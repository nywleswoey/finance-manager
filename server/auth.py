"""Authentication — Google OAuth sign-in + email allowlist + signed session cookie.

Security-critical logic is isolated in this module (SECURITY-11). The deny-by-default
request gate lives in server.main. No secrets in source — everything via env (SECURITY-12).

Flow:
  SPA does Google Sign-In -> gets a Google ID token (JWT) -> POST /api/auth/google.
  We verify the token (signature + audience + issuer + expiry) against Google's JWKS,
  require email_verified and membership in ALLOWED_EMAILS, then mint our own short-lived
  session JWT and set it as an HttpOnly/Secure/SameSite cookie. Every later request is
  validated by the gate, which also re-checks the allowlist so removing an email from the
  env var revokes access immediately (no wait for token expiry).
"""
import datetime as dt
import logging
import time

import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token as g_id_token
from pydantic import BaseModel, Field

from portfolio.config import settings

log = logging.getLogger("auth")

COOKIE_NAME = "session"
SESSION_TTL = dt.timedelta(days=7)
_ALG = "HS256"
_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Reused across requests within a warm worker. google-auth caches Google's certs on it.
_google_request = g_requests.Request()


# ---------------- Google ID token verification ----------------

def verify_google(credential: str) -> dict:
    """Verify a Google ID token. Returns the claims dict. Raises on any failure.

    google-auth validates the signature against Google's published certs, the audience
    (== our client id) and the expiry. We additionally pin the issuer and require a
    verified email (defense in depth, SECURITY-08/13)."""
    if not settings.google_client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID not configured")
    info = g_id_token.verify_oauth2_token(credential, _google_request, settings.google_client_id)
    if info.get("iss") not in _GOOGLE_ISSUERS:
        raise ValueError("untrusted issuer")
    if not info.get("email_verified"):
        raise ValueError("email not verified")
    if not info.get("email"):
        raise ValueError("no email in token")
    return info


# ---------------- our session cookie ----------------

def mint_session(email: str, name: str | None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": email.lower(), "name": name or "", "iat": now, "exp": now + SESSION_TTL}
    return jwt.encode(payload, settings.session_secret, algorithm=_ALG)


def verify_session(token: str) -> dict:
    """Decode + validate our session JWT (signature + expiry). Raises on failure."""
    if not settings.session_secret:
        raise RuntimeError("SESSION_SECRET not configured")
    return jwt.decode(token, settings.session_secret, algorithms=[_ALG])


def user_from_request(request: Request) -> dict | None:
    """Return the authenticated user claims, or None. Fail-closed (SECURITY-15):
    any missing/invalid/expired cookie, or an email no longer in the allowlist,
    yields None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = verify_session(token)
    except Exception:
        return None
    if (payload.get("sub") or "").lower() not in settings.allowed_email_set:
        return None                                   # access revoked via env
    return payload


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,                                # not readable by JS (XSS-safe)
        secure=settings.cookie_secure,                # HTTPS-only in prod
        samesite="lax",
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                           secure=settings.cookie_secure, samesite="lax")


# ---------------- best-effort rate limit on the login endpoint ----------------
# In-memory; resets on cold start. Real protection is the signature check (a forged
# token can't pass), this just blunts spray. Documented best-effort (SECURITY-11).
_RATE_MAX = 10
_RATE_WINDOW = 60.0
_attempts: dict[str, list[float]] = {}


def _rate_ok(ip: str) -> bool:
    now = time.time()
    q = [t for t in _attempts.get(ip, []) if now - t < _RATE_WINDOW]
    q.append(now)
    _attempts[ip] = q
    return len(q) <= _RATE_MAX


# ---------------- routes ----------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


class GoogleIn(BaseModel):
    credential: str = Field(min_length=1, max_length=8192)   # bounded input (SECURITY-05)


@router.post("/google")
def google_login(body: GoogleIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    if not _rate_ok(ip):
        log.warning("auth rate-limited ip=%s", ip)
        raise HTTPException(429, "too many attempts")
    try:
        info = verify_google(body.credential)
    except Exception:
        log.warning("auth rejected: invalid google token ip=%s", ip)   # no token in logs
        raise HTTPException(401, "invalid credential")
    email = info["email"].lower()
    if email not in settings.allowed_email_set:
        log.warning("auth denied: not allowlisted email=%s ip=%s", email, ip)
        raise HTTPException(403, "not authorized")
    _set_cookie(response, mint_session(email, info.get("name")))
    log.info("auth success email=%s", email)
    return {"email": email, "name": info.get("name")}


@router.get("/me")
def me(request: Request):
    user = user_from_request(request)
    if not user:
        raise HTTPException(401, "not authenticated")
    return {"email": user["sub"], "name": user.get("name")}


@router.post("/logout")
def logout(response: Response):
    _clear_cookie(response)
    return {"ok": True}
