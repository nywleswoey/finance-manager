"""Scheduled price refresh — GET /api/cron/refresh-prices (Vercel Cron).

This route is the one hole in the cookie gate: a cron request arrives with no session, so the
gate is told to let it through and the handler authenticates it itself. These tests pin that
the substitute credential is actually enforced — including when CRON_SECRET is unset, which
must deny rather than open, and when the local dev auth bypass is on, which must not reach
into a route that has nothing to do with sessions.

The Yahoo fetch is stubbed throughout: no network, no DB.
"""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from portfolio.config import settings

from ingestion import prices
from server import main

SECRET = "cron-secret-value"


@pytest.fixture(autouse=True)
def _cfg():
    settings.cron_secret = SECRET
    settings.dev_auth_bypass = False   # a developer's .env sets this true; pin it
    yield


@pytest.fixture
def calls(monkeypatch):
    """Count refreshes instead of performing them."""
    seen = []
    monkeypatch.setattr(prices, "main", lambda *a, **k: seen.append(1) or
                        {"ok": 36, "fail": 0, "date": "2026-08-06", "failed": [], "fx_failed": []})
    return seen


@pytest.fixture
def client():
    return TestClient(main.app)


def test_cron_secret_runs_the_refresh(client, calls):
    r = client.get("/api/cron/refresh-prices", headers={"Authorization": f"Bearer {SECRET}"})
    assert r.status_code == 200
    assert r.json()["ok"] == 36
    assert len(calls) == 1


def test_cron_clears_the_cache(client, calls):
    """Fresh prices are worthless if the process keeps serving the memoized old ones."""
    main._cache["all"] = "stale"
    client.get("/api/cron/refresh-prices", headers={"Authorization": f"Bearer {SECRET}"})
    assert main._cache == {}


def test_no_header_is_denied(client, calls):
    r = client.get("/api/cron/refresh-prices")
    assert r.status_code == 401
    assert calls == []          # denied before any outbound fetch


def test_wrong_secret_is_denied(client, calls):
    r = client.get("/api/cron/refresh-prices", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert calls == []


def test_bare_secret_without_bearer_prefix_is_denied(client, calls):
    """Vercel sends `Bearer <secret>`; accepting the naked value would widen the credential."""
    r = client.get("/api/cron/refresh-prices", headers={"Authorization": SECRET})
    assert r.status_code == 401
    assert calls == []


def test_unset_secret_fails_closed(client, calls):
    """A project that never set CRON_SECRET gets a dead route, not an open one — otherwise
    the empty string would match an empty header and anyone could drive the refresh."""
    settings.cron_secret = ""
    for headers in ({}, {"Authorization": ""}, {"Authorization": "Bearer "}):
        assert client.get("/api/cron/refresh-prices", headers=headers).status_code == 401
    assert calls == []


def test_dev_bypass_does_not_open_the_cron_route(client, calls, monkeypatch):
    """The bypass opens the *gate*; this route's credential is checked past it."""
    monkeypatch.setattr(settings, "dev_auth_bypass", True)
    assert client.get("/api/cron/refresh-prices").status_code == 401
    assert calls == []


def test_route_is_exempt_from_the_cookie_gate():
    """If it were not, the 401 above would be the gate's — and a correct cron request would
    be rejected too, for having no session cookie."""
    assert "/api/cron/refresh-prices" in main._PUBLIC_PATHS


def test_manual_refresh_still_needs_a_session(client, calls):
    """The POST twin is unchanged: gate-protected, no CRON_SECRET path into it."""
    r = client.post("/api/refresh-prices", headers={"Authorization": f"Bearer {SECRET}"})
    assert r.status_code == 401
    assert calls == []


# ---------------- the date the rows carry ----------------

def test_price_date_is_sgt_not_the_server_clock():
    """The cron fires at 23:15 UTC, which is already the next SGT day. Stamping rows with the
    UTC date would file a cloud run one day behind the identical 06:15 SGT local run, and the
    two would disagree about which date holds the newest close."""
    fired = dt.datetime(2026, 8, 5, 23, 15, tzinfo=dt.timezone.utc)
    assert fired.astimezone(prices.SGT).date() == dt.date(2026, 8, 6)
    assert fired.date() == dt.date(2026, 8, 5)          # what date.today() would have given
