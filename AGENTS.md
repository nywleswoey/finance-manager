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
  move `migrations/` or `portfolio.models`.
- **`make ingest-all`** delta-ingests every source (brokers, spending, prices, net-worth
  snapshots); idempotent. See the README table for per-source commands.
- **Frontend is already split by product**: `web/src/modules/{portfolio,networth,spending}/`.
  Backend is not (one `portfolio/` package, one `server/main.py` with 51 routes) — see
  [docs/runbooks/BACKEND.md](docs/runbooks/BACKEND.md) before proposing a backend split;
  `server/main.py`'s lazy in-handler imports break real import cycles, not accidental ones.
- **ADR [0001](docs/adr/0001-do-not-unify-twr-and-performance.md): do not unify
  `performance.py` and `twr.py`.** They're deliberately separate engines.
- **`docs/archive/`** holds historical/superseded docs (old plans). **`archive/`** at repo root
  holds retired AIDLC process trees (`aidlc-docs/`, `.aidlc-rule-details/`, `.wayfinder/`) kept
  for history, not live process — do not treat them as the active workflow or documentation
  home.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
