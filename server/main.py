"""FastAPI — composition root. App object, middleware, auth gate, health/refresh/cron,
PostHog proxy, static SPA mount. Product routes live in server/routes/{portfolio,networth,
spending}.py, matching web/src/modules/{portfolio,networth,spending}/.

Run: PYTHONPATH=. .venv/bin/uvicorn server.main:app --reload --port 8000

Locked behind Google OAuth: every /api/* route except the auth + health endpoints
requires a valid session cookie (deny-by-default gate below). See server/auth.py.
"""
import hmac
import logging
import os
import sys
from http import cookiejar

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import requests
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from portfolio.config import settings

from server import auth
# NwValueIn, ticker_ledger and performance are re-exported: tests and scripts/audit_ledger.py
# import them from server.main (they moved with their routes). _cache likewise:
# server.main._cache must stay the object /api/refresh clears and the one the portfolio routes
# memoize into — not a private main.py global.
from server.routes.networth import NwValueIn, router as networth_router  # noqa: F401
from server.routes.portfolio import (_cache, performance, router as portfolio_router,  # noqa: F401
                                     ticker_ledger)
from server.routes.spending import router as spending_router

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")  # SECURITY-03
log = logging.getLogger("api")

app = FastAPI(title="Portfolio API")

if settings.auth_bypass_active:
    log.warning("⚠️  DEV_AUTH_BYPASS active — auth gate DISABLED, every request is 'dev@localhost'. "
                "Local dev only; this is force-off on Vercel.")

# Endpoints reachable WITHOUT a session (login entry + liveness). Everything else
# under /api/ is denied by default by the gate middleware (SECURITY-08).
# /api/cron/refresh-prices is "public" only in the sense that the cookie gate must not answer
# it — a Vercel Cron request carries no session. It authenticates itself against CRON_SECRET
# inside the handler and fails closed when that env var is unset.
_PUBLIC_PATHS = {"/api/auth/google", "/api/auth/me", "/api/auth/logout", "/api/health",
                 "/api/cron/refresh-prices"}

# HTML security headers for both the API and the static SPA — this middleware is the only
# place they are set (vercel.json exists, but carries the cron schedule and nothing else).
# script-src stays strict (no unsafe-inline) — the XSS-relevant directive. style-src
# allows inline because React inline styles + the Google button need it (documented
# exception, SECURITY-04). accounts.google.com is allowed for Google Identity Services
# (SECURITY-13: GIS ships no SRI hash, so we pin its origin instead).
_CSP = ("default-src 'self'; "
        "script-src 'self' https://accounts.google.com; "
        "frame-src https://accounts.google.com; "
        "connect-src 'self' https://accounts.google.com; "
        "img-src 'self' https://*.googleusercontent.com data:; "
        "style-src 'self' 'unsafe-inline'; "
        "base-uri 'self'; frame-ancestors 'none'")


def _is_spending(path: str) -> bool:
    # exact-or-child only: a bare startswith would also swallow a future "/api/spending-export"
    return path == "/api/spending" or path.startswith("/api/spending/")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Deny-by-default: any /api/* path that isn't public requires a valid session.
    Fails closed (SECURITY-08, SECURITY-15)."""
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in _PUBLIC_PATHS:
        return await call_next(request)
    user = auth.user_from_request(request)
    if not user:
        return JSONResponse({"detail": "not authenticated"}, status_code=401)
    # Function-level authorization (SECURITY-08). Runs after authentication, so an anonymous
    # caller still gets 401 and we don't advertise the feature's existence to strangers; runs
    # before call_next, so a denied caller never reaches a handler or a database query.
    # Hiding the nav item in the SPA is cosmetic — this is the control.
    if _is_spending(path) and not auth.can_view_spending(user):
        log.warning("spending denied path=%s", path)   # no email: SECURITY-03 keeps PII out of logs
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    request.state.user = user
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = _CSP
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # index.html must never be cached: a stale copy points at an old (now-404) JS
    # bundle hash after a redeploy -> blank screen. Hashed /assets/* stay cacheable.
    ct = resp.headers.get("content-type", "")
    if ct.startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# CORS added last => outermost => handles preflight before the gate. Locked to known
# origins with credentials (cookies); never wildcard on authenticated APIs (SECURITY-08).
app.add_middleware(CORSMiddleware, allow_origins=settings.origin_list,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(portfolio_router)
app.include_router(networth_router)
app.include_router(spending_router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Top-level handler: log internally, return a generic message — never leak stack
    traces or internals to the client (SECURITY-09, SECURITY-15)."""
    log.exception("unhandled error path=%s", request.url.path)
    return JSONResponse({"detail": "internal error"}, status_code=500)


@app.post("/api/refresh")
def refresh():
    _cache.clear()
    return {"ok": True}


def _refresh_prices():
    """Fetch latest prices + FX for held tickers, then invalidate the cache."""
    from ingestion.prices import main as fetch_prices
    result = fetch_prices()   # blocking; upserts price/fx_rate for current_position
    _cache.clear()            # next overview/positions recompute with fresh prices
    return result             # {ok, fail, date, failed, fx_failed}


@app.post("/api/refresh-prices")
def refresh_prices():
    """Manual refresh from the signed-in UI."""
    return _refresh_prices()


@app.get("/api/cron/refresh-prices")
def cron_refresh_prices(request: Request):
    """The same refresh, on a schedule (Vercel Cron — see DEPLOY.md §6).

    GET, because Vercel invokes a cron path with GET and nothing else; this is the one route
    where a mutating GET is not a choice. It bypasses the cookie gate (a cron request has no
    session) and instead compares the `Authorization: Bearer <CRON_SECRET>` header Vercel
    sends against the env var — constant-time, and denying when CRON_SECRET is unset, so a
    project that never set it has a dead route rather than an open one (SECURITY-15).

    A cloud run prices stocks + FX only: the Endowus NAV is scraped from a statement PDF in
    data/, which is gitignored and therefore absent from the deployment. That one fund's NAV
    moves only on the local scheduled run.
    """
    expected, got = settings.cron_secret, request.headers.get("authorization", "")
    if not expected or not hmac.compare_digest(got, f"Bearer {expected}"):
        log.warning("cron refresh-prices denied ua=%s", request.headers.get("user-agent", ""))
        return JSONResponse({"detail": "not authenticated"}, status_code=401)
    result = _refresh_prices()
    log.info("cron refresh-prices: %s", result)
    return result


# ---------------- PostHog same-origin reverse proxy ----------------
# posthog-js posts analytics + error-tracking traffic to same-origin "/ingest" instead of the
# PostHog cloud host, so it is covered by the strict CSP's `connect-src 'self'` /
# `script-src 'self'` with no third-party origin to allow-list. Ingestion calls go to
# POSTHOG_HOST; the lazily-loaded JS bundles under /static/ (exception-autocapture, surveys,
# recorder) go to the matching *-assets host, mirroring PostHog's own proxy guidance.
# Public by design: /ingest isn't under /api/, so the deny-by-default auth gate lets it through
# (analytics/error events fire before and without a session).
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


@app.api_route("/ingest/{path:path}", methods=["GET", "POST"])
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


# serve the built frontend (web/dist) if present
_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
