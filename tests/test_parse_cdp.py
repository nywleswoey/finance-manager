"""build/parse_cdp.py — CDP holdings table -> {security name: balance} for one month.

Gates `parse(path)`: rows count only inside a "Securities Holdings" block (which runs
through foreign-currency sub-tables and ends at an end-of-section marker), the Balance
column is taken for both the Free/Available and Free/Blocked layouts (NIL allowed),
and the month comes from the path's 6-digit YYYYMM. Also `code_of`'s fallback when
symbols.csv has no mapping (name_to_ticker is patched). `raw_text` is patched with
fabricated text; `main()` is not run.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_cdp.py -q
"""
import pytest

from tests.buildscript import load_build_script

pcdp = load_build_script("parse_cdp")

PATH = "/nowhere/cdp_202404.pdf"


@pytest.fixture
def text(monkeypatch):
    def feed(s):
        monkeypatch.setattr(pcdp, "raw_text", lambda path: s)
    return feed


def test_parse_reads_balance_column_inside_the_holdings_block(text):
    text("\n".join([
        "TEST OUTSIDE LTD      100      NIL      100      1.000      100.00",   # before block
        "Securities Holdings",
        "Security              Free     Blocked  Balance  Price      Market Value",
        "TEST ALPHA LTD        1,000    NIL      1,000    1.230      1,230.00",
        "TEST BETA REIT        500      200      700      0.800      560.00",
        "TOTAL: SGD                                                  1,790.00",
        "TEST EURO TRUST EUR   300      NIL      300      0.400      120.00",
        "- END -",
        "TEST AFTER LTD        9        NIL      9        1.000      9.00",
    ]))
    assert pcdp.parse(PATH) == ("2024-04", {
        "TEST ALPHA LTD": 1000.0,
        "TEST BETA REIT": 700.0,
        "TEST EURO TRUST EUR": 300.0,     # foreign sub-table after TOTAL: SGD still counts
    })


@pytest.mark.parametrize("marker", ["Summary of Payments", "Your Securities Account",
                                    "  Bonds", "Portfolio Summary"])
def test_each_end_marker_closes_the_block(text, marker):
    text("\n".join([
        "Securities Holdings as at 30 Apr 2024",
        "TEST ALPHA LTD   10   10   10   1.000   10.00",
        marker,
        "TEST BETA LTD    20   20   20   1.000   20.00",
    ]))
    assert pcdp.parse(PATH)[1] == {"TEST ALPHA LTD": 10.0}


def test_a_later_holdings_header_reopens_the_block(text):
    text("\n".join([
        "Securities Holdings",
        "TEST ALPHA LTD   10   NIL   10   1.000   10.00",
        "Portfolio Summary",
        "Securities Holdings (continued)",
        "TEST BETA LTD    20   NIL   20   1.000   20.00",
    ]))
    assert pcdp.parse(PATH)[1] == {"TEST ALPHA LTD": 10.0, "TEST BETA LTD": 20.0}


def test_rows_without_price_and_value_are_not_holdings(text):
    text("Securities Holdings\nTEST ALPHA LTD   10   NIL   10\n")
    assert pcdp.parse(PATH) == ("2024-04", {})


def test_code_of_falls_back_to_a_squashed_name(monkeypatch):
    monkeypatch.setattr(pcdp, "name_to_ticker", lambda name: None)
    assert pcdp.code_of("Test Alpha-Beta Ltd") == "TESTALPH"
    assert pcdp.code_of("---") == "?"
    monkeypatch.setattr(pcdp, "name_to_ticker", lambda name: "T01")
    assert pcdp.code_of("Test Alpha-Beta Ltd") == "T01"
