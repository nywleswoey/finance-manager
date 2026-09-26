"""Shared test scaffolding: settings isolation and the three app clients.

`settings` is one process-wide object, so a test that assigns to it changes every test after
it. `_restore_settings` snapshots its fields before each test and puts them back after, so a
fixture may assign freely and nothing leaks into the next file — the ordering bug where a
dev-bypass fixture left the gate open for a later auth test cannot come back.

What restoring cannot do is undo a developer's `.env`: DEV_AUTH_BYPASS=true there is the
starting value, not a leak. A test that needs the gate enforced still asks for `auth_settings`.

In-memory SQLite sessions for the unittest-style files live in tests/sqlitetest.py, beside
tests/pgtest.py: `unittest.TestCase` methods cannot take pytest fixtures.
"""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from portfolio.config import settings

OWNER = "owner@gmail.com"       # allowlisted AND allowed to see Spending


@pytest.fixture(autouse=True)
def _restore_settings():
    saved = dict(settings.__dict__)
    yield
    settings.__dict__.clear()
    settings.__dict__.update(saved)


@pytest.fixture
def auth_settings():
    """Deterministic auth config with the gate enforced. dev_auth_bypass is pinned off: a
    developer's local .env sets DEV_AUTH_BYPASS=true, which would otherwise short-circuit
    user_from_request and silently pass tests that exist to prove the gate denies."""
    settings.session_secret = "test-secret-key"
    settings.google_client_id = "test-client.apps.googleusercontent.com"
    settings.allowed_emails = OWNER
    settings.spending_emails = OWNER
    settings.cookie_secure = False
    settings.dev_auth_bypass = False
    return settings


@contextmanager
def _no_session():
    yield None


@pytest.fixture
def no_db(monkeypatch):
    """The portfolio routes' `session_scope` yields None: for handlers whose reads are stubbed."""
    from server.routes import portfolio as portfolio_routes
    monkeypatch.setattr(portfolio_routes, "session_scope", lambda *a, **k: _no_session())


@pytest.fixture
def client():
    """The app with the auth gate bypassed. The response memo is process-wide, so it is cleared
    on both sides: a figure cached by one test's stubs must not answer the next test."""
    from server import main
    settings.dev_auth_bypass = True
    main._cache.clear()
    yield TestClient(main.app)
    main._cache.clear()


@pytest.fixture
def owner_client(auth_settings):
    """The app through the real cookie gate, signed in as OWNER."""
    from server import auth, main
    main._cache.clear()
    c = TestClient(main.app)
    c.cookies.set("session", auth.mint_session(OWNER, "Me"))
    yield c
    main._cache.clear()
