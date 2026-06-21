# Functional Design — Auth Unit (Google OAuth + Vercel)

## Goal
Put the portfolio app behind Google sign-in. Only emails in an allowlist may
access any data API. Deploy as one Vercel project (static SPA + Python serverless
API, managed Postgres).

## Decisions (Requirements Analysis)
- **Topology**: All on Vercel (serverless). SPA + `/api/*` same origin → first-party cookie.
- **Auth**: App-level Google OAuth. SPA gets Google ID token → backend verifies → mints own session cookie → allowlist enforced on every request.
- **Security Baseline**: ENABLED (blocking).

## Auth flow
```
Browser                         Vercel /api (FastAPI)               Google
  | Google Sign-In (GIS)  ----------------------------------------->  |
  |<--------------- ID token (JWT, signed by Google) ---------------  |
  | POST /api/auth/google {credential} -->                            |
  |                         verify sig+aud+iss+exp via Google JWKS    |
  |                         email_verified? email in ALLOWED_EMAILS?  |
  |                         mint session JWT (HS256, SESSION_SECRET)  |
  |<-- Set-Cookie: session=...  HttpOnly; Secure; SameSite=Lax        |
  | GET /api/overview  (cookie auto-sent) -->                         |
  |                         gate: verify session JWT + recheck allowlist
  |<-- 200 data    (or 401 if no/invalid cookie, 403 if removed)      |
```

### Why own session cookie (not raw Google token each request)
- Google ID token lifetime ~1h; re-hitting JWKS per request = latency.
- Session JWT self-contained, fast HS256 verify, HttpOnly (XSS-safe), controllable TTL.
- **Instant revoke**: gate re-checks `email ∈ ALLOWED_EMAILS` every request → remove
  an email from env var and access dies immediately (no wait for token expiry).

## Backend components
| File | Role |
|---|---|
| `api/auth.py` (new) | auth config, Google verify, session mint/verify, `require_user` dep, router, auth-event logging |
| `api/main.py` (edit) | lock CORS, security-headers mw, deny-by-default auth gate mw, include auth router, generic errors |
| `api/index.py` (new) | Vercel ASGI entry: `from api.main import app` |

### Routes
- `POST /api/auth/google` — body `{credential: str}` (max-len bound). Verify → set cookie → return `{email,name}`. **Public** (login entry). Rate-limited.
- `GET  /api/auth/me` — return current user or 401. Public (used to test session).
- `POST /api/auth/logout` — clear cookie. Public.
- All other `/api/*` — **deny by default** (gate middleware). 401 without valid session.

### Auth gate (deny-by-default middleware)
- Exempt: `OPTIONS` (CORS preflight), `/api/auth/google`, `/api/auth/me`, `/api/auth/logout`, `/api/health`.
- Else if path starts `/api/`: require valid session cookie → else 401. Fail **closed** on any verify error.

## Frontend components
| File | Role |
|---|---|
| `web/src/auth.jsx` (new) | AuthProvider: GETs `/api/auth/me`; if 401 renders Google Sign-In gate; else app. Loads GIS script dynamically. Logout. |
| `web/src/api.js` (edit) | `credentials:"include"`; on 401 → broadcast → force re-login |
| `web/src/main.jsx` (edit) | wrap `<App/>` in `<AuthGate>` |
| `web/src/App.jsx` (edit) | show signed-in email + Logout button |
| `web/.env.example` (new) | `VITE_GOOGLE_CLIENT_ID` |

## Config (env vars — no secrets in code)
| Var | Where | Purpose |
|---|---|---|
| `GOOGLE_CLIENT_ID` | api + `VITE_GOOGLE_CLIENT_ID` web build | OAuth client / token audience |
| `SESSION_SECRET` | api (server-only) | HS256 session signing key (strong random) |
| `ALLOWED_EMAILS` | api | comma-separated allowlist |
| `ALLOWED_ORIGINS` | api | CORS allowlist (prod URL + localhost) |
| `COOKIE_SECURE` | api | `true` prod, `false` local http |
| `DATABASE_URL` | api | managed Postgres, TLS (`sslmode=require`) |

## Deploy artifacts
- `vercel.json` — build SPA (`web/`) + python fn (`api/index.py`); route `/api/*`→fn, else SPA fallback.
- `requirements.txt` — pinned: sqlalchemy, psycopg[binary], fastapi, pydantic-settings, python-dotenv, **google-auth, PyJWT**.
- Postgres → Neon/Vercel Postgres (TLS + encryption at rest). Set `DATABASE_URL`.
- Price refresh: blocking external fetch → timeout risk on serverless. Keep endpoint (auth-protected) + document Vercel Cron + `maxDuration`. Out of auth scope.

## Security Baseline compliance (SECURITY-01..15)
| Rule | Status | How |
|---|---|---|
| 01 Encryption rest/transit | Compliant | Managed PG (TLS, at-rest); `sslmode=require`; Vercel HTTPS |
| 02 Net-intermediary logging | N/A (platform) | Vercel provides access logs |
| 03 App logging | Compliant | structured auth-event logs (success/denied/invalid), no token/PII |
| 04 HTTP security headers | Compliant | CSP/HSTS/X-CTO/X-Frame/Referrer mw; CSP allows Google GIS origin (documented) |
| 05 Input validation | Compliant | pydantic models, credential max-len, parameterized SQL (existing) |
| 06 Least-privilege IAM | N/A (platform) | Vercel-managed |
| 07 Network config | N/A (platform) | Vercel-managed |
| 08 App access control | Compliant | deny-by-default gate, server-side token validate (sig/exp/aud/iss), CORS locked, no wildcard on auth'd. Object-level IDOR N/A (single shared owner dataset) |
| 09 Hardening | Compliant | generic errors (no stack traces), no default creds, no demo pages |
| 10 Supply chain | Compliant | pinned requirements.txt + uv.lock committed; `pip-audit` in build docs |
| 11 Secure design | Compliant | auth isolated in `api/auth.py`; rate-limit on `/api/auth/google` (best-effort) |
| 12 Auth/credential mgmt | Compliant | federated (no passwords → policy/hash N/A); cookie Secure+HttpOnly+SameSite; logout clears; short TTL + allowlist recheck = revoke; MFA via Google |
| 13 Integrity | Compliant w/ exception | JWT verified before trust; Google GIS script has no SRI (Google constraint) → mitigated by CSP origin pin (documented) |
| 14 Alerting | Partial / N/A | auth-failure logs emitted; alerting = platform/out-of-scope |
| 15 Fail-safe defaults | Compliant | gate fails closed; try/except on DB+external; generic user errors; global handler |

No blocking (non-compliant) findings. Exceptions documented: SECURITY-13 (Google GIS no-SRI), SECURITY-04 (CSP allows accounts.google.com).
