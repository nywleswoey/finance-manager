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
| `CRON_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(32))"` — Production only; Vercel sends it as the cron's `Authorization: Bearer …` (§6). Unset ⇒ the cron route denies every caller |
| `DATABASE_URL` | the `sslmode=require` Postgres URL |
| `VITE_PUBLIC_POSTHOG_KEY` | PostHog project API key (`phc_…`) |
| `VITE_PUBLIC_POSTHOG_HOST` | PostHog host, e.g. `https://us.i.posthog.com` — used as `ui_host` (toolbar links) and to gate `posthog.init()`; events go through the same-origin `/ingest` proxy, not here |
| `POSTHOG_HOST` | Server-side upstream the `/ingest` proxy forwards to — same region host as above (`https://us.i.posthog.com`). Defaults to that if unset. Must be a `*.i.posthog.com` region host: the proxy derives the assets host from it, so a custom/self-hosted value logs a startup warning and leaves the lazily-loaded bundles (exception autocapture, surveys, recorder) 404ing — error tracking silently off |

> **PostHog is all-or-nothing and build-time.** Missing either `VITE_*` var skips
> `posthog.init()`, so the deploy ships with no analytics *and* no error tracking (uncaught
> exceptions, unhandled promise rejections, React render errors). `VITE_*` vars are baked into
> the bundle at build time — adding them takes effect on the next deploy, not on the running
> one. No CSP change is needed — see [Security ops](#security-ops) for why.

> **`SPENDING_EMAILS` fails closed.** Omit it and the Spending section disappears for everyone —
> the nav item is hidden and `/api/spending/*` returns 403, including for accounts in
> `ALLOWED_EMAILS`. Set it on Production *and* Preview.

## 4. Deploy (single FastAPI project)
Vercel deploys the whole repo as **one FastAPI Vercel Function** that serves both the
API and the built SPA (same origin → first-party session cookie). `vercel.json` carries the
cron schedule (§6) and **nothing else** — build settings stay with Vercel's framework
detection, and a key added here silently overrides the dashboard:

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

## 6. Keeping the deployed data fresh (schedules)

Two schedules, because the sources split cleanly in two: **Yahoo is reachable from anywhere,
everything else is a file on the laptop.** `data/` is gitignored, so no deployment has ever
contained a broker statement — dividends, transactions, spending and net-worth snapshots can
only be produced by the machine holding the PDFs. Prices are the one exception, and the only
thing the cloud can refresh alone.

| | What runs | When | Reaches |
|---|---|---|---|
| **launchd** (this Mac) | `make ingest-all` | daily 06:15 SGT | statements → `txn`/`dividend`, spending, prices + FX, the Endowus NAV, snapshots |
| **Vercel Cron** | `GET /api/cron/refresh-prices` | daily 23:15 UTC (≈07:15 SGT) | Yahoo closes + FX only |

One local agent, not two: `ingest-all` ends in `make prices`, so a separate price job would
refresh what this one already refreshes. It ran weekly at first, which left a statement
dropped on Monday unloaded until Sunday — for ~4 minutes of overnight work, that wait bought
nothing.

**What is still manual**: putting the statement in `data/`. Nothing downloads from Tiger,
Moomoo, FSM, CDP or Endowus — the schedule loads whatever is sitting there, the morning after
you drop it.

The local job writes to the **deployed** Neon database — that is the whole point, and the one
thing to get wrong: `make ingest` with no `DATABASE_URL` writes to the local docker DB and
reports success while the site goes stale. `scripts/scheduled_run.sh` resolves
`DATABASE_URL_UNPOOLED` from `.env.local` and refuses to run against a localhost URL.

```sh
make schedule-install     # write + load the launchd agent (~/Library/LaunchAgents)
make schedule-status      # loaded? last exit code? last three log lines?
make schedule-test        # run it now
make schedule-uninstall
```

Log: `~/Library/Logs/portfolio/ingest-all.log`. A missed calendar time (machine asleep) fires
**once** on wake, not once per occurrence; powered off, at next login. Every target is
idempotent, so a catch-up and a duplicate are equally harmless.

The one way this leaves prices stale: `make ingest` failing aborts the chain before the price
step (`ingest-all` runs ingest → spending → prices → snapshots). The Vercel Cron an hour later
refreshes them anyway, which is the second reason it exists.

### 6a. The Vercel Cron half — enabling it, step by step

Only for the days the laptop is shut. Two things have to be true before a single invocation
happens, and **neither is in the code you just merged**: the secret must exist as a
Production env var, and a *new production deployment* must be built after `vercel.json`
declared the cron. A cron belongs to the deployment that declared it — merging the file is
not enough.

**1 — Generate the secret.** Vercel's own recommendation is ≥16 characters of random.

```sh
python3 -c "import secrets;print(secrets.token_urlsafe(32))"
```

**2 — Store it as a Production env var.** The name must be exactly `CRON_SECRET`: Vercel
sends *that* variable as the `Authorization` header, and nothing else is consulted.

```sh
vercel env add CRON_SECRET production      # paste the value from step 1 at the prompt
```

Dashboard equivalent: **Project → Settings → Environment Variables → Add**, name
`CRON_SECRET`, Environment = **Production** only. Preview does not need it (crons only ever
hit the production deployment), and leaving it off Preview keeps one fewer copy of a
credential that can drive writes.

**3 — Deploy from `main`.** Push the merge, or **Deployments → Redeploy** on the latest
production build. The commit author's email must be authorised or the build never
runs — see [§4](#commit-author-must-be-an-authorised-email). Watch for the build to finish;
a `BLOCKED` deployment declares no cron.

**4 — Confirm the cron was registered.** **Project → Settings → Cron Jobs** must list
`/api/cron/refresh-prices` with schedule `15 23 * * *`. If the page is empty, the deployment
that shipped `vercel.json` was not promoted to production — nothing else causes this.

**5 — Prove the endpoint before waiting a day for it.** Two curls, both from your machine —
the first is the one that matters, because a route this shape is only safe if the naked path
is dead:

```sh
APP=https://<your-app>.vercel.app

curl -si "$APP/api/cron/refresh-prices" | head -1
# HTTP/2 401     <- required. Anything else: STOP, the route is open to the internet.

curl -s -H "Authorization: Bearer $CRON_SECRET" "$APP/api/cron/refresh-prices"
# {"ok":35,"fail":0,"date":"2026-08-06","failed":[],"fx_failed":[]}
```

**`ok` is 35, not 36, and that is correct here** — the Endowus fund is skipped in the cloud
and counted in neither `ok` nor `fail`, so the response cannot tell you it happened (see the
third bullet below). Locally the same call reports 36. A second call is safe either way: the
write is a merge keyed on (security, date), so running it twice changes nothing.

**6 — Check the first real run the next morning.** Settings → Cron Jobs → **View Logs**
(filtered to `requestPath:/api/cron/refresh-prices`), or from the data side:

```sh
set -a; . ./.env.local; set +a
psql "$DATABASE_URL_UNPOOLED" -c "select max(date) from price; select max(date) from fx_rate;"
```

#### Changing or turning it off
- **Reschedule**: edit the `schedule` in `vercel.json`, commit, redeploy. Editing it anywhere
  else does not survive the next deploy.
- **Pause without a deploy**: Settings → Cron Jobs → **Disable Cron Jobs**.
- **Remove**: delete the entry from `vercel.json` and redeploy.
- **Rotate the secret**: `vercel env rm CRON_SECRET production` then add the new value, and
  **redeploy** — a running deployment keeps the value it was built with.
- **Revoke instantly**: remove `CRON_SECRET`. The route then denies every caller, including
  Vercel's own (it fails closed by design), while the local launchd jobs carry on untouched.

#### Four things to know about it
- **Hobby plan**: at most one run per day, fired at any minute inside the stated hour
  (23:00–23:59 UTC). A more frequent expression fails the deployment outright. Max 2 crons.
- **23:15 UTC is deliberate** — after the US close, and already the next SGT day, so the row
  it writes carries the same date the 06:15 SGT local run would use (`ingestion.prices.sg_today`,
  not the function's UTC clock).
- **It cannot price the Endowus fund**, and says nothing about it. That NAV is scraped from
  the latest statement PDF in `data/`, absent from the deployment: `endowus_nav()` finds no
  file, returns `None`, and the loop moves on without touching `ok` or `fail`. So a cloud run
  reports `35 ok, 0 fail` and looks clean. Only the local daily/Sunday run moves that NAV.
- **No retries, best-effort delivery.** A failed or missed run is not re-attempted; the next
  one is 24h later. That is tolerable only because the job is idempotent and the local
  06:15 run covers the same ground.

#### If it does not fire
| Symptom | Cause |
|---|---|
| Cron Jobs page empty | `vercel.json` never reached a **production** deployment |
| Build fails on the cron | Schedule is more frequent than daily (Hobby limit) |
| Logs show `401` | `CRON_SECRET` missing on Production, or set after the current deployment was built — redeploy |
| Logs show `404` | Path typo; Vercel still invokes and still logs it |
| Ran, but `price.date` did not move | Read the JSON in the log: all-`fail` means Yahoo refused the deployment's IP, not a scheduling problem |

Duration is not a concern in practice: 36 held securities + 4 FX pairs run in ~19s against
the 300s function ceiling. It stays sequential and unretried — a failed run is visible in
**Project → Settings → Cron Jobs → View Logs**, and the next run is 24h later.

## Security ops
- **Dependency scan (SECURITY-10)**: `.github/workflows/audit.yml` runs
  `pip-audit -r requirements.txt` and `npm audit --audit-level=high` every Monday 07:00 SGT,
  so the scan no longer depends on remembering it before a deploy. Run it on demand from the
  **Actions** tab, or locally with `uvx pip-audit -r requirements.txt`. Lock files (`uv.lock`,
  pinned `requirements.txt`) are committed.
- **Dependency updates**: Dependabot (`.github/dependabot.yml`) opens grouped PRs weekly for
  the Python manifests and `web/package-lock.json`, monthly for the workflow actions.
  Minor/patch **development** bumps auto-merge once CI passes; anything that reaches
  production waits for you. See [§Dependency updates](#dependency-updates) below.
- **Local dev**: copy `.env.example` → `.env` (`COOKIE_SECURE=false` for http), and
  `web/.env.example` → `web/.env.local`. Run API (`make api`, i.e. `uvicorn server.main:app
  --port 8000`) + `npm run dev` (Vite proxies `/api` **and** `/ingest` → 8000, so the
  same-origin cookie works and PostHog traffic takes the same proxy path as production).
- **Headers**: HTTP security headers (CSP/HSTS/X-Content-Type-Options/X-Frame-Options/
  Referrer-Policy) are set by the FastAPI middleware in `server/main.py`, which serves both
  the API and the static SPA. CSP allows `accounts.google.com` for Google Identity Services
  (which ships no SRI hash — origin pin instead) and inline styles for React/GIS;
  `script-src` stays strict.
- **PostHog is proxied same-origin (no CSP host needed)**: posthog-js posts to `/ingest`
  (same origin), which the FastAPI reverse proxy in `server/main.py` forwards to `POSTHOG_HOST`
  (ingestion) and its `*-assets` host (the lazily-loaded exception-autocapture/recorder
  bundles). Because the traffic is first-party, the strict `connect-src 'self'` /
  `script-src 'self'` already cover it — no PostHog origin is added to the CSP. If you ever
  switch back to hitting PostHog directly, you must instead allow the host in `connect-src`.
  `/ingest` is deliberately **unauthenticated** — it sits outside `/api/`, so the
  deny-by-default gate lets it through; analytics and error events fire before sign-in. It
  forwards only to `POSTHOG_HOST`, never follows upstream redirects, and re-emits no
  `Set-Cookie`/`Access-Control-*`/`Location` headers.

## Dependency updates
Dependabot opens the PRs, `.github/workflows/ci.yml` decides whether they are safe, and
`.github/workflows/dependabot-automerge.yml` merges the boring ones.

**Two Python manifests, one resolver.** `uv.lock` is the resolved truth for everything;
`requirements.txt` is the runtime subset the Vercel Python builder installs into the function
— deliberately without alembic/uvicorn/ruff/pytest, which never run inside a request. Nothing
derives one from the other (`uv export` would drag alembic and uvicorn in, because they are
real `[project].dependencies`), so the package *list* in `requirements.txt` is a human's
choice. The *versions* are not: `scripts/sync_requirements.py` re-pins them from `uv.lock`,
and CI fails on drift.

**Dependabot updates all three files itself.** `uv` names the resolver, not the file set —
its Python updater rewrites every manifest in the directory it can, `requirements.txt`
included. PR #70 carried `fastapi` 0.138.0 → 0.141.1 into `pyproject.toml`, `uv.lock` *and*
the runtime pins in one PR, and the drift check passed on it. So there is no routine step
here: you do not run `make sync-requirements` on a Dependabot PR.

What the check actually guards is a **hand-run `uv lock`** — which is exactly how this repo
ended up with a lockfile that had no entry for `anthropic` at all while `requirements.txt`
pinned it. If CI ever fails on drift:

```
make sync-requirements     # re-pin requirements.txt from uv.lock, then commit
```

**Grouping, and the trap in it.** Most groups are scoped `update-types: [minor, patch]`,
which **silently excludes majors** — a major falls out of its group and gets its own PR.
Harmless for an independent package; a deadlock for a coupled pair, which is what happened
on the first run: react 18→19 and react-dom 18→19 arrived as two PRs (#67, #69), and neither
could be merged alone. The pairs that must travel together are therefore grouped by *name*,
which covers every update type: `react`+`react-dom`, `vite`+`@vitejs/plugin-react`,
`sqlalchemy`+`alembic`. Add to those patterns before adding a coupled dependency, not after.

**What auto-merges**: minor and patch **development** dependencies (ruff, pytest, vite,
`@playwright/test`, `@vitejs/plugin-react`), and only once both CI jobs pass. Nothing that
reaches a user, and no majors. A production or major PR gets a comment saying why it is
waiting, and stays open.

**Two repo settings this depends on** — without them the automerge workflow is either a
no-op or, worse, merges without waiting:
1. **Settings → General → Allow auto-merge** — ticked. `gh pr merge --auto` errors without it.
2. **Settings → Rules/Branches** — a ruleset on `main` requiring the `python` and `web`
   status checks. Auto-merge waits for *required* checks; with none required it merges
   immediately.

**CI runs more than the local default.** `make test-web` and `pytest -m "not pg"` are the
fast local loop; CI runs the whole thing — the 33 `pg`-marked tests against a real Postgres
service container (same image, credentials and port 5544 as `docker-compose.yml`, so no env
var is needed), plus all 1,497 Playwright tests. The Postgres-only SQL and the production
vite build are exactly what a psycopg or vite bump breaks.
