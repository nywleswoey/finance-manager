# finance-manager

Personal investment-portfolio + net-worth + spending platform. See [README.md](README.md) for
what it does and how to run it; [docs/](docs/) for domain glossary, runbooks, and archived
plans.

## Constraints agents must not break

- **Python is not an installable package.** Everything runs with `PYTHONPATH=.` (Makefile,
  pytest, CI, scripts). Do not add packaging.
- **`server.main:app` is the one FastAPI app.** `api/index.py` is the Vercel entrypoint — it
  re-exports `server.main:app` and must never move or rename that symbol. `vercel.json`'s cron
  hits `/api/cron/refresh-prices` on the same app.
- **Alembic lives in `migrations/`**, driven by `alembic.ini` (`script_location =
  %(here)s/migrations`). `env.py` imports `portfolio.config` and `portfolio.models.Base`. Don't
  move `migrations/` or `portfolio.models`. The models must describe exactly what the migrations
  create: CI runs `alembic check` on a freshly migrated DB (pg tests build from the models).
- **`make ingest-all`** delta-ingests every source (brokers, spending, prices, net-worth
  snapshots); idempotent. See the README table for per-source commands.
- **Frontend and HTTP routes are split by product; the domain package is not.**
  `web/src/modules/{portfolio,networth,spending}/` and `server/routes/{portfolio,networth,
  spending}.py` match; `portfolio/` stays one package (kernel + all three products) — see
  [docs/runbooks/BACKEND.md](docs/runbooks/BACKEND.md) before proposing that split.
  `server/main.py` is the composition root only: app object, middleware, `auth_gate`,
  health/refresh/cron, PostHog proxy, StaticFiles mount (last). It re-exports symbols tests and
  `scripts/audit_ledger.py` import from it (`_cache`, `ticker_ledger`, `NwValueIn`,
  `performance`); those live in `server/routes/`, not in `main.py`. `_is_spending` is defined
  in `server/main.py`. A handler's monkeypatched dependency (e.g. `perf_all`, `session_scope`)
  must be patched on the `server.routes.*` module that defines it, not on `server.main`. Lazy
  in-handler imports
  (ruff E402, ignored repo-wide) break real import cycles, not accidental ones.
- **Tests share scaffolding; don't re-copy it.** [tests/conftest.py](tests/conftest.py) restores
  `settings` after every test and provides `client` (gate bypassed), `owner_client` (real
  cookie gate), `auth_settings`, `no_db`; SQLite sessions and the alembic-only
  `current_position` view SQL are in `tests/sqlitetest.py`, Postgres-only SQL goes in
  `tests/*_pg.py` via `tests/pgtest.py`, build/ scripts load via `tests/buildscript.py`.
- **ADR [0001](docs/adr/0001-do-not-unify-twr-and-performance.md): do not unify
  `performance.py` and `twr.py`.** They're deliberately separate engines; they share only
  `portfolio/xirr.py`.
- **One "today": `ingestion.prices.sg_today()` (SGT)** — price rows, the fold and the option
  parser use it. Nullable-field helpers (`num`, `rounded`, `iso`, `nulls_last`) live in
  `portfolio/nullable.py` and SQL→dicts is `db.fetch_dicts`; don't re-spell them per module.
- **`docs/archive/`** holds historical/superseded docs (old plans). **`archive/`** at repo root
  holds retired AIDLC process trees (`aidlc-docs/`, `.aidlc-rule-details/`, `.wayfinder/`) kept
  for history, not live process — do not treat them as the active workflow or documentation
  home. The `SECURITY-NN` codes cited in `server/` are defined in DEPLOY.md § Security
  register; add a line there before citing a new one.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
