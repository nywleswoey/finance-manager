"""build.parse_cash.parse_hsbc — the hand-made HSBC CSV is checked on read.

The parser script runs as `python build/parse_cash.py` and imports its siblings by
bare name. Load it the same way, and do not execute `main()`: that reads statement
files and writes build/cash_ledger_raw.csv.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_cash.py -q
"""
import importlib.util
import os
import sys

import pytest

_BUILD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "build")
sys.path.insert(0, _BUILD)
try:
    _spec = importlib.util.spec_from_file_location(
        "parse_cash_under_test", os.path.join(_BUILD, "parse_cash.py"))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
finally:
    sys.path.remove(_BUILD)

HEADER = "tran_date,post_date,description,amount_sgd,cr_flag,source_file\n"


def _parse(tmp_path, monkeypatch, amount, cr=""):
    path = tmp_path / "hsbc_extracted.csv"
    path.write_text(HEADER + f'2025-03-01,2025-03-02,GRAB,"{amount}",{cr},data/h.pdf\n')
    monkeypatch.setattr(_mod, "HSBC_CSV", str(path))
    return _mod.parse_hsbc()


@pytest.mark.parametrize("amount,cr,signed", [
    ("12.50", "", "-12.50"), ("1,234.50", "", "-1234.50"), ("7", "CR", "7.00")])
def test_a_well_formed_amount_is_signed_by_the_cr_flag(tmp_path, monkeypatch, amount, cr,
                                                      signed):
    [r] = _parse(tmp_path, monkeypatch, amount, cr)
    assert r["amount_sgd"] == signed


@pytest.mark.parametrize("amount", ["1.234,50", "S$12.50", "12.50 CR", "12,34.50", "1,2"])
def test_a_malformed_amount_stops_the_parse(tmp_path, monkeypatch, amount):
    with pytest.raises(SystemExit, match="malformed amount_sgd"):
        _parse(tmp_path, monkeypatch, amount)
