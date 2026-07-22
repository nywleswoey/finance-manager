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
from build._ledgercommon import canon, is_transfer_in, is_transfer_out, norm_ticker, num


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
