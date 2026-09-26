"""build/classify_cash.py — raw cash ledger -> is_spend / exclude_reason / category.

Gates the keyword matchers (`exclusion_for`, `category_for`, `income_for`), the
prefix-matched manual overrides (`override_for`), `_iso`, `_apply_correction`, the
branch order inside `classify` (per-record correction > itemised card > inflow >
exclusion > manual override > category / Uncategorized), and `watch_alerts`.

Every config (categories, exclusions, overrides, watchlist, corrections) is a
fabricated dict passed in — the real data/spending/*.yaml is never read, and `main()`
(which writes build/cash_ledger.csv) is not run.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_classify_cash.py -q
"""
from portfolio.spending import ITEMISED_CARD
from tests.buildscript import load_build_script

cc = load_build_script("classify_cash")

CATS = {
    "groups": {
        "Food": {"Coffee": ["kopi", "cafe"], "Groceries": ["mart"]},
        "Transport": {"Taxi": ["ride"]},
    },
    "income": {"Salary": ["employer"], "Interest": ["interest"]},
}
EXCL = {"cc_payment": ["card bill"], "investment": ["broker"]}
OVERRIDES = {"Special Shop": "Shopping::Gifts", "Plain Group": "Health"}
OEXCL = ["Loan To"]


def row(merchant, amount, source="dbs", description="", txn_date="2025-03-01"):
    return {"source": source, "account_label": "", "txn_date": txn_date, "post_date": "",
            "description": description, "merchant": merchant, "amount_sgd": f"{amount:.2f}",
            "fcy_amount": "", "fcy_currency": "", "direction": "", "source_file": "", "raw": ""}


def one(r, corrections=None, cats=CATS, excl=EXCL, overrides=OVERRIDES, oexcl=OEXCL):
    out, unmatched = cc.classify([r], cats, excl, overrides, oexcl, corrections)
    o = out[0]
    return (o["is_spend"], o["exclude_reason"], o["category"], o["subcategory"]), unmatched


# ------------------------------------------------------------------ matchers

def test_exclusion_for_first_matching_reason_case_insensitive():
    assert cc.exclusion_for("paid card bill to broker", EXCL) == "cc_payment"
    assert cc.exclusion_for("top up broker", EXCL) == "investment"
    assert cc.exclusion_for("groceries", EXCL) is None
    assert cc.exclusion_for("x", {"r": [12345]}) is None     # non-str keywords are str()'d
    assert cc.exclusion_for("ref 12345", {"r": [12345]}) == "r"


def test_category_for_returns_group_and_leaf_or_none_pair():
    assert cc.category_for("test kopi stall", CATS["groups"]) == ("Food", "Coffee")
    assert cc.category_for("night ride", CATS["groups"]) == ("Transport", "Taxi")
    assert cc.category_for("nothing here", CATS["groups"]) == (None, None)


def test_income_for_defaults_to_other_income():
    assert cc.income_for("test employer pte ltd", CATS["income"]) == "Salary"
    assert cc.income_for("mystery", CATS["income"]) == "Other Income"


def test_override_for_matches_merchant_prefix_not_substring():
    assert cc.override_for("SPECIAL SHOP #12", OVERRIDES, OEXCL) == ("Shopping", "Gifts")
    assert cc.override_for("The Special Shop", OVERRIDES, OEXCL) == (None, None)
    assert cc.override_for("plain group clinic", OVERRIDES, OEXCL) == ("Health", None)


def test_override_for_manual_exclude_beats_an_override():
    assert cc.override_for("loan to friend", {"Loan": "Misc::Other"}, OEXCL) == ("EXCLUDE", None)


def test_iso_normalises_spreadsheet_dates_and_passes_through_the_rest():
    assert cc._iso("2025-03-01") == "2025-03-01"
    assert cc._iso("1/3/25") == "2025-03-01"         # D/M/YY, as spreadsheet apps save it
    assert cc._iso("01/03/2025") == "2025-03-01"
    assert cc._iso(" not a date ") == "not a date"
    assert cc._iso(None) == ""


def test_apply_correction_excluded_and_category_targets():
    o = cc._apply_correction({}, "EXCLUDED:transfer")
    assert o == {"is_spend": "false", "exclude_reason": "transfer",
                 "category": "Excluded", "subcategory": "transfer"}
    o = cc._apply_correction({"exclude_reason": "old"}, "Food::Coffee")
    assert o == {"is_spend": "true", "exclude_reason": "", "category": "Food",
                 "subcategory": "Coffee"}
    assert cc._apply_correction({}, "Food")["subcategory"] == ""


# ------------------------------------------------------------------ classify branch order

def test_per_record_correction_wins_over_every_rule():
    r = row("TEST BROKER", -500.0)                   # would otherwise be excluded
    corr = {("dbs", "2025-03-01", -500.0, "TEST BROKER"): "Food::Groceries"}
    assert one(r, corr)[0] == ("true", "", "Food", "Groceries")


def test_correction_key_uses_the_first_40_chars_of_the_merchant():
    long_name = "M" * 50
    corr = {("dbs", "2025-03-01", -1.0, "M" * 40): "EXCLUDED:manual"}
    assert one(row(long_name, -1.0), corr)[0][0] == "false"


def test_itemised_card_debit_is_spend_even_when_an_exclusion_matches():
    got, _ = one(row("TEST BROKER KOPI", -5.0, source=ITEMISED_CARD))
    assert got == ("true", "", "Food", "Coffee")


def test_itemised_card_credit_stays_spend_so_it_nets_in_its_category():
    got, _ = one(row("TEST CAFE", 5.0, source=ITEMISED_CARD))
    assert got == ("true", "", "Food", "Coffee")


def test_itemised_card_manual_exclude_and_override():
    assert one(row("LOAN TO X", -5.0, source=ITEMISED_CARD))[0] == (
        "false", "manual", "Excluded", "manual")
    assert one(row("SPECIAL SHOP", -5.0, source=ITEMISED_CARD))[0] == (
        "true", "", "Shopping", "Gifts")


def test_inflow_on_a_card_bill_source_is_a_card_repayment():
    for src in ("hsbc", "trust"):
        assert one(row("PAYMENT RECEIVED", 100.0, source=src))[0] == (
            "false", "cc_payment", "Income", "Card Repayment")


def test_inflow_on_the_bank_is_income_with_its_leaf():
    assert one(row("TEST EMPLOYER", 3000.0))[0] == ("false", "income", "Income", "Salary")
    assert one(row("MYSTERY", 0.0))[0] == ("false", "income", "Income", "Other Income")


def test_outflow_exclusion_beats_override_and_category():
    # merchant also starts with an override key and contains a category keyword
    r = row("SPECIAL SHOP KOPI", -10.0, description="card bill")
    assert one(r)[0] == ("false", "cc_payment", "Excluded", "cc_payment")


def test_outflow_manual_exclude():
    assert one(row("LOAN TO FRIEND", -10.0))[0] == ("false", "manual", "Excluded", "manual")


def test_outflow_override_beats_keyword_category():
    assert one(row("SPECIAL SHOP KOPI", -10.0))[0] == ("true", "", "Shopping", "Gifts")
    assert one(row("PLAIN GROUP KOPI", -10.0))[0] == ("true", "", "Health", "")


def test_outflow_keyword_category_matches_description_too():
    assert one(row("TEST STORE", -10.0, description="neighbourhood mart"))[0] == (
        "true", "", "Food", "Groceries")


def test_unmatched_spend_is_uncategorized_and_counted():
    rows = [row("UNKNOWN PLACE", -1.0), row("UNKNOWN PLACE", -2.0), row("X" * 70, -3.0)]
    out, unmatched = cc.classify(rows, CATS, EXCL, OVERRIDES, OEXCL)
    assert {(o["category"], o["subcategory"], o["is_spend"]) for o in out} == {
        ("Uncategorized", "", "true")}
    assert unmatched == {"UNKNOWN PLACE": 2, "X" * 60: 1}


def test_classify_output_has_every_out_col_and_keeps_row_fields():
    out, _ = cc.classify([row("TEST CAFE", -4.0)], {}, {}, {}, [])
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
