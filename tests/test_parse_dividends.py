"""build/parse_dividends.py — Tiger's flex currency column, ticker normalisation and CDP dates.

Gates `tiger_currency`, `cdp()` (the ±7-day dedup and CDP_DIV_FIX), `norm` (bare exchange
code, then the canonical rename) and `_cdp_date` (Excel serials counted from 1899-12-30, the
sheet's string formats, None when nothing parses).
The script is loaded the way it runs (tests/buildscript.py), and `main()` is not executed: that
reads statement files and writes build/dividends.csv.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_dividends.py -q
"""
import csv

import pytest

from tests.buildscript import load_build_script

pd = load_build_script("parse_dividends")
tiger_currency = pd.tiger_currency


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


def test_norm_pulls_the_code_drops_suffixes_and_applies_canon():
    assert pd.norm("Test Reit (00823)", "HK") == "00823"
    assert pd.norm("700", "HK") == "00700"            # HK numerics zero-padded to 5
    assert pd.norm("d05.si", "SG") == "D05"
    assert pd.norm("CWBU.SI", "SG") == "SET"          # ALIAS rename
    assert pd.norm("", "SG") == ""


def test_cdp_date_excel_serial_counts_from_1899_12_30():
    assert pd._cdp_date("123") is None                # 1-3 digits is not a serial
    assert pd._cdp_date("45000") == "2023-03-15"
    assert pd._cdp_date(" 44197 ") == "2021-01-01"


@pytest.mark.parametrize("s", ["2023-03-15", "15-Mar-23", "15 Mar 2023", "15-Mar-2023",
                               "15/03/2023"])
def test_cdp_date_string_formats(s):
    assert pd._cdp_date(s) == "2023-03-15"


@pytest.mark.parametrize("s", ["", None, "   ", "Mar 15 2023", "31/02/2023", "n/a"])
def test_cdp_date_is_none_when_nothing_parses(s):
    assert pd._cdp_date(s) is None


# ---------- CDP tracker: the ±7-day dedup and CDP_DIV_FIX ----------
# data/ is gitignored, so these run cdp() over a synthetic tracker sheet.

CDP_HEADER = ["Date", "Year", "Month", "Stock Name", "Dividends (native)", "Dividends (SGD)",
              "Quantity", "Dividend (rate)"]


LEDGER_HEADER = ["date", "account", "market", "ticker", "asset_type", "action",
                  "qty_signed", "price", "amount", "currency", "fees", "source", "raw"]


def _cdp(tmp_path, monkeypatch, sheet, already=(), ledger=None, statements=()):
    (tmp_path / "cdp-stocks").mkdir()
    (tmp_path / "cdp-statements").mkdir()
    for ym in statements:
        (tmp_path / "cdp-statements" / f"{ym}.pdf").write_bytes(b"")
    with open(tmp_path / "cdp-stocks" / "dividends.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CDP_HEADER)
        w.writerows(sheet)
    monkeypatch.setattr(pd, "DATA", str(tmp_path))
    monkeypatch.setattr(pd, "DIV", [dict(x) for x in already])
    # ledger.csv is a real build artifact (build/ledger.csv) that would otherwise leak
    # into these tests from a developer's own `make flat` run; point it at an explicit,
    # by-default absent, tmp_path file so the backfill only fires when a test asks for it.
    ledger_path = tmp_path / "ledger.csv"
    if ledger is not None:
        with open(ledger_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(LEDGER_HEADER)
            w.writerows(ledger)
    monkeypatch.setattr(pd, "LEDGER_CSV", str(ledger_path))
    pd.cdp()
    return [(d["ticker"], d["date"], d["gross"]) for d in pd.DIV
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
    fixed = next(d for d in pd.DIV if d["ticker"] == "SET")
    assert (fixed["units"], fixed["currency"]) == (1400.0, "EUR")


def test_a_zero_amount_row_is_declared_but_unpaid(tmp_path, monkeypatch):
    assert _cdp(tmp_path, monkeypatch, [
        ["17-May-24", "2024", "5", "DBS", "0", "0", "300", "0.5"]]) == []


# ---------- CDP tracker: backfill from the statement-derived custody position ----------
# From late 2023 the sheet stopped having its amount/quantity columns filled by hand (left
# "#N/A" or "0" while the per-unit rate kept being recorded) — the bug this reproduces and
# fixes. The rate x the CDP position in build/ledger.csv (via LEDGER_CSV) recovers the gross,
# but only when a statement (data/cdp-statements/YYYYMM.pdf) backs that position.

def _leg(date, ticker, qty, name, action="open"):
    return [date, "CDP", "SG", ticker, "stock", action, str(qty), "", "", "", "", "x", name]


def test_an_unfilled_amount_is_backfilled_from_the_cdp_position(tmp_path, monkeypatch):
    got = _cdp(tmp_path, monkeypatch, [
        ["17-May-24", "2024", "5", "DBS", "#N/A", "#N/A", "#N/A", "0.5"],
    ], ledger=[_leg("2024-04-28", "D05", 300, "DBS")], statements=["202404"])
    assert got == [("D05", "2024-05-17", 150.0)]
    assert next(d for d in pd.DIV if d["ticker"] == "D05")["currency"] == "SGD"


def test_backfill_sums_every_ledger_leg_up_to_the_pay_date(tmp_path, monkeypatch):
    """Two statement legs (an opening balance, then a later buy) must both count toward
    the position on the pay date; a leg dated after the pay date must not."""
    ledger = [
        _leg("2024-03-28", "D05", 200, "DBS"),
        _leg("2024-04-28", "D05", 100, "DBS", "buy"),
        _leg("2024-05-28", "D05", 500, "DBS", "buy"),
    ]
    got = _cdp(tmp_path, monkeypatch, [
        ["17-May-24", "2024", "5", "DBS", "0", "0", "0", "0.5"],
    ], ledger=ledger, statements=["202403", "202404", "202405"])
    assert got == [("D05", "2024-05-17", 150.0)]        # (200 + 100) x 0.5, not + the May 500


SET_NAME = "Stoneweg European Trust EUR"


def test_backfill_keeps_the_native_fx_currency(tmp_path, monkeypatch):
    """SET is EUR-denominated (CDP_FCCY); a backfilled gross is still the native amount,
    not converted to SGD."""
    got = _cdp(tmp_path, monkeypatch, [
        ["28-Mar-25", "2025", "3", SET_NAME, "#N/A", "#N/A", "#N/A", "0.07903"],
    ], ledger=[_leg("2024-06-28", "SET", 1400, SET_NAME)], statements=["202406", "202503"])
    assert got == [("SET", "2025-03-28", 110.64)]       # 1400 x 0.07903, rounded
    assert next(d for d in pd.DIV if d["ticker"] == "SET")["currency"] == "EUR"


def test_backfill_does_not_fire_without_a_held_position(tmp_path, monkeypatch):
    """No CDP leg at all (position 0) -> still declared-but-unfilled, same as before."""
    assert _cdp(tmp_path, monkeypatch, [
        ["17-May-24", "2024", "5", "DBS", "#N/A", "#N/A", "#N/A", "0.5"],
    ], ledger=[], statements=["202404"]) == []


def test_a_backfilled_row_is_kept_beside_another_brokers_payout(tmp_path, monkeypatch):
    """A backfilled gross is rate x the CDP-only position, so a same-ticker payout at
    another broker (here Tiger, for its own shares) is not a duplicate of it."""
    tiger = {"date": "2025-03-28", "ticker": "SET", "source": "tiger (dividends)"}
    got = _cdp(tmp_path, monkeypatch, [
        ["28-Mar-25", "2025", "3", SET_NAME, "#N/A", "#N/A", "#N/A", "0.07903"],
    ], already=[tiger], ledger=[_leg("2024-06-28", "SET", 1400, SET_NAME)],
        statements=["202406", "202503"])
    assert got == [("SET", "2025-03-28", 110.64)]


def test_a_pay_date_inside_a_statement_gap_is_not_backfilled(tmp_path, monkeypatch):
    """No statement 2021-04..2024-05: the last leg before 2024-03-28 is the stale 2021-03
    balance (7000), not what CDP held then. Such a row keeps the pre-backfill behaviour:
    dropped as unfilled, never booked as 7000 x rate."""
    ledger = [_leg("2021-03-28", "SET", 7000, SET_NAME),
              _leg("2024-06-28", "SET", -5600, SET_NAME, "sell/transfer_out")]
    got = _cdp(tmp_path, monkeypatch, [
        ["28-Mar-24", "2024", "3", SET_NAME, "#N/A", "#N/A", "#N/A", "0.07903"],
        ["10-Jun-24", "2024", "6", SET_NAME, "#N/A", "#N/A", "#N/A", "0.07"],
    ], ledger=ledger, statements=["202103", "202406"])
    assert got == []


def test_a_filled_sgd_amount_with_no_native_amount_is_still_backfilled(tmp_path, monkeypatch):
    """The sheet sometimes fills only the SGD column (for every unit it tracks, incl. other
    brokers); the native gross still comes from rate x the CDP position."""
    tiger = {"date": "2026-03-31", "ticker": "SET", "source": "tiger (dividends)"}
    got = _cdp(tmp_path, monkeypatch, [
        ["31-Mar-26", "2026", "3", SET_NAME, "0", "1479.29", "0", "0.06837"],
    ], already=[tiger], ledger=[_leg("2024-06-28", "SET", 1400, SET_NAME)],
        statements=["202406", "202603"])
    assert got == [("SET", "2026-03-31", 95.72)]        # 1400 x 0.06837
    assert next(d for d in pd.DIV if d["source"] == "cdp (cash dividend)")["currency"] == "EUR"
