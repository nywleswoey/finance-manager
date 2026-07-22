"""Spending capability gate — the rule, the middleware, and the capability list.

The Spending section is restricted to the emails in SPENDING_EMAILS. Hiding the nav item in the
SPA is cosmetic; the 403 from the auth_gate middleware is the control (SECURITY-08).

No DB and no network: middleware coverage comes from probing a path that matches the gate but
has no route, so a permitted caller falls through to 404 while a denied caller stops at 403.
"""
import pytest
from fastapi.testclient import TestClient

from portfolio.config import Settings, settings

from server import auth
from server.main import _is_spending

OWNER = "owner@gmail.com"          # allowlisted AND allowed to see Spending
GUEST = "guest@gmail.com"          # allowlisted, NOT allowed to see Spending
PROBE = "/api/spending/__probe__"  # matches the gate, no route behind it


@pytest.fixture(autouse=True)
def _cfg():
    """Deterministic auth config. Pins dev_auth_bypass explicitly — the local .env sets
    DEV_AUTH_BYPASS=true, which would otherwise short-circuit every check here."""
    settings.session_secret = "test-secret-key"
    settings.google_client_id = "test-client.apps.googleusercontent.com"
    settings.allowed_emails = f"{OWNER}, {GUEST}"
    settings.spending_emails = OWNER
    settings.cookie_secure = False
    settings.dev_auth_bypass = False
    yield


@pytest.fixture
def client():
    from server.main import app
    # raise_server_exceptions=False so a DB-less handler surfaces as a 500 instead of
    # re-raising: these tests only assert the gate's decision (!= 403 / 401 / 404), never the DB path.
    return TestClient(app, raise_server_exceptions=False)


def _session(client, email):
    client.cookies.set("session", auth.mint_session(email, "Me"))


# ---------------- the rule ----------------

def test_authorized_email_holds_the_capability():
    assert auth.can_view_spending({"sub": OWNER}) is True
    assert auth.features_for({"sub": OWNER}) == ["spending"]


def test_allowlisted_but_unauthorized_email_does_not():
    """Being allowed to sign in is not being allowed to see Spending."""
    assert auth.can_view_spending({"sub": GUEST}) is False
    assert auth.features_for({"sub": GUEST}) == []


def test_email_match_is_case_insensitive():
    settings.spending_emails = "Owner@Gmail.COM"
    assert auth.can_view_spending({"sub": OWNER}) is True


def test_no_user_denies():
    assert auth.can_view_spending(None) is False
    assert auth.can_view_spending({}) is False
    assert auth.features_for(None) == []


def test_empty_config_denies_everyone_including_the_allowlisted():
    """Fail closed (SECURITY-15). Forgetting SPENDING_EMAILS hides the feature; it never opens it."""
    settings.spending_emails = ""
    assert auth.can_view_spending({"sub": OWNER}) is False
    assert auth.can_view_spending({"sub": GUEST}) is False


def test_dev_bypass_precedes_the_fail_closed_check(monkeypatch):
    """FR-7: locally the bypass grants every capability even with SPENDING_EMAILS unset.
    auth_bypass_active is force-false on Vercel, so this cannot leak into a deployment."""
    settings.spending_emails = ""
    monkeypatch.setattr(type(settings), "auth_bypass_active", property(lambda self: True))
    assert auth.can_view_spending({"sub": "dev@localhost"}) is True
    assert auth.features_for(None) == ["spending"]


def test_capability_is_recomputed_not_read_from_the_session():
    """Revocation must take effect on the next request, without re-login (NFR-1)."""
    user = {"sub": OWNER}
    assert auth.can_view_spending(user) is True
    settings.spending_emails = ""
    assert auth.can_view_spending(user) is False


# ---------------- the path predicate ----------------

def test_is_spending_matches_exact_and_children():
    assert _is_spending("/api/spending") is True
    assert _is_spending("/api/spending/") is True
    assert _is_spending("/api/spending/summary") is True
    assert _is_spending("/api/spending/recurring/detect") is True


def test_is_spending_does_not_swallow_sibling_prefixes():
    """A bare startswith('/api/spending') would gate a future /api/spending-export too."""
    assert _is_spending("/api/spending-export") is False
    assert _is_spending("/api/spendings") is False
    assert _is_spending("/api/overview") is False


# ---------------- the middleware ----------------

def test_anonymous_gets_401_not_403(client):
    """Authentication precedes authorization, so we never reveal the feature to strangers."""
    assert client.get(PROBE).status_code == 401


def test_unauthorized_session_is_forbidden(client):
    _session(client, GUEST)
    r = client.get(PROBE)
    assert r.status_code == 403
    assert r.json() == {"detail": "forbidden"}


def test_authorized_session_passes_the_gate(client):
    """404, not 403: the gate let it through and no route serves the probe path."""
    _session(client, OWNER)
    assert client.get(PROBE).status_code == 404


def test_empty_config_forbids_the_authorized_session_too(client):
    settings.spending_emails = ""
    _session(client, OWNER)
    assert client.get(PROBE).status_code == 403


def test_non_spending_routes_are_unaffected_for_an_unauthorized_user(client):
    """Gating Spending must not gate anything else (AC-6)."""
    _session(client, GUEST)
    assert client.get("/api/overview").status_code != 403


# ---------------- the capability list on /api/auth/me ----------------

def test_me_reports_the_capability_for_the_authorized_account(client):
    _session(client, OWNER)
    body = client.get("/api/auth/me").json()
    assert body["email"] == OWNER
    assert body["features"] == ["spending"]


def test_me_reports_no_capability_for_everyone_else(client):
    _session(client, GUEST)
    body = client.get("/api/auth/me").json()
    assert body["email"] == GUEST
    assert body["features"] == []


def test_me_never_leaks_the_authorized_address(client):
    """The client renders from `features`; it must not learn who the owner is."""
    _session(client, GUEST)
    assert OWNER not in client.get("/api/auth/me").text


# ---------------- config plumbing ----------------

def test_spending_emails_defaults_to_empty():
    """The default must be deny-all, asserted on the class, not on the loaded instance."""
    assert Settings.model_fields["spending_emails"].default == ""


def test_spending_email_set_parsing():
    settings.spending_emails = " A@x.com ,, B@X.com,"
    assert settings.spending_email_set == {"a@x.com", "b@x.com"}
