"""build._ledgercommon — the shared statement-parse primitives.

These `num` / `norm_ticker` / `canon` helpers used to be copy-pasted (and quietly
divergent) across build_ledger.py, parse_dividends.py, and ingestion/load_cdp_cost.py.
Now there is one home, so the contract each caller relied on is pinned here:
  - num reads `(1.23)` as -1.23 and maps blanks/`-`/`--` to 0.0 (the 0.0-sentinel
    flavour; ingestion/load.py keeps a separate None-sentinel `num` on purpose).
  - norm_ticker is the bare-code normaliser WITHOUT canon; the dividend parser's old
    `norm` is exactly `canon(norm_ticker(...))`.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_ledgercommon.py -q
"""
import os

from build._ledgercommon import (
    MARKET_CCY, TIGER_FEE_COLS, canon, is_transfer_in, is_transfer_out, market_of,
    name_to_ticker, norm_ticker, num,
)


def test_num_strips_separators_and_symbols():
    assert num("1,234.50") == 1234.5
    assert num("$1,000") == 1000.0
    assert num(" 42 ") == 42.0


def test_num_reads_parenthesised_as_negative():
    # build_ledger + load_cdp_cost relied on this; the old dividend-parser copy did NOT
    # handle it (it returned 0.0), so consolidating had to keep the paren behaviour.
    assert num("(5.00)") == -5.0
    assert num("(1,234.50)") == -1234.5


def test_num_blank_sentinels_are_zero():
    for blank in ("", "-", "--", None, "   "):
        assert num(blank) == 0.0


def test_num_garbage_is_zero_not_raise():
    assert num("n/a") == 0.0


def test_norm_ticker_extracts_trailing_paren_code():
    assert norm_ticker("Link Reit (00823)", "HK") == "00823"


def test_norm_ticker_strips_exchange_suffix_and_uppercases():
    assert norm_ticker("d05.SI", "SG") == "D05"
    assert norm_ticker("aapl.US", "US") == "AAPL"


def test_norm_ticker_zero_pads_hk_numeric_only():
    assert norm_ticker("5", "HK") == "00005"
    assert norm_ticker("5", "US") == "5"          # non-HK left as-is


def test_norm_ticker_does_not_apply_canon():
    # the whole reason norm_ticker is canon-free: callers compose canon when they want it.
    assert norm_ticker("CWBU", "SG") == "CWBU"
    assert canon(norm_ticker("CWBU", "SG")) == "SET"


def test_canon_renames_known_counters_only():
    assert canon("CWBU") == "SET"     # Cromwell -> Stoneweg
    assert canon("QAF") == "Q01"
    assert canon("D05") == "D05"      # unknown -> unchanged


def test_transfer_predicates_accept_both_spellings():
    assert is_transfer_out("transfer_out") and is_transfer_out("transfer out")
    assert is_transfer_in("transfer_in") and is_transfer_in("transfer in")
    assert not is_transfer_out("buy")


def test_market_of_sgx_alnum_without_si_is_sg_not_us():
    """A Tiger dividend symbol `DBS (D05)` has no `.SI`. The old dividend
    parser sent every non-digit code to US, so that dividend was booked USD."""
    assert market_of("D05") == "SG"
    assert market_of("DBS (D05)") == "SG"
    assert market_of("C38U") == "SG"
    assert market_of("9CI") == "SG"
    assert market_of("D05.SI") == "SG"
    assert market_of("DBS (D05.SI)") == "SG"


def test_market_of_letters_are_us_and_digits_are_hk():
    """The Tiger-transfer and viewer spellings. A letters-only SGX code is
    indistinguishable from a US ticker; seed keeps the ledger's market when it
    has one and only then falls through to this."""
    assert market_of("AAPL") == "US"
    assert market_of("BRK.B") == "US"
    assert market_of("SpaceX (SPCX)") == "US"
    assert market_of("SET") == "US"
    assert market_of("00823") == "HK"
    assert market_of("Link Reit (00823)") == "HK"
    assert market_of("5") == "HK"


def test_market_shape_and_currency_and_fees_have_one_owner():
    root = os.path.dirname(os.path.dirname(__file__))
    for rel in ("build/parse_dividends.py", "build/build_ledger.py",
                "build/build_viewer.py", "scripts/seed.py"):
        text = open(os.path.join(root, rel)).read()
        assert "market_of(" in text, rel
        assert "def market_of" not in text, rel
    for rel in ("build/parse_dividends.py", "build/build_ledger.py",
                "scripts/seed.py", "ingestion/parse_options.py"):
        text = open(os.path.join(root, rel)).read()
        assert "MARKET_CCY" in text, rel
    for rel in ("build/build_ledger.py", "ingestion/parse_options.py"):
        text = open(os.path.join(root, rel)).read()
        assert "TIGER_FEE_COLS" in text, rel
        assert "TIGER_FEE_COLS = " not in text, rel
        assert "_FEE_COLS = " not in text, rel
    assert MARKET_CCY == {"SG": "SGD", "US": "USD", "HK": "HKD", "MY": "MYR"}
    assert "GST" in TIGER_FEE_COLS and "Accrued Interest in Trade" not in TIGER_FEE_COLS


def test_stoneweg_display_names_resolve_to_one_ticker():
    """The CDP statement map sent Stoneweg to CWBU; the dividend map sent it to
    SET. symbols.csv's canonical is SET, and both names resolve there."""
    assert name_to_ticker("STONEWEG EUTRUST") == "SET"
    assert name_to_ticker("Stoneweg European Trust EUR") == "SET"
    assert name_to_ticker("CROMWELL REIT EU") == "SET"
    assert name_to_ticker("QAF") == "Q01"
    assert name_to_ticker("DBS") == "D05"
    assert name_to_ticker("hock lian seng") == "J2T"
    assert name_to_ticker("(label alias)") is None
    assert name_to_ticker("not a holding") is None


def test_cdp_statement_names_use_symbols_csv():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build"))
    import parse_cdp
    assert not hasattr(parse_cdp, "NAME2CODE")
    assert parse_cdp.code_of("STONEWEG EUTRUST") == "SET"
    assert parse_cdp.code_of("QAF") == "Q01"
    assert parse_cdp.code_of("NOT A REAL NAME") != "SET"
