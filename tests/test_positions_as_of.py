"""/api/positions says what its prices are as of — the response half of issue #56.

The date itself is `portfolio.db.valuation_as_of`, tested against real Postgres SQL in
tests/test_db_pg.py. What is left, and what these pin, is the wiring: that the endpoint carries
it, that a list-shaped response became an envelope so it can, and that "no priced data" reports
no date rather than today. The database and the price fold are both stubbed — no DB, no network.

Why it matters that this is a separate assertion from the number: `/api/positions` and
`/api/return` value the same book off two different price sources (ADR 0001, deliberate), and
were 29,451 SGD apart when the issue was written. The gap closes by ingest; what the endpoints
owe the reader is the moment each of them is speaking about.
"""
import datetime as dt
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from portfolio.config import settings

from server import main

D = dt.date

ROW = {"ticker": "D05", "bucket": "cash", "units": 3080.0, "price": 73.94, "mv_sgd": 227735.2,
       "pl_sgd": 194503.2, "invested_native": 73289.2, "income_native": 40057.2}


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    """One open position, no database. The cache is process-wide, so clear it either side."""
    main._cache.clear()
    settings.dev_auth_bypass = True
    monkeypatch.setattr(main, "perf_all", lambda: [dict(ROW)])
    monkeypatch.setattr(main, "session_scope", lambda *a, **k: _no_session())
    yield
    main._cache.clear()


@contextmanager
def _no_session():
    yield None


@pytest.fixture
def client():
    return TestClient(main.app)


def as_of(monkeypatch, value):
    monkeypatch.setattr(main, "valuation_as_of", lambda s: value)


def test_positions_reports_the_valuation_date(client, monkeypatch):
    as_of(monkeypatch, D(2026, 7, 25))

    body = client.get("/api/positions").json()

    assert body["as_of"] == "2026-07-25"
    assert [r["ticker"] for r in body["positions"]] == ["D05"]


def test_the_date_is_not_todays(client, monkeypatch):
    """The failure the issue is about: the endpoint answering now while its prices are weeks
    old. A date that tracked the clock would be worse than none."""
    as_of(monkeypatch, D(2026, 7, 25))

    assert client.get("/api/positions").json()["as_of"] != str(dt.date.today())


def test_an_unpriced_database_reports_no_date(client, monkeypatch):
    as_of(monkeypatch, None)

    assert client.get("/api/positions").json()["as_of"] is None


def test_closed_positions_share_the_same_envelope(client, monkeypatch):
    """?closed=true is the same valuation, one row wider — not a second response shape."""
    as_of(monkeypatch, D(2026, 7, 25))

    body = client.get("/api/positions?closed=true").json()

    assert body["as_of"] == "2026-07-25"
    assert body["positions"][0]["status"] == "open"
