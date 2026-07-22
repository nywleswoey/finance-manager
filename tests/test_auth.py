"""Auth unit tests — session mint/verify, allowlist enforcement, deny-by-default gate,
and the Google login endpoint (Google verification stubbed). No DB or network needed."""
import datetime as dt

import jwt
import pytest
from fastapi.testclient import TestClient

from portfolio.config import Settings, settings

from server import auth


@pytest.fixture(autouse=True)
def _cfg():
    """Deterministic auth config for every test.

    dev_auth_bypass is pinned like the rest: a developer's local .env sets DEV_AUTH_BYPASS=true,
    which would otherwise short-circuit user_from_request and silently pass tests that exist to
    prove the cookie/allowlist path denies. The tests that exercise the bypass turn it on
    explicitly via monkeypatch."""
    settings.session_secret = "test-secret-key"
    settings.google_client_id = "test-client.apps.googleusercontent.com"
    settings.allowed_emails = "yes@gmail.com, Owner@Gmail.com"
    settings.cookie_secure = False
    settings.dev_auth_bypass = False
    yield


# ---------------- session token ----------------

def test_session_roundtrip():
    tok = auth.mint_session("yes@gmail.com", "Me")
    claims = auth.verify_session(tok)
    assert claims["sub"] == "yes@gmail.com"
    assert claims["name"] == "Me"


def test_session_rejects_tampered_token():
    tok = auth.mint_session("yes@gmail.com", "Me")
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_session(tok + "x")


def test_session_rejects_wrong_secret():
    tok = auth.mint_session("yes@gmail.com", "Me")
    settings.session_secret = "different-secret"
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_session(tok)


def test_session_rejects_expired():
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    tok = jwt.encode({"sub": "yes@gmail.com", "exp": past}, settings.session_secret, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.verify_session(tok)


# ---------------- allowlist / request resolution ----------------

class _Req:
    def __init__(self, cookie=None):
        self.cookies = {"session": cookie} if cookie else {}


def test_user_from_request_allowlisted():
    tok = auth.mint_session("yes@gmail.com", "Me")
    assert auth.user_from_request(_Req(tok))["sub"] == "yes@gmail.com"


def test_user_from_request_case_insensitive_allowlist():
    tok = auth.mint_session("owner@gmail.com", "O")     # allowlist has "Owner@Gmail.com"
    assert auth.user_from_request(_Req(tok)) is not None


def test_user_from_request_revoked_when_removed_from_allowlist():
    tok = auth.mint_session("yes@gmail.com", "Me")
    settings.allowed_emails = "someone-else@gmail.com"   # email no longer allowed
    assert auth.user_from_request(_Req(tok)) is None


def test_user_from_request_no_cookie():
    assert auth.user_from_request(_Req()) is None


def test_user_from_request_garbage_cookie():
    assert auth.user_from_request(_Req("not-a-jwt")) is None


# ---------------- gate + login endpoint (HTTP) ----------------

@pytest.fixture
def client():
    from server.main import app
    # raise_server_exceptions=False so a DB-less handler surfaces as a 500 instead of
    # re-raising: these tests only assert the gate's decision (!= 401), never the DB path.
    return TestClient(app, raise_server_exceptions=False)


def test_health_is_public(client):
    assert client.get("/api/health").status_code == 200


def test_protected_route_denied_without_session(client):
    # gate rejects before the handler -> no DB hit
    assert client.get("/api/overview").status_code == 401


def test_protected_route_passes_gate_with_session(client):
    tok = auth.mint_session("yes@gmail.com", "Me")
    client.cookies.set("session", tok)
    r = client.get("/api/overview")
    assert r.status_code != 401          # gate let it through (handler may 500 w/o DB)


def test_login_sets_cookie_for_allowlisted(client, monkeypatch):
    monkeypatch.setattr(auth, "verify_google",
                        lambda cred: {"email": "yes@gmail.com", "name": "Me",
                                      "email_verified": True, "iss": "accounts.google.com"})
    r = client.post("/api/auth/google", json={"credential": "x"})
    assert r.status_code == 200
    assert r.json()["email"] == "yes@gmail.com"
    assert "session" in r.cookies


def test_login_rejects_non_allowlisted(client, monkeypatch):
    monkeypatch.setattr(auth, "verify_google",
                        lambda cred: {"email": "stranger@gmail.com", "email_verified": True,
                                      "iss": "accounts.google.com"})
    r = client.post("/api/auth/google", json={"credential": "x"})
    assert r.status_code == 403
    assert "session" not in r.cookies


def test_login_rejects_invalid_google_token(client, monkeypatch):
    def _boom(cred):
        raise ValueError("bad token")
    monkeypatch.setattr(auth, "verify_google", _boom)
    r = client.post("/api/auth/google", json={"credential": "x"})
    assert r.status_code == 401


def test_login_validates_payload(client):
    assert client.post("/api/auth/google", json={}).status_code == 422   # missing credential


def test_logout_clears_cookie(client):
    tok = auth.mint_session("yes@gmail.com", "Me")
    client.cookies.set("session", tok)
    r = client.post("/api/auth/logout")
    assert r.status_code == 200


# ---------------- local-dev auth bypass (DEV_AUTH_BYPASS) ----------------

def test_bypass_off_by_default():
    """Off by default is a property of the class, not of the instance the fixture just pinned.
    Asserting settings.dev_auth_bypass here would only prove _cfg ran."""
    assert Settings.model_fields["dev_auth_bypass"].default is False


def test_no_bypass_denies_without_cookie(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    assert settings.auth_bypass_active is False
    assert auth.user_from_request(_Req()) is None      # no cookie, no bypass -> denied


def test_bypass_grants_dev_user_without_cookie(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(settings, "dev_auth_bypass", True)
    assert settings.auth_bypass_active is True
    user = auth.user_from_request(_Req())              # no cookie at all
    assert user["sub"] == "dev@localhost"


def test_bypass_force_disabled_on_vercel(monkeypatch):
    monkeypatch.setattr(settings, "dev_auth_bypass", True)   # flag ON...
    monkeypatch.setenv("VERCEL", "1")                        # ...but deployed on Vercel
    assert settings.auth_bypass_active is False              # guard wins
    assert auth.user_from_request(_Req()) is None            # still fail-closed


def test_bypass_opens_gate(client, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(settings, "dev_auth_bypass", True)
    r = client.get("/api/overview")                    # no session cookie set
    assert r.status_code != 401                        # gate let it through (handler may 500 w/o DB)
