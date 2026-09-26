"""build.parse_dividends.tiger_currency — Tiger's flex currency column.

The parser script runs as `python3 build/parse_dividends.py` and imports its
siblings by bare name. Load it the same way, and do not execute `main()`: that
reads statement files and writes build/dividends.csv.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_dividends.py -q
"""
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
