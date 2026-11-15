"""Same-origin PostHog reverse proxy: `/ingest/{path}`.

posthog-js posts analytics + error-tracking traffic to same-origin "/ingest" instead of the
PostHog cloud host, so it is covered by the strict CSP's `connect-src 'self'` /
`script-src 'self'` with no third-party origin to allow-list. Ingestion calls go to
POSTHOG_HOST; the lazily-loaded JS bundles under /static/ (exception-autocapture, surveys,
recorder) go to the matching *-assets host, mirroring PostHog's own proxy guidance.
Public by design: /ingest isn't under /api/, so the deny-by-default auth gate lets it through
(analytics/error events fire before and without a session). DEPLOY.md § Operations has the
operator's view. Tests: tests/test_posthog_proxy.py (they stub `_ph_session.request`).
"""
import logging
from http import cookiejar

import requests
from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from portfolio.config import settings

router = APIRouter()
log = logging.getLogger("api")

_PH_INGEST = settings.posthog_host.rstrip("/")
_PH_ASSETS = _PH_INGEST.replace(".i.posthog.com", "-assets.i.posthog.com")
if _PH_ASSETS == _PH_INGEST:
    # the replace was a no-op (custom or self-hosted POSTHOG_HOST), so /ingest/static/* goes to
    # the ingestion host and the lazily-loaded bundles 404 — error tracking silently disabled
    log.warning("POSTHOG_HOST=%s has no matching *-assets host; /ingest/static/* bundles "
                "(exception-autocapture, surveys, recorder) will likely 404", _PH_INGEST)
# Allow-list, not a deny-list: these are the only upstream response headers safe to re-emit
# from our own origin. Notably excluded are Set-Cookie (a third party must not set cookies on
# the session domain), Access-Control-* (would let any cross-origin page read /ingest/*),
# Location (never redirect our origin to a PostHog-chosen URL) and the framing/length headers
# that requests+Starlette recompute for the decoded body.
_PH_KEEP_HEADERS = {"content-type", "cache-control", "etag", "vary"}
# reused across invocations for connection pooling — posthog-js fires several calls per page
_ph_session = requests.Session()


class _BlockAllCookies(cookiejar.DefaultCookiePolicy):
    """Refuse to store or send any cookie. The pooled session is shared by every visitor, so a
    live jar would replay one caller's PostHog cookies on behalf of all the others."""
    def set_ok(self, cookie, request): return False
    def return_ok(self, cookie, request): return False
    def domain_return_ok(self, domain, request): return False
    def path_return_ok(self, path, request): return False


_ph_session.cookies.set_policy(_BlockAllCookies())


@router.api_route("/ingest/{path:path}", methods=["GET", "POST"])
async def posthog_proxy(path: str, request: Request):
    upstream = _PH_ASSETS if path.startswith("static/") else _PH_INGEST
    body = await request.body()
    headers = {}
    if ct := request.headers.get("content-type"):
        headers["Content-Type"] = ct
    # without this PostHog sees python-requests/... and may filter the event as bot traffic
    if ua := request.headers.get("user-agent"):
        headers["User-Agent"] = ua
    # preserve the caller's IP so PostHog geoip still resolves through the proxy
    xff = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")
    if xff:
        headers["X-Forwarded-For"] = xff
    try:
        # allow_redirects=False: an upstream 3xx must not make the server fetch a PostHog-chosen URL
        r = await run_in_threadpool(
            lambda: _ph_session.request(request.method, f"{upstream}/{path}",
                                        params=request.url.query, data=body or None,
                                        headers=headers, timeout=10, allow_redirects=False))
    except requests.RequestException as e:
        # best-effort analytics: a PostHog blip must not become an app 500 / error-level log
        log.warning("posthog proxy upstream failed path=%s: %s", path, e)
        return Response(status_code=502)
    out = {k: v for k, v in r.headers.items() if k.lower() in _PH_KEEP_HEADERS}
    return Response(content=r.content, status_code=r.status_code, headers=out)
