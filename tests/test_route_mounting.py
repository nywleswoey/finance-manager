"""The three product routers are reachable on the one app (`server.main:app`).

Since the routes moved out of main.py, each product reaches the app only through an
`app.include_router(...)` line. Drop one and every path under it answers 404 in production —
swallowed by the StaticFiles mount, so not even a 500 to notice. These hit one path per
product through the real app and assert the handler ran, so a missing registration fails here.

No DB and no network: each product's domain call is stubbed with a sentinel.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_route_mounting.py -q
"""
import pytest
from fastapi.testclient import TestClient

from portfolio import networth as nw
from portfolio import spending as sp
from portfolio.config import settings

from server import auth
from server.main import app
from server.routes import portfolio as portfolio_routes

OWNER = "owner@gmail.com"      # allowlisted AND allowed to see Spending


@pytest.fixture(autouse=True)
def _cfg():
    """Deterministic auth config — the local .env's DEV_AUTH_BYPASS would otherwise
    short-circuit the gate and hide a real 401."""
    settings.session_secret = "test-secret-key"
    settings.allowed_emails = OWNER
    settings.spending_emails = OWNER
    settings.cookie_secure = False
    settings.dev_auth_bypass = False
    yield


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("session", auth.mint_session(OWNER, "Me"))
    return c


def test_portfolio_router_is_mounted(client, monkeypatch):
    monkeypatch.setattr(portfolio_routes, "perf", lambda: [])
    monkeypatch.setattr(portfolio_routes, "perf_all", lambda: [])
    monkeypatch.setattr(portfolio_routes, "alloc_by_account", lambda: [])
    r = client.get("/api/overview")
    assert r.status_code == 200
    assert r.json()["positions"] == 0


def test_networth_router_is_mounted(client, monkeypatch):
    monkeypatch.setattr(nw, "latest", lambda: {"id": 7})
    r = client.get("/api/networth/latest")
    assert r.status_code == 200
    assert r.json() == {"id": 7}


def test_spending_router_is_mounted(client, monkeypatch):
    monkeypatch.setattr(sp, "summary", lambda frm, to: {"total": 42})
    r = client.get("/api/spending/summary")
    assert r.status_code == 200
    assert r.json() == {"total": 42}
