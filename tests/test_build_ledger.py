"""build/build_ledger.py row rules, on synthetic rows.

data/ is gitignored, so CI cannot run the builder end to end. These pin the rules that
change positions: the FSM nil-paid skip, the S51 consolidation sign, and the two custody-move
repairs (synthesize_transfer_ins, reconcile_transfer_amounts).

The script runs as `python build/build_ledger.py` and imports its siblings by bare name.
Load it the same way; importing it runs nothing.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_build_ledger.py -q
"""
import csv
import importlib.util
import os
import sys

import pytest

_BUILD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "build")
sys.path.insert(0, _BUILD)
try:
    _spec = importlib.util.spec_from_file_location(
        "build_ledger_under_test", os.path.join(_BUILD, "build_ledger.py"))
    BL = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(BL)
finally:
    sys.path.remove(_BUILD)

FSM_COLS = ["Transaction Date", "Transaction Type", "Product Name", "Payment Method",
            "Quantity", "Product Currency", "Transaction Price", "Product Amount",
            "Investment Amount", "Redemption Amount", "Total Fee"]


@pytest.fixture(autouse=True)
def empty_ledger():
    BL.LEDGER.clear()
    yield
    BL.LEDGER.clear()


def _fsm(tmp_path, monkeypatch, rows):
    (tmp_path / "fsm").mkdir()
    with open(tmp_path / "fsm" / "ifast_historical.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, FSM_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({"Transaction Date": "01 Jun 2023", "Payment Method": "Cash",
                        "Product Currency": "SGD", "Transaction Price": "1",
                        "Product Amount": "100", "Investment Amount": "100",
                        "Total Fee": "0", **r})
    monkeypatch.setattr(BL, "DATA", str(tmp_path))
    BL.load_fsm()
    return [(r["ticker"], r["action"], r["qty_signed"]) for r in BL.LEDGER]


def test_fsm_nil_paid_rights_placeholders_are_skipped(tmp_path, monkeypatch):
    """"NRO (...)" / "R (...)" rows convert away; the share delivery is the Corp Action."""
    rows = _fsm(tmp_path, monkeypatch, [
        {"Transaction Type": "Corp Action", "Product Name": "IREIT NRO (8U7)", "Quantity": "500"},
        {"Transaction Type": "Corp Action", "Product Name": "IREIT R (8U7R)", "Quantity": "500"},
        {"Transaction Type": "Corp Action", "Product Name": "IREIT Global (UD1U)",
         "Quantity": "500"},
    ])
    assert rows == [("UD1U", "corp action", 500.0)]


def test_seatrium_s51_corp_action_retires_the_old_counter(tmp_path, monkeypatch):
    """The Seatrium consolidation books the OLD S51 shares out and the NEW 5E2 shares in.
    S51 rights under the SembCorp Marine name stay a delivery (+)."""
    rows = _fsm(tmp_path, monkeypatch, [
        {"Transaction Type": "Corp Action", "Product Name": "SembCorp Marine (S51)",
         "Quantity": "2000"},
        {"Transaction Type": "Corp Action", "Product Name": "Seatrium Ltd (S51)",
         "Quantity": "4000"},
        {"Transaction Type": "Corp Action", "Product Name": "Seatrium Ltd (5E2)",
         "Quantity": "200"},
    ])
    assert rows == [("S51", "corp action", 2000.0), ("S51", "corp action", -4000.0),
                    ("5E2", "corp action", 200.0)]


def test_a_receiver_short_by_a_matching_transfer_out_gets_the_missing_leg():
    BL.add(date="2020-01-01", account="CDP", market="SG", ticker="D05",
           action="buy", qty_signed=100.0, source="cdp")
    BL.add(date="2021-03-01", account="CDP", market="SG", ticker="D05",
           action="transfer_out", qty_signed=-100.0, source="cdp")
    BL.add(date="2021-04-01", account="FSM", market="SG", ticker="D05",
           action="sell", qty_signed=-100.0, source="fsm")
    BL.synthesize_transfer_ins()
    synth = [r for r in BL.LEDGER if r["source"] == "synthesized (custody move)"]
    assert len(synth) == 1
    s = synth[0]
    assert (s["account"], s["ticker"], s["action"], s["qty_signed"], s["date"]) == \
        ("FSM", "D05", "transfer_in", 100.0, "2021-03-01")


def test_no_leg_is_synthesized_without_a_same_quantity_transfer_out():
    BL.add(date="2020-01-01", account="CDP", market="SG", ticker="D05",
           action="buy", qty_signed=60.0, source="cdp")
    BL.add(date="2021-03-01", account="CDP", market="SG", ticker="D05",
           action="transfer_out", qty_signed=-60.0, source="cdp")
    BL.add(date="2021-04-01", account="FSM", market="SG", ticker="D05",
           action="sell", qty_signed=-100.0, source="fsm")
    BL.add(date="2021-04-01", account="SRS(via-iFast-dup)", market="SG", ticker="D05",
           action="sell", qty_signed=-60.0, source="fsm")     # not a real account
    BL.synthesize_transfer_ins()
    assert not [r for r in BL.LEDGER if r["source"] == "synthesized (custody move)"]


def test_a_transfer_in_carries_the_sending_legs_cost():
    """The receiver stamps market value on the move date; cost basis travels with the shares."""
    BL.add(date="2021-03-01", account="CDP", market="SG", ticker="D05",
           action="transfer_out", qty_signed=-100.0, amount=-2000.0, price="20", source="cdp")
    BL.add(date="2021-03-02", account="FSM", market="SG", ticker="D05",
           action="transfer in", qty_signed=100.0, amount=2600.0, price="26", source="fsm")
    BL.reconcile_transfer_amounts()
    tin = BL.LEDGER[1]
    assert (tin["amount"], tin["price"]) == (-2000.0, "20")


def test_fx_cash_transfers_keep_their_own_amounts():
    """No ticker means a currency conversion, whose two legs genuinely differ."""
    BL.add(date="2021-03-01", account="Tiger Prime", ticker="", asset_type="cash",
           action="transfer_out", qty_signed=0, amount=-1000.0, source="tiger")
    BL.add(date="2021-03-01", account="Tiger Prime", ticker="", asset_type="cash",
           action="transfer_in", qty_signed=0, amount=740.0, source="tiger")
    BL.reconcile_transfer_amounts()
    assert BL.LEDGER[1]["amount"] == 740.0


def test_endowus_funding_maps_to_its_account_and_an_unknown_one_stops_the_build():
    assert BL.endowus_account("CPF OA") == "CPF"
    assert BL.endowus_account("SRS") == "SRS"
    with pytest.raises(SystemExit, match="Cash"):
        BL.endowus_account("Cash")
