"""build/fetch_cpf_srs_dividends.py — the pure date/quantity helpers of the backfill.

Gates `epoch_date` (SGX millisecond epochs, falsy -> None), `pdate` (the formats the
CPF/SRS files and tracker use, including bare "YYYY-MM"), `nearest` (closest date
within a tolerance; ties keep the first) and `qty_at` (holdings replay up to and
including a date). Importing the module has no side effects; `main()` hits the
network and writes data/cpf-srs-dividends.csv, so it is never run.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_fetch_cpf_srs_dividends.py -q
"""
import datetime as dt

from tests.buildscript import load_build_script

fc = load_build_script("fetch_cpf_srs_dividends")

D = dt.date


def test_epoch_date_reads_milliseconds_and_treats_falsy_as_none():
    # noon UTC so the local-time conversion lands on the same date in any timezone
    noon = int(dt.datetime(2024, 3, 12, 12, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert fc.epoch_date(noon) == D(2024, 3, 12)
    assert fc.epoch_date(0) is None
    assert fc.epoch_date(None) is None


def test_pdate_formats():
    for s in ("2024-03-12", "12-Mar-24", "12 Mar 2024", "12/03/2024"):
        assert fc.pdate(s) == D(2024, 3, 12)
    assert fc.pdate("2024-03") == D(2024, 3, 1)
    assert fc.pdate("March 2024") is None
    assert fc.pdate(None) is None


def test_nearest_picks_the_closest_within_the_tolerance():
    pool = [D(2024, 1, 1), D(2024, 1, 10), D(2024, 1, 20)]
    assert fc.nearest(D(2024, 1, 12), pool, days=5) == D(2024, 1, 10)
    assert fc.nearest(D(2024, 1, 15), pool, days=5) == D(2024, 1, 10)   # tie: first wins
    assert fc.nearest(D(2024, 1, 15), pool, days=4) is None             # 5 days away is outside 4
    assert fc.nearest(D(2024, 1, 15), [], days=30) is None


def test_nearest_accepts_a_dict_of_dates():
    # main() passes the Yahoo {date: amount} dict straight in
    assert fc.nearest(D(2024, 1, 2), {D(2024, 1, 1): 0.1, D(2024, 2, 1): 0.2}, days=3) == D(2024, 1, 1)


def test_qty_at_sums_events_up_to_and_including_the_date():
    events = [(D(2024, 1, 1), 100.0), (D(2024, 2, 1), 50.0), (D(2024, 3, 1), -30.0),
              (None, 999.0)]                     # an unparsed date never counts
    assert fc.qty_at(events, D(2023, 12, 31)) == 0
    assert fc.qty_at(events, D(2024, 2, 1)) == 150.0
    assert fc.qty_at(events, D(2024, 12, 31)) == 120.0
    assert fc.qty_at([], D(2024, 1, 1)) == 0
