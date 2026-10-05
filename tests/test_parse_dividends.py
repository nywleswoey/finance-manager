"""build/parse_dividends.py — Tiger's flex currency column, ticker normalisation, CDP dates,
the CDP statement/tracker split and the Moomoo PDF dividend regexes.

Gates `tiger_currency`, `cdp()` (the ±7-day dedup and CDP_DIV_FIX), `norm` (bare exchange
code, then the canonical rename), `_cdp_date` (Excel serials counted from 1899-12-30, the
sheet's string formats, None when nothing parses), `cdp_statements()` (the Cash Transaction
line regex and issuer-name stripping) and `moomoo()` (the SG "@"/"AT" dividend line and the
US SHARES-anchor + signed-amount pairing).
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


# ---------- CDP tracker: a row cdp_statements() already read is never doubled ----------
# cdp_statements() isn't called by the `_cdp` fixture (it only exercises cdp()), so these
# feed a fake "cdp (cash dividend, statement)" row through `already`, exactly the shape
# cdp_statements() would have added to DIV ahead of cdp() in main().

def test_a_tracker_row_matching_a_statement_row_is_skipped_but_others_are_kept(
        tmp_path, monkeypatch):
    stmt = {"date": "2026-05-22", "ticker": "Q01", "source": "cdp (cash dividend, statement)"}
    got = _cdp(tmp_path, monkeypatch, [
        ["22-May-26", "2026", "5", "QAF", "680", "680", "17000", "0.04"],       # same payout
        ["15-May-26", "2026", "5", "Hock Lian Seng", "7.88", "7.88", "700", "0.01125"],
    ], already=[stmt])
    assert got == [("J2T", "2026-05-15", 7.88)]


def test_a_tracker_row_dated_by_ex_date_is_still_matched_to_the_statement_pay_date(
        tmp_path, monkeypatch):
    """Real data: the sheet dates Asian Pay TV's 2019 payout 20-Jun-19 while the statement's
    Cash Transaction line pays it 28/06/2019 — 8 days apart, still the same payout."""
    stmt = {"date": "2019-06-28", "ticker": "S7OU", "source": "cdp (cash dividend, statement)"}
    got = _cdp(tmp_path, monkeypatch, [
        ["20-Jun-19", "2019", "6", "Asian Pay Tv Tr", "324", "324", "108000", "0.003"],
    ], already=[stmt])
    assert got == []


def test_a_statement_row_skips_the_trackers_backfill_too(tmp_path, monkeypatch):
    """Real CDP data shows the sheet's one blended per-unit rate can cover two same-day
    REIT distribution tranches (so its rate x position backfill overstates or splits the
    payout differently from the statement). The statement reading wins outright, even over
    a backfill that would otherwise be exempt from the broker-statement dedup."""
    stmt = {"date": "2025-03-28", "ticker": "SET", "source": "cdp (cash dividend, statement)"}
    got = _cdp(tmp_path, monkeypatch, [
        ["28-Mar-25", "2025", "3", SET_NAME, "#N/A", "#N/A", "#N/A", "0.07903"],
    ], already=[stmt], ledger=[_leg("2024-06-28", "SET", 1400, SET_NAME)],
        statements=["202406", "202503"])
    assert got == []


# ---------- CDP cash dividends straight from the statement PDF ----------
# cdp_statements() is not reached by the `_cdp`/`_leg` fixtures above (those only exercise
# cdp()); `raw_text` is patched directly here, the same way tests/test_parse_moomoo.py gates
# build/parse_moomoo.py. The path only needs a real file on disk for glob() to find — its
# bytes are never read.

def _cdp_statements(tmp_path, monkeypatch, text):
    (tmp_path / "cdp-statements").mkdir()
    (tmp_path / "cdp-statements" / "202605.pdf").write_bytes(b"")
    monkeypatch.setattr(pd, "DATA", str(tmp_path))
    monkeypatch.setattr(pd, "DIV", [])
    monkeypatch.setattr(pd, "raw_text", lambda path: text)
    pd.cdp_statements()
    return [(d["ticker"], d["date"], d["gross"], d["currency"], d["units"], d["rate"])
            for d in pd.DIV]


CASH_TXN_HEADER = " Cash Transaction\n\nDate            Description                            Amount         Paid\n"
CASH_TXN_FOOTER = "\n Your Securities Account is Linked To\n"


def test_cdp_statement_issuer_strips_the_kind_suffix():
    assert pd.cdp_statement_issuer("OCBC BANK Final Cash Dividend") == "OCBC BANK"
    assert pd.cdp_statement_issuer("OCBC BANK Special Cash Dividend") == "OCBC BANK"
    assert pd.cdp_statement_issuer("SASSEUR REIT Cash Dividend") == "SASSEUR REIT"       # no qualifier
    assert pd.cdp_statement_issuer(
        "AIMS APAC REIT Interim Dividend Option") == "AIMS APAC REIT"
    assert pd.cdp_statement_issuer("CROMWELLREIT EUR Dividend Option") == "CROMWELLREIT EUR"


def test_cdp_statements_reads_final_interim_and_special_cash_dividend_lines(tmp_path, monkeypatch):
    text = CASH_TXN_HEADER + (
        "22/05/2026      QAF Final Cash Dividend - 17,000 units @ SGD 0.04"
        "                                         680.00\n"
        "22/05/2026      HYPHENS PHARMA Final Cash Dividend - 3,000 units @ SGD 0.015"
        "                               45.00\n"
        "28/05/2026      JUMBO Interim Cash Dividend - 3,000 units @ SGD 0.005"
        "                                      15.00\n"
    ) + CASH_TXN_FOOTER
    got = _cdp_statements(tmp_path, monkeypatch, text)
    assert got == [
        ("Q01", "2026-05-22", 680.0, "SGD", 17000.0, 0.04),
        ("1J5", "2026-05-22", 45.0, "SGD", 3000.0, 0.015),
        ("42R", "2026-05-28", 15.0, "SGD", 3000.0, 0.005),
    ]


def test_cdp_statements_reads_a_bare_cash_dividend_and_a_dividend_option_line(tmp_path, monkeypatch):
    """REIT distributions sometimes carry no Final/Interim/Special qualifier at all
    ("Cash Dividend"), and a scrip-election REIT reads "Dividend Option" instead."""
    text = CASH_TXN_HEADER + (
        "24/09/2026      SASSEUR REIT Cash Dividend - 6,500 units @ SGD 0.03366"
        "                                      218.79\n"
        "31/03/2026      STONEWEG EUTRUST Dividend Option - 1,400 units @ EUR 0.06837"
        "                            95.72\n"
    ) + CASH_TXN_FOOTER
    got = _cdp_statements(tmp_path, monkeypatch, text)
    assert got == [
        ("CRPU", "2026-09-24", 218.79, "SGD", 6500.0, 0.03366),
        ("SET", "2026-03-31", 95.72, "EUR", 1400.0, 0.06837),
    ]


def test_cdp_statements_ignores_capital_distribution_redemption_and_payment_made_lines(
        tmp_path, monkeypatch):
    """Capital Distribution / bond Redemption rows share the dividend lines' column shape
    but are not dividend income; "Payment Made" settlement legs have no "units @" clause."""
    text = CASH_TXN_HEADER + (
        "26/03/2026      SASSEUR REIT Capital Distribution - 6,500 units @ SGD 0.01"
        "                                 65.00\n"
        "15/03/2026      ASTREAVIB310318 Redemption - 100 units @ SGD 100.00"
        "                                     10,000.00\n"
        "22/05/2026      Payment Made - REF: DCS - A-1YX-BOUC-J09"
        "                                                      -680.00\n"
    ) + CASH_TXN_FOOTER
    assert _cdp_statements(tmp_path, monkeypatch, text) == []


def test_cdp_statements_skips_an_unmapped_issuer_name(tmp_path, monkeypatch, capsys):
    text = CASH_TXN_HEADER + (
        "01/01/2026      SOME NEW CO Final Cash Dividend - 100 units @ SGD 0.10"
        "                                      10.00\n"
    ) + CASH_TXN_FOOTER
    assert _cdp_statements(tmp_path, monkeypatch, text) == []
    assert "SOME NEW CO" in capsys.readouterr().out


def test_cdp_statements_only_reads_inside_the_cash_transaction_section(tmp_path, monkeypatch):
    """A line shaped like a dividend outside the Cash Transaction .. Your Securities Account
    bounds (e.g. in the holdings table some other section of the statement prints) is not
    picked up."""
    text = (
        "15/01/2026      QAF Final Cash Dividend - 17,000 units @ SGD 0.04"
        "                                         680.00\n"
    ) + CASH_TXN_HEADER + CASH_TXN_FOOTER
    assert _cdp_statements(tmp_path, monkeypatch, text) == []


# ---------- Moomoo (PDF) dividend lines ----------
# `raw_text` is patched the same way tests/test_parse_moomoo.py gates build/parse_moomoo.py;
# the path only needs a real file on disk for glob() to find a YYYYMM to key the pay date.

def _moomoo(tmp_path, monkeypatch, text, ym="202605"):
    (tmp_path / "moomoo").mkdir()
    (tmp_path / "moomoo" / f"moomoo_{ym}.pdf").write_bytes(b"")
    monkeypatch.setattr(pd, "DATA", str(tmp_path))
    monkeypatch.setattr(pd, "DIV", [])
    monkeypatch.setattr(pd, "raw_text", lambda path: text)
    pd.moomoo()
    return [(d["ticker"], d["date"], d["gross"], d["currency"], d["source"]) for d in pd.DIV]


def test_moomoo_sg_dividend_with_the_at_connector_uppercase(tmp_path, monkeypatch):
    """moomoo_202605.pdf's real text: "9CI CASH DIVIDEND AT SGD 0.12", the connector that
    broke the old "@"-only regex."""
    text = "\n".join([
        "   Ending Unsettled Cash    0.00                     9CI CASH DIVIDEND AT SGD 0.12",
        "                              2026/05/15 09:03:34   Corporate Action    +324.00",
    ])
    assert _moomoo(tmp_path, monkeypatch, text) == [
        ("9CI", "2026-05-15", 324.0, "SGD", "moomoo (cash dividend)")]


def test_moomoo_sg_dividend_with_the_at_connector_lower_case(tmp_path, monkeypatch):
    """moomoo_202205.pdf's real text: "9CI Cash Dividend at SGD 0.03" / "...0.12" — two
    same-day tranches, each its own row."""
    text = "\n".join([
        "  2022/05/23 09:37:08   Corporate Action   +81.00    9CI Cash Dividend at SGD 0.03",
        "  2022/05/23 10:12:49   Corporate Action   +324.00   9CI Cash Dividend at SGD 0.12",
    ])
    assert _moomoo(tmp_path, monkeypatch, text, ym="202205") == [
        ("9CI", "2022-05-15", 81.0, "SGD", "moomoo (cash dividend)"),
        ("9CI", "2022-05-15", 324.0, "SGD", "moomoo (cash dividend)"),
    ]


def test_moomoo_sg_dividend_still_reads_the_older_at_sign_connector(tmp_path, monkeypatch):
    text = "\n".join([
        "   Ending Unsettled Cash    0.00                   HMN CASH DIVIDEND @ SGD 0.00415",
        "                              2023/08/01 00:00:00   Corporate Action    +10.00",
    ])
    assert _moomoo(tmp_path, monkeypatch, text, ym="202308") == [
        ("HMN", "2023-08-15", 10.0, "SGD", "moomoo (cash dividend)")]


def test_moomoo_sg_dividend_whose_rate_wraps_onto_the_next_line(tmp_path, monkeypatch):
    """moomoo_202606.pdf's real text: three C38U tranches whose rate text ("0.0006 / 0.0027
    / 0.0365 PER") wraps past the ticker/currency line, leaving no rate on it — the amount
    is still found via the nearby "Corporate Action" line, with rate left blank."""
    text = "\n".join([
        "   Ending Unsettled Cash    0.00                                  C38U CASH DIVIDEND AT SGD",
        "                              2026/06/09 08:40:26   Corporate Action    +0.30     0.0006 / 0.0027 / 0.0365 PER",
        "                                                                                   SHARE",
    ])
    got = _moomoo(tmp_path, monkeypatch, text, ym="202606")
    assert got == [("C38U", "2026-06-15", 0.3, "SGD", "moomoo (cash dividend)")]
    assert next(d for d in pd.DIV)["rate"] == ""


def test_moomoo_us_dividend_old_format_shares_dividends_on_the_anchor_line(tmp_path, monkeypatch):
    """moomoo_202305.pdf's real text: the anchor line itself says "SHARES DIVIDENDS", the
    amount is on the next "US Dividend Paying" line, and the withholding-tax leg right
    after it (its own "AAPL ... SHARES" anchor, no DIVIDENDS, negative amount) is skipped."""
    text = "\n".join([
        "   Ending Unsettled Cash    0.00                      AAPL 1.00000000 SHARES DIVIDENDS",
        "        2023/05/19 17:30:55    US Dividend Paying    +0.24",
        "                                                      0.24 USD PER SHARE",
        "                                                      AAPL 1.00000000 SHARES",
        "        2023/05/19 17:44:35    US Dividend Paying    -0.07   WITHHOLDING TAX -0.07200001 USD",
    ])
    assert _moomoo(tmp_path, monkeypatch, text, ym="202305") == [
        ("AAPL", "2023-05-15", 0.24, "USD", "moomoo (cash dividend)")]


def test_moomoo_us_dividend_new_format_dividend_word_wraps_onto_the_amount_line(
        tmp_path, monkeypatch):
    """moomoo_202605.pdf's real text: the anchor line now says only "SHARES" (no DIVIDENDS),
    and "DIVIDENDS" instead sits on the following "Corporate Action" line carrying the
    amount — the regression this fixes alongside the SG "AT" connector."""
    text = "\n".join([
        "   Ending Unsettled Cash    0.00                                    AAPL 1.00000000 SHARES",
        "      2026/05/15 15:02:09   Corporate Action   +0.27   DIVIDENDS 0.26999998 USD PER",
        "                                                       SHARE",
        "                                                       AAPL 1.00000000 SHARES",
        "      2026/05/15 15:23:41   Corporate Action   -0.08   WITHHOLDING TAX -0.08099999 USD PER",
        "                                                       SHARE - TAX",
    ])
    assert _moomoo(tmp_path, monkeypatch, text, ym="202605") == [
        ("AAPL", "2026-05-15", 0.27, "USD", "moomoo (cash dividend)")]
    assert next(d for d in pd.DIV)["units"] == 1.0


def test_moomoo_us_shares_anchor_without_a_dividend_word_is_not_booked(tmp_path, monkeypatch):
    """A SHARES-shaped corporate action that is never tied to the word "DIVIDEND" anywhere
    in its pair of lines (e.g. a split) must not be booked as income."""
    text = "\n".join([
        "TSLA 5.00000000 SHARES",
        "      2026/01/01 00:00:00   Corporate Action   +10.00   STOCK SPLIT ADJUSTMENT",
    ])
    assert _moomoo(tmp_path, monkeypatch, text, ym="202601") == []
