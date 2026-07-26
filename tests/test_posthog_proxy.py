"""Same-origin PostHog proxy tests — /ingest/{path} in server/main.py.

The proxy exists so posthog-js can post analytics + error events first-party and stay inside
the strict CSP (`connect-src 'self'`), so these pin both halves: the CSP carries no PostHog
host, and the route forwards to the right upstream without re-emitting the response headers a
third party must not control on our origin. Upstream is stubbed — no network, no DB.
"""
import requests
from fastapi.testclient import TestClient

from server import main


class _Resp:
    def __init__(self, status=200, content=b"ok", headers=None):
        self.status_code, self.content = status, content
        self.headers = headers or {"Content-Type": "application/json"}


def _stub(monkeypatch, resp=None, boom=None):
    """Capture the outbound request the proxy makes instead of hitting PostHog."""
    seen = {}

    def fake_request(method, url, **kw):
        seen.update(method=method, url=url, **kw)
        if boom:
            raise boom
        return resp or _Resp()

    monkeypatch.setattr(main._ph_session, "request", fake_request)
    return seen


def test_csp_has_no_posthog_host():
    """The payoff of proxying: the CSP is left untouched — 'self' covers /ingest."""
    assert "posthog" not in main._CSP
    assert "connect-src 'self' https://accounts.google.com" in main._CSP


def test_ingestion_path_goes_to_posthog_host(monkeypatch):
    seen = _stub(monkeypatch)
    with TestClient(main.app) as c:
        r = c.post("/ingest/e/?ver=1.407.2", content=b"payload",
                   headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert seen["url"] == f"{main._PH_INGEST}/e/"
    assert seen["params"] == "ver=1.407.2"
    assert seen["data"] == b"payload"
    assert seen["headers"]["Content-Type"] == "application/json"
    # never chase a PostHog-chosen redirect target from our own server
    assert seen["allow_redirects"] is False


def test_static_bundles_go_to_the_assets_host(monkeypatch):
    seen = _stub(monkeypatch)
    with TestClient(main.app) as c:
        c.get("/ingest/static/exception-autocapture.js")
    assert seen["url"] == "https://us-assets.i.posthog.com/static/exception-autocapture.js"


def test_client_ip_is_forwarded_for_geoip(monkeypatch):
    seen = _stub(monkeypatch)
    with TestClient(main.app) as c:
        c.post("/ingest/e/", headers={"X-Forwarded-For": "203.0.113.9"})
    assert seen["headers"]["X-Forwarded-For"] == "203.0.113.9"


def test_unsafe_upstream_headers_are_not_re_emitted(monkeypatch):
    """Set-Cookie / CORS / Location from PostHog must not become headers of OUR origin."""
    _stub(monkeypatch, _Resp(headers={
        "Content-Type": "application/json", "Cache-Control": "no-store", "ETag": "W/abc",
        "Set-Cookie": "ph_session=1; Path=/", "Access-Control-Allow-Origin": "*",
        "Location": "https://evil.example/",
    }))
    with TestClient(main.app) as c:
        r = c.post("/ingest/e/")
    assert r.headers["cache-control"] == "no-store" and r.headers["etag"] == "W/abc"
    for banned in ("set-cookie", "access-control-allow-origin", "location"):
        assert banned not in {k.lower() for k in r.headers}


def test_upstream_failure_is_502_not_500(monkeypatch):
    _stub(monkeypatch, boom=requests.ConnectionError("posthog unreachable"))
    with TestClient(main.app) as c:
        r = c.post("/ingest/e/")
    assert r.status_code == 502   # analytics blip, not an app error


def test_upstream_status_is_passed_through(monkeypatch):
    _stub(monkeypatch, _Resp(status=401, content=b'{"detail":"bad token"}'))
    with TestClient(main.app) as c:
        r = c.post("/ingest/e/")
    assert (r.status_code, r.content) == (401, b'{"detail":"bad token"}')


def test_proxy_is_public_and_never_sends_cookies_upstream(monkeypatch):
    """Events fire before login, so /ingest sits outside the deny-by-default /api/ gate — and
    the pooled session is shared by every visitor, so no caller's cookies may leak upstream."""
    seen = _stub(monkeypatch)
    with TestClient(main.app) as c:
        c.cookies.set("session", "someone-elses-session")
        r = c.post("/ingest/e/")
    assert r.status_code == 200                       # not 401 from the auth gate
    assert "Cookie" not in seen["headers"]
    assert main._ph_session.cookies.get_policy().set_ok(None, None) is False
