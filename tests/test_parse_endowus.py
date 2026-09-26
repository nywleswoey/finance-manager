"""build/parse_endowus.py — transaction-line parsing for both statement layouts.

Gates `parse_txns` (later "DD Mon YYYY" layout A with a Buy/Sell column and funding
source, carried as a 7th field; earlier "DD/MM/YYYY" layout B where the type alone sets the
sign and the funding is EARLY_FUNDING) and its `isoA` / `isoB` helpers. `main()` is not run: it reads statements and writes
build/endowus_events.csv. Every statement line here is fabricated.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_endowus.py -q
"""
import pytest

from tests.buildscript import load_build_script

pe = load_build_script("parse_endowus")


def test_iso_helpers_read_each_layouts_date():
    assert pe.isoA("09 Apr 2025") == "2025-04-09"
    assert pe.isoB("27/04/2023") == "2023-04-27"      # day first, not month first
    with pytest.raises(ValueError):
        pe.isoB("2023-04-27")


def test_layout_a_buy_is_positive_units_with_price_and_amount():
    txt = "12 Mar 2024  Investment  Buy  Test Growth   Fund  CPF OA  1,001.2345  S$1.23  S$1,231.52\n"
    assert pe.parse_txns(txt) == [
        ("2024-03-12", "Investment", "Test Growth Fund", 1001.2345, 1.23, 1231.52, "CPF OA")]


def test_layout_a_sell_is_negative_units_whatever_the_type():
    txt = ("15 Jul 2025  Endowus Fee  Sell Test Growth Fund  CPF OA    0.30560  S$198.66     S$60.71\n"
           "16 Jul 2025  Rebalancing  Sell Test Growth Fund  SRS    2.00000  S$10.00     S$20.00\n")
    rows = pe.parse_txns(txt)
    assert [(r[1], r[3]) for r in rows] == [("Endowus Fee", -0.3056), ("Rebalancing", -2.0)]
    # amount stays unsigned — only units carry the direction
    assert [r[5] for r in rows] == [60.71, 20.0]
    assert [r[6] for r in rows] == ["CPF OA", "SRS"]


def test_layout_a_needs_a_known_funding_source():
    txt = "12 Mar 2024  Investment  Buy  Test Fund  Wallet  1.0000  S$1.00  S$1.00\n"
    assert pe.parse_txns(txt) == []


def test_layout_b_investment_positive_redemption_and_fee_negative():
    # layout B prints the amount twice; the first one is taken
    txt = ("27/04/2023 Investment  Test Growth  393.2710  S$131.85  S$51,852.90 S$51,852.90\n"
           "26/07/2023 Redemption   Test Growth   0.2850  S$145.62      S$41.47    S$41.47\n"
           "26/07/2023 Endowus Fee   Test Growth   0.1000  S$145.62      S$14.56    S$14.56\n"
           "28/07/2023 Subscription   Test Growth   1.0000  S$145.00      S$145.00    S$145.00\n")
    assert pe.parse_txns(txt) == [
        ("2023-04-27", "Investment", "Test Growth", 393.271, 131.85, 51852.9, pe.EARLY_FUNDING),
        ("2023-07-26", "Redemption", "Test Growth", -0.285, 145.62, 41.47, pe.EARLY_FUNDING),
        ("2023-07-26", "Endowus Fee", "Test Growth", -0.1, 145.62, 14.56, pe.EARLY_FUNDING),
        ("2023-07-28", "Subscription", "Test Growth", 1.0, 145.0, 145.0, pe.EARLY_FUNDING),
    ]


def test_a_mixed_statement_lists_layout_a_rows_before_layout_b_rows():
    txt = ("27/04/2023 Investment  Old Fund  1.0000  S$1.00  S$1.00 S$1.00\n"
           "12 Mar 2024  Investment  Buy  New Fund  Cash  2.0000  S$1.00  S$2.00\n")
    assert [r[2] for r in pe.parse_txns(txt)] == ["New Fund", "Old Fund"]


def test_non_transaction_lines_are_ignored():
    txt = ("Transactions\nDate  Type  Fund  Units  Price  Amount\n"
           "Test Growth Fund  Equity  CPF OA  12.34500  S$1,000.00\n")
    assert pe.parse_txns(txt) == []
