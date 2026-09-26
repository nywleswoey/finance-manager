"""build/parse_cash.py — the bank + card statement parsers behind cash_ledger_raw.csv.

Gates the money/date helpers, the DBS bank row assembly (`_name_from`, `_dbs_finish`,
and `parse_dbs`'s running-balance direction), the Trust card's cycle-year inference
(`_year_for`, `parse_trust`), the DBS card CSV path (`_clean_cc_merchant`,
`parse_dbs_cc`, `_cancel_reversals`), and the bank-side card-bill suppression
(`_cc_windows`, `_is_suppressed_cc_bill`).

Statement readers are pointed at a tmp_path (ROOT / DBS_CC_DIR monkeypatched) and fed
fabricated text through a patched `raw_text`; `main()` is never run, so nothing is
written to build/. The itemised card number lives only in the module
(`DBS_CC_CARD`) and is referenced, never retyped.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_cash.py -q
"""
import datetime as dt

import pytest

from tests.buildscript import load_build_script

pc = load_build_script("parse_cash")

D = dt.date


# ------------------------------------------------------------------ helpers

def test_money_strips_separators_and_a_leading_plus():
    assert pc.money("1,234.56") == 1234.56
    assert pc.money("+12.00") == 12.0
    assert pc.money("-3.50") == -3.5
    assert pc.money(7) == 7.0
    with pytest.raises(ValueError):
        pc.money("")


def test_num_is_lenient_zero_on_blank_or_junk():
    assert pc._num("1,234.5") == 1234.5
    assert pc._num(" 2.00 ") == 2.0
    assert pc._num("") == 0.0
    assert pc._num(None) == 0.0
    assert pc._num("n/a") == 0.0


def test_pdate_reads_the_three_statement_formats():
    assert pc._pdate("23 Feb 2026") == D(2026, 2, 23)
    assert pc._pdate("2026-02-23") == D(2026, 2, 23)
    assert pc._pdate("23/02/2026") == D(2026, 2, 23)
    assert pc._pdate("Feb 23 2026") is None
    assert pc._pdate("") is None


# ------------------------------------------------------------------ DBS bank

def test_name_from_prefers_the_to_payee():
    assert pc._name_from("NETS QR PAYMENT 123456 TO: KOPI STALL") == "KOPI STALL"
    assert pc._name_from("TO :ACME PTE LTD") == "ACME PTE LTD"


def test_name_from_falls_back_to_the_first_chunk_capped_at_120():
    assert pc._name_from("FAST PAYMENT  OTHER  REF 42") == "FAST PAYMENT"
    assert pc._name_from("X" * 200) == "X" * 120
    assert pc._name_from("") == ""


def _cur(amount, detail=("TO: TEST MERCHANT",), txntype="FAST Payment"):
    return dict(date=D(2025, 3, 4), txntype=txntype, amount=amount, detail=list(detail))


def test_dbs_finish_builds_a_signed_row():
    r = pc._dbs_finish(_cur(-12.5), "data/x.pdf")
    assert r["source"] == "dbs" and r["account_label"] == "DBS"
    assert r["txn_date"] == r["post_date"] == "2025-03-04"
    assert r["amount_sgd"] == "-12.50" and r["direction"] == "debit"
    assert r["merchant"] == "TEST MERCHANT"
    assert r["description"] == "FAST Payment | TO: TEST MERCHANT"
    assert r["raw"] == "FAST Payment || TO: TEST MERCHANT"
    assert r["source_file"] == "data/x.pdf"
    assert set(r) == set(pc.COLS)


def test_dbs_finish_credit_and_merchant_fallback_to_txntype():
    r = pc._dbs_finish(_cur(100.0, detail=(), txntype="Interest Earned"), "s")
    assert r["direction"] == "credit" and r["amount_sgd"] == "100.00"
    assert r["merchant"] == "Interest Earned"
    assert r["description"] == "Interest Earned"


def test_dbs_finish_drops_a_zero_amount():
    assert pc._dbs_finish(_cur(0), "s") is None


def _statement(tmp_path, monkeypatch, subdir, name, text):
    d = tmp_path / "data" / subdir
    d.mkdir(parents=True)
    (d / name).write_bytes(b"")
    monkeypatch.setattr(pc, "ROOT", str(tmp_path))
    monkeypatch.setattr(pc, "raw_text", lambda path: text)


def test_parse_dbs_derives_direction_from_the_running_balance(tmp_path, monkeypatch):
    text = "\n".join([
        "DBS Multiplier Account  Account No. 000-000000-0",
        "Date  Description  Withdrawal (-)  Deposit (+)  Balance",
        "01/03/2025  Balance Brought Forward                         1,000.00",
        "02/03/2025  FAST Payment          200.00                      800.00",
        "TO: TEST PAYEE",
        "Page 2 of 5",
        "05/03/2025  Salary                         3,000.00         3,800.00",
        "TEST EMPLOYER PTE LTD",
        "31/03/2025  Balance Carried Forward                         3,800.00",
        "Supplementary Retirement Scheme",
        "06/03/2025  Ignored               1.00                        1.00",
    ])
    _statement(tmp_path, monkeypatch, "dbs-consolidated-statements", "dbs_202503.pdf", text)
    rows = pc.parse_dbs()
    assert [(r["txn_date"], r["amount_sgd"], r["direction"], r["merchant"]) for r in rows] == [
        ("2025-03-02", "-200.00", "debit", "TEST PAYEE"),
        ("2025-03-05", "3000.00", "credit", "TEST EMPLOYER PTE LTD"),
    ]
    assert rows[0]["source_file"] == "data/dbs-consolidated-statements/dbs_202503.pdf"


def test_parse_dbs_skips_statements_before_start(tmp_path, monkeypatch):
    text = ("DBS Multiplier Account\n01/12/2024  Balance Brought Forward  10.00\n"
            "02/12/2024  Payment  5.00  5.00\n")
    _statement(tmp_path, monkeypatch, "dbs-consolidated-statements", "dbs_202412.pdf", text)
    assert pc.parse_dbs() == []


# ------------------------------------------------------------------ Trust card

CYCLE = (D(2024, 12, 20), D(2025, 1, 19))


def test_year_for_places_each_side_of_a_year_straddling_cycle():
    assert pc._year_for(25, "Dec", *CYCLE) == D(2024, 12, 25)
    assert pc._year_for(5, "Jan", *CYCLE) == D(2025, 1, 5)


def test_year_for_allows_three_days_of_slack_around_the_cycle():
    assert pc._year_for(17, "Dec", *CYCLE) == D(2024, 12, 17)
    assert pc._year_for(22, "Jan", *CYCLE) == D(2025, 1, 22)


def test_year_for_outside_the_window_falls_back_to_the_start_year():
    assert pc._year_for(10, "Jun", *CYCLE) == D(2024, 6, 10)


def test_year_for_impossible_or_unknown_dates_are_none():
    assert pc._year_for(29, "Feb", D(2025, 2, 1), D(2025, 2, 28)) is None
    assert pc._year_for(1, "Foo", *CYCLE) is None


def test_parse_trust_signs_credits_and_uses_the_wrapped_merchant(tmp_path, monkeypatch):
    text = "\n".join([
        "Statement period  20 Dec 2024 - 19 Jan 2025",
        "Posting date  Description  Amount in SGD",
        "28 Dec  29 Dec  TEST CAFE                          12.30",
        "A VERY LONG TEST MERCHANT NAME",
        "03 Jan  04 Jan                              10.00   13.50",
        "05 Jan  06 Jan  TEST REFUND                       +5.00",
        "19 Jan  19 Jan  Total outstanding balance         20.80",
    ])
    _statement(tmp_path, monkeypatch, "trust-cc", "202501.pdf", text)
    rows = pc.parse_trust()
    assert [(r["txn_date"], r["post_date"], r["merchant"], r["amount_sgd"], r["direction"])
            for r in rows] == [
        ("2024-12-28", "2024-12-29", "TEST CAFE", "-12.30", "debit"),
        ("2025-01-03", "2025-01-04", "A VERY LONG TEST MERCHANT NAME", "-13.50", "debit"),
        ("2025-01-05", "2025-01-06", "TEST REFUND", "5.00", "credit"),
    ]
    assert rows[1]["fcy_amount"] == "10.00"


# ------------------------------------------------------------------ DBS card CSV

def test_clean_cc_merchant_strips_location_and_instalment_suffixes():
    assert pc._clean_cc_merchant("TEST SHOP SINGAPORE SGP") == "TEST SHOP"
    assert pc._clean_cc_merchant("TEST SHOP SGP") == "TEST SHOP"
    assert pc._clean_cc_merchant("TEST SHOP SINGAPORE 123456") == "TEST SHOP"
    assert pc._clean_cc_merchant("TEST SHOP SINGAPORE") == "TEST SHOP"
    assert pc._clean_cc_merchant("TEST STORE-MP12") == "TEST STORE"
    assert pc._clean_cc_merchant("SINGAPORE POOLS") == "SINGAPORE POOLS"   # only a trailing token


def _ccrow(merchant, amount, source="dbs-cc"):
    return {"source": source, "merchant": merchant, "amount_sgd": f"{amount:.2f}"}


def test_cancel_reversals_drops_an_equal_and_opposite_pair():
    rows = [_ccrow("FEE", -196.20), _ccrow("SHOP", -10.0), _ccrow("FEE", 196.20)]
    assert pc._cancel_reversals(rows) == [_ccrow("SHOP", -10.0)]


def test_cancel_reversals_keeps_a_partial_refund():
    rows = [_ccrow("SHOP", -100.0), _ccrow("SHOP", 30.0)]
    assert pc._cancel_reversals(rows) == rows


def test_cancel_reversals_needs_the_same_merchant():
    rows = [_ccrow("SHOP A", -50.0), _ccrow("SHOP B", 50.0)]
    assert pc._cancel_reversals(rows) == rows


def test_cancel_reversals_one_credit_cancels_only_one_debit():
    rows = [_ccrow("SHOP", -20.0), _ccrow("SHOP", -20.0), _ccrow("SHOP", 20.0)]
    assert pc._cancel_reversals(rows) == [_ccrow("SHOP", -20.0)]


def test_cancel_reversals_works_when_the_credit_comes_first():
    rows = [_ccrow("SHOP", 20.0), _ccrow("SHOP", -20.0)]
    assert pc._cancel_reversals(rows) == []


CC_CSV = "\n".join([
    "Card Transaction History",
    "Card No.,XXXX-XXXX-XXXX-0000",
    "",
    "Transaction Date,Posting Date,Description,Transaction Type,Payment Type,Status,Debit Amount,Credit Amount",
    "03 Feb 2026,04 Feb 2026,TEST CAFE SINGAPORE SGP,PURCHASE,Contactless,Settled,12.30,",
    "03 Feb 2026,04 Feb 2026,TEST CAFE SINGAPORE SGP,PURCHASE,Contactless,Settled,12.30,",
    "05 Feb 2026,06 Feb 2026,TEST STORE-MP12,INSTALMENT PLANS & LOANS,,Settled,50.00,",
    "05 Feb 2026,06 Feb 2026,TEST STORE,ADJUSTMENT OF INSTALMENT PLANS & LOANS,,Settled,,600.00",
    "10 Feb 2026,10 Feb 2026,PAYMENT - THANK YOU,PAYMENT,,Settled,,900.00",
    "12 Feb 2026,,TEST SHOP SINGAPORE,PURCHASE,,Settled,40.00,",
    "14 Feb 2026,15 Feb 2026,TEST SHOP,REFUND,,Settled,,15.00",
    "15 Feb 2026,15 Feb 2026,ZERO LINE,PURCHASE,,Settled,,",
    "not a date,15 Feb 2026,BAD DATE,PURCHASE,,Settled,1.00,",
    "short,row",
    "",
])


def test_parse_dbs_cc_skips_payments_instalments_and_duplicates(tmp_path, monkeypatch):
    ccdir = tmp_path / "data" / "dbs-cc"
    ccdir.mkdir(parents=True)
    (ccdir / "feb.csv").write_text(CC_CSV)
    monkeypatch.setattr(pc, "ROOT", str(tmp_path))
    monkeypatch.setattr(pc, "DBS_CC_DIR", str(ccdir))
    rows, closes = pc.parse_dbs_cc()
    assert [(r["txn_date"], r["post_date"], r["merchant"], r["amount_sgd"], r["direction"])
            for r in rows] == [
        ("2026-02-03", "2026-02-04", "TEST CAFE", "-12.30", "debit"),    # duplicate collapsed
        ("2026-02-12", "2026-02-12", "TEST SHOP", "-40.00", "debit"),    # blank post date -> txn date
        ("2026-02-14", "2026-02-15", "TEST SHOP", "15.00", "credit"),    # partial refund kept
    ]
    assert rows[0]["description"] == "TEST CAFE | PURCHASE"
    assert rows[0]["raw"] == "TEST CAFE SINGAPORE SGP || PURCHASE"
    assert rows[0]["source_file"] == "data/dbs-cc/feb.csv"
    assert {r["source"] for r in rows} == {"dbs-cc"}
    # the closing date is the latest dated line, PAYMENT and zero rows included
    assert closes == [D(2026, 2, 15)]


def test_parse_dbs_cc_collapses_a_line_repeated_across_overlapping_files(tmp_path, monkeypatch):
    head = ("Transaction Date,Posting Date,Description,Transaction Type,Payment Type,Status,"
            "Debit Amount,Credit Amount\n")
    line = "03 Feb 2026,04 Feb 2026,TEST CAFE,PURCHASE,,Settled,12.30,\n"
    (tmp_path / "a.csv").write_text(head + line)
    (tmp_path / "b.csv").write_text(head + line + "20 Feb 2026,21 Feb 2026,OTHER,PURCHASE,,Settled,1.00,\n")
    monkeypatch.setattr(pc, "ROOT", str(tmp_path))
    monkeypatch.setattr(pc, "DBS_CC_DIR", str(tmp_path))
    rows, closes = pc.parse_dbs_cc()
    assert [r["merchant"] for r in rows] == ["TEST CAFE", "OTHER"]
    assert sorted(closes) == [D(2026, 2, 3), D(2026, 2, 20)]


def test_parse_dbs_cc_with_no_files_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "DBS_CC_DIR", str(tmp_path))
    assert pc.parse_dbs_cc() == ([], [])


# ------------------------------------------------------------------ card-bill suppression

def test_cc_windows_is_5_to_45_days_after_each_distinct_close():
    wins = pc._cc_windows([D(2026, 1, 15), D(2026, 1, 15), D(2026, 3, 15)])
    assert sorted(wins) == [(D(2026, 1, 20), D(2026, 3, 1)), (D(2026, 3, 20), D(2026, 4, 29))]
    assert pc._cc_windows([]) == []


WIN = [(D(2026, 1, 20), D(2026, 3, 1))]


def _bank(raw, txn_date="2026-02-01", source="dbs"):
    return {"source": source, "raw": raw, "txn_date": txn_date}


def test_card_centre_giro_in_a_window_is_suppressed_edges_inclusive():
    assert pc._is_suppressed_cc_bill(_bank("GIRO || DBS CARD CENTRE"), WIN)
    assert pc._is_suppressed_cc_bill(_bank("GIRO || DBS CARD CENTRE", "2026-01-20"), WIN)
    assert pc._is_suppressed_cc_bill(_bank("GIRO || DBS CARD CENTRE", "2026-03-01"), WIN)


def test_itemised_card_number_in_a_window_is_suppressed():
    assert pc._is_suppressed_cc_bill(_bank(f"Bill Payment || {pc.DBS_CC_CARD}"), WIN)


def test_bill_outside_every_window_is_kept():
    assert not pc._is_suppressed_cc_bill(_bank("GIRO || DBS CARD CENTRE", "2026-03-02"), WIN)
    assert not pc._is_suppressed_cc_bill(_bank("GIRO || DBS CARD CENTRE"), [])


def test_other_payees_and_non_bank_rows_are_kept():
    assert not pc._is_suppressed_cc_bill(_bank("Bill Payment || OTHER CARD 0000"), WIN)
    assert not pc._is_suppressed_cc_bill(_bank("DBS CARD CENTRE", source="dbs-cc"), WIN)
    assert not pc._is_suppressed_cc_bill(_bank("DBS CARD CENTRE", txn_date="bad"), WIN)
