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
| `SPENDING_EMAILS` | `you@gmail.com` — subset of `ALLOWED_EMAILS` that may see Spending |
| `ALLOWED_ORIGINS` | `https://<your-app>.vercel.app` |
| `COOKIE_SECURE` | `true` |
| `DATABASE_URL` | the `sslmode=require` Postgres URL |

> **`SPENDING_EMAILS` fails closed.** Omit it and the Spending section disappears for everyone —
> the nav item is hidden and `/api/spending/*` returns 403, including for accounts in
> `ALLOWED_EMAILS`. Set it on Production *and* Preview.

## 4. Deploy (single FastAPI project)
Vercel deploys the whole repo as **one FastAPI Vercel Function** that serves both the
API and the built SPA (same origin → first-party session cookie). There is no
`vercel.json`; the model relies on Vercel's framework detection:

- Vercel detects the entrypoint at `api/index.py` (re-exports `server.main:app`) and
  installs Python deps from `pyproject.toml`/`uv.lock`.
- The `[tool.vercel.scripts] build` hook in `pyproject.toml` runs `npm --prefix web run
  build`, producing `web/dist`, which FastAPI serves via its StaticFiles mount.

**Project Settings → General** (one-time):
- **Framework Preset**: FastAPI
- **Root Directory**: `./` (repo root)
- **Build Command / Output Directory**: leave as preset defaults (no override). A custom
  Build Command makes Vercel treat the project as static and skip the Python install —
  that's what caused the earlier `ModuleNotFoundError: No module named 'fastapi'`.

Push to `main` (or Redeploy) to build.

### Commit author must be an authorised email
Vercel authorises each deployment against the **commit author's email**, before the build
runs. An unrecognised author email gives a `BLOCKED` deployment — GitHub shows
`Vercel — Deployment was blocked`, `buildSkipped: true`, and no build log at all (nothing
was built, so this is never a code or build error). The author email must be one listed
under Vercel **Account Settings → Emails**: `sgfjords@gmail.com`.

The trap is git's fallback identity: with no `user.email` configured, git invents one from
the machine hostname (e.g. `selwynyeow@Personal-MacBook-Air.local`) and every commit made
from that clone is undeployable. Set the identity once per clone/worktree — including
throwaway agent worktrees, which do not inherit it:

```sh
git config user.name  nywleswoey
git config user.email sgfjords@gmail.com
```

Already-pushed commits keep their author, so a blocked commit stays blocked: push a new
commit (or re-author it) with the right identity to get a fresh deployment.

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
