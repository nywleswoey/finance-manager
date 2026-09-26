"""build.parse_dividends.tiger_currency — Tiger's flex currency column.

The parser script runs as `python build/parse_dividends.py` and imports its
siblings by bare name. Load it the same way, and do not execute `main()`: that
reads statement files and writes build/dividends.csv.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_dividends.py -q
"""
import csv
import importlib.util
import os
import sys

_BUILD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "build")
sys.path.insert(0, _BUILD)
try:
    _spec = importlib.util.spec_from_file_location(
        "parse_dividends_under_test", os.path.join(_BUILD, "parse_dividends.py"))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
finally:
    sys.path.remove(_BUILD)

tiger_currency = _mod.tiger_currency


def test_an_explicit_currency_column_is_kept_on_an_sgx_symbol():
    """The pinned row. Market inference would label this SGD. The column says EUR,
    so the payout is EUR — which is the only Tiger shape that needs a rate other
    than the market's. Live SET rows do not look like this; their column is SGD."""
    assert tiger_currency("Stoneweg EUTrust EUR (SET.SI)", "EUR") == "EUR"


def test_a_set_row_whose_column_says_sgd_stays_sgd():
    """Live Tiger SET/CWBU cash equals quantity times the SGD gross rate, and the
    flex column is SGD. A ticker override to EUR would convert that cash again."""
    assert tiger_currency("Stoneweg EUTrust EUR (SET.SI)", "SGD") == "SGD"
    assert tiger_currency("CWBU.SI", "SGD") == "SGD"


def test_a_blank_currency_cell_falls_back_to_the_market():
    assert tiger_currency("DBS (D05.SI)", "") == "SGD"
    assert tiger_currency("LINK REIT (00823)", "  ") == "HKD"
    assert tiger_currency("AAPL", None) == "USD"


# ---------- CDP tracker: the ±7-day dedup and CDP_DIV_FIX ----------
# data/ is gitignored, so these run cdp() over a synthetic tracker sheet.

CDP_HEADER = ["Date", "Year", "Month", "Stock Name", "Dividends (native)", "Dividends (SGD)",
              "Quantity", "Dividend (rate)"]


def _cdp(tmp_path, monkeypatch, sheet, already=()):
    (tmp_path / "cdp-stocks").mkdir()
    with open(tmp_path / "cdp-stocks" / "dividends.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CDP_HEADER)
        w.writerows(sheet)
    monkeypatch.setattr(_mod, "DATA", str(tmp_path))
    monkeypatch.setattr(_mod, "DIV", [dict(x) for x in already])
    _mod.cdp()
    return [(d["ticker"], d["date"], d["gross"]) for d in _mod.DIV
            if d["source"] == "cdp (cash dividend)"]


def test_a_cdp_row_within_seven_days_of_a_broker_dividend_is_not_booked_twice(
        tmp_path, monkeypatch):
    """The sheet keeps tracking a holding after it moves to a broker; that broker's
    statement already books the payment."""
    tiger = {"date": "2024-05-10", "ticker": "D05", "source": "tiger (dividends)"}
    got = _cdp(tmp_path, monkeypatch, [
        ["17-May-24", "2024", "5", "DBS", "150", "150", "300", "0.5"],      # +7 days -> dup
        ["18-May-24", "2024", "5", "DBS", "150", "150", "300", "0.5"],      # +8 days -> kept
        ["10-May-24", "2024", "5", "OCBC", "90", "90", "300", "0.3"],       # other ticker
    ], already=[tiger])
    assert got == [("D05", "2024-05-18", 150.0), ("O39", "2024-05-10", 90.0)]


def test_cdp_div_fix_drops_and_rescales_the_named_rows(tmp_path, monkeypatch):
    got = _cdp(tmp_path, monkeypatch, [
        ["17-Aug-21", "2021", "8", "Accordia Golf Tr", "50", "50", "1000", "0.05"],
        ["28-Sep-22", "2022", "9", "Stoneweg European Trust EUR", "1260.78", "1773.37",
         "14500", "0.087"],
    ])
    assert got == [("SET", "2022-09-28", 121.73)]
    fixed = next(d for d in _mod.DIV if d["ticker"] == "SET")
    assert (fixed["units"], fixed["currency"]) == (1400.0, "EUR")


def test_a_zero_amount_row_is_declared_but_unpaid(tmp_path, monkeypatch):
    assert _cdp(tmp_path, monkeypatch, [
        ["17-May-24", "2024", "5", "DBS", "0", "0", "300", "0.5"]]) == []
