# Deploy — Vercel + Google Auth

The app is locked behind Google sign-in: only emails in `ALLOWED_EMAILS` can reach any
`/api/*` data route. Deploys as one Vercel project — static SPA (`web/`) + Python
serverless API (`api/index.py`) — backed by managed Postgres.

## 1. Google Cloud — OAuth client
1. <https://console.cloud.google.com> → create/select a project.
2. **APIs & Services → OAuth consent screen**: User type *External*, app name, add your
   account(s) as **Test users** (keeps the app in "testing" — only listed users sign in).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID → Web application**.
   - **Authorized JavaScript origins**: `https://<your-app>.vercel.app` and `http://localhost:5173` (dev).
   - Save. Copy the **Client ID** (`xxxx.apps.googleusercontent.com`).

The allowlist (`ALLOWED_EMAILS`) is the real access control — the consent-screen test-user
list is a second gate. Both should contain only designated accounts.

## 2. Postgres (managed, TLS)
Use Neon or Vercel Postgres (encryption at rest + TLS — SECURITY-01).
- Create a DB, copy the connection string, convert to the psycopg URL with TLS:
  `postgresql+psycopg://USER:PASS@HOST/DB?sslmode=require`
- Run migrations from your machine against it: `DATABASE_URL=... alembic upgrade head`
  (then seed as needed).

## 3. Vercel env vars
Project → Settings → Environment Variables (Production + Preview):

| Var | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | the OAuth client id |
| `VITE_GOOGLE_CLIENT_ID` | **same** client id (exposed to the web build) |
| `SESSION_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `ALLOWED_EMAILS` | `you@gmail.com,partner@gmail.com` |
| `ALLOWED_ORIGINS` | `https://<your-app>.vercel.app` |
| `COOKIE_SECURE` | `true` |
| `DATABASE_URL` | the `sslmode=require` Postgres URL |

## 4. Deploy
`vercel.json` already wires the build + routes. Push the branch / import the repo and
deploy. Vercel builds the SPA and the Python function automatically.

## 5. Revoking access
Remove the email from `ALLOWED_EMAILS` and redeploy (or update the env var). The gate
re-checks the allowlist on **every** request, so access dies immediately — no waiting
for the 7-day session cookie to expire.

## 6. Price refresh on serverless (note)
`POST /api/refresh-prices` does a blocking external fetch and can exceed the serverless
function timeout. Options: trigger it via **Vercel Cron** off-peak, raise the function
`maxDuration`, or run price ingestion from a scheduled job outside Vercel. Not part of the
auth work — the endpoint is auth-protected either way.

## Security ops
- **Dependency scan (SECURITY-10)**: `uv pip install pip-audit && pip-audit -r requirements.txt`
  before each deploy. Lock files (`uv.lock`, pinned `requirements.txt`) are committed.
- **Local dev**: copy `.env.example` → `.env` (`COOKIE_SECURE=false` for http), and
  `web/.env.example` → `web/.env.local`. Run API (`uvicorn api.main:app --port 8000`) +
  `npm run dev` (Vite proxies `/api` → 8000, same-origin cookie works).
- **Headers**: HTTP security headers (CSP/HSTS/X-Content-Type-Options/X-Frame-Options/
  Referrer-Policy) are set by FastAPI middleware (API) and `vercel.json` (static HTML).
  CSP allows `accounts.google.com` for Google Identity Services (which ships no SRI hash —
  origin pin instead) and inline styles for React/GIS; `script-src` stays strict.
