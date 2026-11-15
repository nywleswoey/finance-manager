"""FastAPI — composition root. App object, middleware, auth gate, health, static SPA mount.
Product routes live in server/routes/{portfolio,networth,spending}.py, matching
web/src/modules/{portfolio,networth,spending}/; the price refresh (UI + cron) is
server/refresh.py and the PostHog proxy is server/posthog_proxy.py.

Run: PYTHONPATH=. .venv/bin/uvicorn server.main:app --reload --port 8000

Locked behind Google OAuth: every /api/* route except the auth + health endpoints
requires a valid session cookie (deny-by-default gate below). See server/auth.py.
The SECURITY-NN codes cited here are defined in DEPLOY.md § Security register.
"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from portfolio.config import settings
from server import auth, posthog_proxy, refresh

# NwValueIn, ticker_ledger and performance are re-exported: tests and scripts/audit_ledger.py
# import them from server.main (they moved with their routes). _cache likewise:
# server.main._cache must stay the object server.refresh clears and the one the portfolio
# routes memoize into — not a private main.py global.
from server.routes.networth import NwValueIn  # noqa: F401
from server.routes.networth import router as networth_router
from server.routes.portfolio import _cache, performance, ticker_ledger  # noqa: F401
from server.routes.portfolio import router as portfolio_router
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
# refresh.CRON_PATH is "public" only in the sense that the cookie gate must not answer it — a
# Vercel Cron request carries no session. Its handler authenticates against CRON_SECRET and
# fails closed when that env var is unset.
def _router_paths(router):
    """Full URL paths of a router's HTTP routes. The gate reads these so a prefix
    change cannot leave a copied literal behind."""
    out = set()
    for route in router.routes:
        path = getattr(route, "path", None)
        if not path or not getattr(route, "methods", None):
            continue
        if path.startswith(router.prefix):
            out.add(path)
        else:
            out.add(router.prefix.rstrip("/") + path)
    return out


# Auth routes are the login entry, so every route on that router is public. Health is declared
# on this app; the cron path is the one route of refresh's router the gate must let through.
_PUBLIC_PATHS = _router_paths(auth.router) | {"/api/health", refresh.CRON_PATH}

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
    prefix = spending_router.prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


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
app.include_router(refresh.router)
app.include_router(posthog_proxy.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Top-level handler: log internally, return a generic message — never leak stack
    traces or internals to the client (SECURITY-09, SECURITY-15)."""
    log.exception("unhandled error path=%s", request.url.path)
    return JSONResponse({"detail": "internal error"}, status_code=500)


# serve the built frontend (web/dist) if present
_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
