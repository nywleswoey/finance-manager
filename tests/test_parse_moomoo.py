"""build/parse_moomoo.py — Moomoo PDF statement tables -> month-end quantities + trades.

Gates `f2`, `parse(path)` (per-symbol rows: an 11-number change table takes endQ from
nums[3], an 8-9-number holdings table from nums[2]; the ticker is the next bare-code
line) and `trades(path)` (priced "Buy to Open"/"Sell to Close" lines, ticker from the
nearby time-stamped line). `raw_text` is patched with fabricated text; the path only
has to carry a 6-digit YYYYMM and is never opened. `main()` is not run.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_moomoo.py -q
"""
import pytest

from tests.buildscript import load_build_script

pm = load_build_script("parse_moomoo")

PATH = "/nowhere/moomoo_202403.pdf"


@pytest.fixture
def text(monkeypatch):
    def feed(s):
        monkeypatch.setattr(pm, "raw_text", lambda path: s)
    return feed


def test_f2_strips_signs_and_separators_and_zeroes_blanks():
    assert pm.f2("1,234.5") == 1234.5
    assert pm.f2("+10") == 10.0
    assert pm.f2("-3.25") == -3.25
    assert pm.f2("") == 0.0
    assert pm.f2("-") == 0.0


def test_parse_change_table_takes_end_quantity(text):
    text("\n".join([
        "TEST HOLDINGS LTD",
        "SGX SGD 1,000 1.10 1,100.00 1,500 1.20 1,800.00 +700.00 500 0 0 0",
        "T01",
        "TEST US CORP",
        "  US USD 10 100.00 1,000.00 5 110.00 550.00 -450.00 0 5 0 0",
        "",
        "TUS",
    ]))
    assert pm.parse(PATH) == [
        dict(month="2024-03", ticker="T01", market="SG", currency="SGD", endQ=1500.0),
        dict(month="2024-03", ticker="TUS", market="US", currency="USD", endQ=5.0),
    ]


def test_parse_holdings_table_takes_quantity_column(text):
    text("\n".join([
        "HK TEST CO",
        "SEHK HKD 2,000 0 2,000 1 3.50 7,000.00 0.17 1,190.00",
        "700",
        "NASDAQ USD 3 0 3 1 50.00 150.00 1.35 202.50 0",
        "TNQ",
    ]))
    rows = pm.parse(PATH)
    assert [(r["ticker"], r["market"], r["endQ"]) for r in rows] == [
        ("700", "HK", 2000.0), ("TNQ", "US", 3.0)]


def test_parse_skips_rows_with_other_number_counts_or_no_ticker(text):
    text("\n".join([
        "SGX SGD 1 2 3 4 5 6 7 8 9 10",            # 10 numbers: neither table
        "T10",
        "SGX SGD 1 2 3 4 5 6 7 8",                 # valid shape, but no ticker within 3 lines
        "Test Holdings Ltd",
        "some text",
        "more text",
        "T99",
    ]))
    assert pm.parse(PATH) == []


def test_parse_month_comes_from_the_path(text):
    text("SGX SGD 1 0 1 1 1.00 1.00 1.00 1.00\nT01\n")
    assert pm.parse("/x/moomoo_202512.pdf")[0]["month"] == "2025-12"


def test_trades_reads_priced_lines_and_the_nearby_ticker(text):
    text("\n".join([
        "Transaction Details",
        "Buy to Open   SGX SGD   1.230   1,000   1,230.00   Filled",
        "T01   2024/03/12 10:15:00",
        "",
        "",
        "",
        "Sell to Close  US USD  110.500  5  552.50",
        "TUS  2024/03/20 22:30:01",
    ]))
    assert pm.trades(PATH) == [
        {"ym": "2024-03", "ticker": "T01", "qty": 1000.0, "price": 1.23,
         "amount": 1230.0, "buy": True},
        {"ym": "2024-03", "ticker": "TUS", "qty": 5.0, "price": 110.5,
         "amount": 552.5, "buy": False},
    ]


def test_trades_ticker_is_blank_without_a_time_line(text):
    text("Buy to Close  HK HKD  3.500  2,000  7,000.00\nno timestamp here\n")
    assert pm.trades(PATH)[0]["ticker"] == ""


def test_trades_ignores_non_trade_lines(text):
    text("Opening Balance  SGX SGD 1.00 1 1.00\nBuy  SGX SGD 1.00 1 1.00\n")
    assert pm.trades(PATH) == []
