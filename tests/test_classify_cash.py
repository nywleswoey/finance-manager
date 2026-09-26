"""build/classify_cash.py — raw cash ledger -> is_spend / exclude_reason.

Gates the exclusion keyword matcher (`exclusion_for`), the prefix-matched manual exclude
list (`manually_excluded`), `_iso`, the branch order inside `classify` (per-record correction
> itemised card > inflow > exclusion > manual exclude > spend), and `watch_alerts`. Category
is DB-owned (portfolio.classify), so this script decides spend only.

Every config (exclusions, the exclude list, watchlist, corrections) is a fabricated value
passed in — the real data/spending/*.yaml is never read, and `main()` (which writes
build/cash_ledger.csv) is not run.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_classify_cash.py -q
"""
from portfolio.spending import ITEMISED_CARD
from tests.buildscript import load_build_script

cc = load_build_script("classify_cash")

EXCL = {"cc_payment": ["card bill"], "investment": ["broker"]}
OEXCL = ["Loan To"]


def row(merchant, amount, source="dbs", description="", txn_date="2025-03-01"):
    return {"source": source, "account_label": "", "txn_date": txn_date, "post_date": "",
            "description": description, "merchant": merchant, "amount_sgd": f"{amount:.2f}",
            "fcy_amount": "", "fcy_currency": "", "direction": "", "source_file": "", "raw": ""}


def one(r, corrections=None, excl=EXCL, oexcl=OEXCL):
    o = cc.classify([r], excl, oexcl, corrections)[0]
    return o["is_spend"], o["exclude_reason"]


# ------------------------------------------------------------------ matchers

def test_exclusion_for_first_matching_reason_case_insensitive():
    assert cc.exclusion_for("paid card bill to broker", EXCL) == "cc_payment"
    assert cc.exclusion_for("top up broker", EXCL) == "investment"
    assert cc.exclusion_for("groceries", EXCL) is None
    assert cc.exclusion_for("x", {"r": [12345]}) is None     # non-str keywords are str()'d
    assert cc.exclusion_for("ref 12345", {"r": [12345]}) == "r"


def test_manually_excluded_matches_merchant_prefix_not_substring():
    assert cc.manually_excluded("LOAN TO FRIEND", OEXCL)
    assert not cc.manually_excluded("A LOAN TO FRIEND", OEXCL)
    assert not cc.manually_excluded("LOAN TO FRIEND", [])


def test_iso_normalises_spreadsheet_dates_and_passes_through_the_rest():
    assert cc._iso("2025-03-01") == "2025-03-01"
    assert cc._iso("1/3/25") == "2025-03-01"         # D/M/YY, as spreadsheet apps save it
    assert cc._iso("01/03/2025") == "2025-03-01"
    assert cc._iso(" not a date ") == "not a date"
    assert cc._iso(None) == ""


# ------------------------------------------------------------------ classify branch order

def test_per_record_correction_wins_over_every_rule():
    r = row("TEST BROKER", -500.0)                   # would otherwise be excluded
    corr = {("dbs", "2025-03-01", -500.0, "TEST BROKER"): "Food::Groceries"}
    assert one(r, corr) == ("true", "")
    corr = {("dbs", "2025-03-01", -5.0, "TEST CAFE"): "EXCLUDED:transfer"}
    assert one(row("TEST CAFE", -5.0), corr) == ("false", "transfer")


def test_correction_key_uses_the_first_40_chars_of_the_merchant():
    long_name = "M" * 50
    corr = {("dbs", "2025-03-01", -1.0, "M" * 40): "EXCLUDED:manual"}
    assert one(row(long_name, -1.0), corr) == ("false", "manual")


def test_itemised_card_debit_is_spend_even_when_an_exclusion_matches():
    assert one(row("TEST BROKER", -5.0, source=ITEMISED_CARD)) == ("true", "")


def test_itemised_card_credit_stays_spend_so_it_nets_in_its_category():
    assert one(row("TEST CAFE", 5.0, source=ITEMISED_CARD)) == ("true", "")


def test_itemised_card_manual_exclude():
    assert one(row("LOAN TO X", -5.0, source=ITEMISED_CARD)) == ("false", "manual")


def test_inflow_on_a_card_bill_source_is_a_card_repayment():
    for src in ("hsbc", "trust"):
        assert one(row("PAYMENT RECEIVED", 100.0, source=src)) == ("false", "cc_payment")


def test_inflow_on_the_bank_is_income():
    assert one(row("TEST EMPLOYER", 3000.0)) == ("false", "income")
    assert one(row("MYSTERY", 0.0)) == ("false", "income")


def test_outflow_exclusion_beats_manual_exclude():
    r = row("LOAN TO BROKER", -10.0, description="card bill")
    assert one(r) == ("false", "cc_payment")


def test_outflow_manual_exclude():
    assert one(row("LOAN TO FRIEND", -10.0)) == ("false", "manual")


def test_exclusion_matches_description_too():
    assert one(row("TEST STORE", -10.0, description="monthly card bill")) == \
        ("false", "cc_payment")


def test_any_other_outflow_is_spend():
    assert one(row("UNKNOWN PLACE", -1.0)) == ("true", "")


def test_classify_output_has_every_out_col_and_keeps_row_fields():
    out = cc.classify([row("TEST CAFE", -4.0)], {}, [])
    assert list(out[0]) == cc.OUT_COLS
    assert out[0]["merchant"] == "TEST CAFE" and out[0]["amount_sgd"] == "-4.00"


# ------------------------------------------------------------------ watch_alerts

def _spend(merchant, amount, is_spend="true"):
    return {"is_spend": is_spend, "merchant": merchant, "amount_sgd": f"{amount:.2f}",
            "txn_date": "2025-03-01"}


def test_watch_alerts_prefix_min_amount_and_spend_only():
    out = [_spend("TEST SUB MONTHLY", -20.0), _spend("TEST SUB", -5.0),
           _spend("TEST SUB", -50.0, is_spend="false"), _spend("OTHER TEST SUB", -99.0)]
    wl = {"watch": [{"match": "test sub", "min_amount": 10, "note": "what is this?"}]}
    assert cc.watch_alerts(out, wl) == [("2025-03-01", 20.0, "TEST SUB MONTHLY", "what is this?")]


def test_watch_alerts_min_amount_defaults_to_zero_and_empty_watchlist():
    out = [_spend("TEST SUB", -0.5), _spend("TEST SUB", 3.0)]   # a credit is below 0
    assert cc.watch_alerts(out, {"watch": [{"match": "TEST", "note": "n"}]}) == [
        ("2025-03-01", 0.5, "TEST SUB", "n")]
    assert cc.watch_alerts(out, {}) == []
