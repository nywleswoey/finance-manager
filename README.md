# finance-manager

Personal investment-portfolio + net-worth + spending platform: ingests broker statements →
Postgres → performance analytics (incl. dividends) → a modular web app. Portfolio is the first
module of a larger personal app. Built per [docs/archive/PLAN.md](docs/archive/PLAN.md)
(historical).

```
statements (data/) ──▶ parsers (build/, ingestion/) ──▶ Postgres ──▶ FastAPI ──▶ React app
   csv + pdf            normalize                      txn/dividend   /api/*       web/
                                                       price/fx
```

## Run it

```bash
# deps (once)
uv venv .venv && uv pip install --python .venv/bin/python \
  sqlalchemy alembic "psycopg[binary]" pydantic-settings python-dotenv fastapi uvicorn
cp .env.example .env

make setup     # db + schema + seed + ingest statements + fetch prices/FX (local docker DB)
make build-web && make api-local   # serve the docker DB on http://localhost:8001
```

`make api` / `make app` (:8000) instead serve the **deployed** Neon DB, read from `.env.local`
(`vercel env pull`) — they fail without it. Those servers can write to it (refresh, snapshot
delete, spending classify), so treat them as prod. `api-local` serves its own built `web/dist`;
the vite dev server proxies to :8000, so it does not work with `api-local`.
Running both ports side by side shares one session cookie (cookies are not port-scoped), so logging
out of one logs out the other. `make capture-web-fixtures` reads `api-local` (:8001), never `api`.

Individual steps: `make db-up migrate seed ingest prices` · `make psql` · `make api-local`.

## Ingesting new data files

Drop new statements into their `data/` folders, then **`make ingest-all`** — one command that
delta-ingests every source (brokers + spending + prices + net-worth snapshots). All loaders are
idempotent (dedup by hash / duplicate-date skip), so it's safe to re-run and only net-new data
lands. Per-source commands below if you want to run just one pipeline.

| New file in… | Command | What it does |
|---|---|---|
| `data/` broker statements (Tiger / Moomoo / FSM / CDP / Endowus) | `make ingest` | re-parse → `txn` + `dividend` (only net-new rows land) |
| `data/*-cc`, bank/card statements | `make spending` | parse → classify → spending ledger |
| — (market data) | `make prices` | refresh latest prices + FX (needs network) |
| `data/dbs-consolidated-statements/dbs_YYYYMM.pdf` (+ latest `data/tiger-prime/`) | `make snapshot` → `make snapshot-commit` | preview, then write a net-worth snapshot for the one DBS month newer than the latest one (month-end dated); refuses a multi-month or stale catch-up |

Unattended, against the **deployed** database: `make schedule-install` loads a launchd agent
that runs `make ingest-all` daily at 06:15, plus a Vercel Cron that refreshes prices in the
cloud on the days this machine is off. Dropping the statement in its folder is still yours to
do; parsing it the next morning is not. See
[DEPLOY.md §6](DEPLOY.md#6-keeping-the-deployed-data-fresh-schedules).

One-off / backdated net-worth snapshot for a specific month:

```bash
PYTHONPATH=. .venv/bin/python scripts/snapshot_from_statements.py --dbs 202606 --date 2026-06-30            # dry-run
PYTHONPATH=. .venv/bin/python scripts/snapshot_from_statements.py --dbs 202606 --date 2026-06-30 --commit  # write
```

## What it does

- **Ingestion** — Tiger / Moomoo / FSM / CDP / Endowus statements (CSV + PDF) →
  normalized `txn` + `dividend`, idempotent (`dedup_hash`), securities resolved through an
  alias table. Renamed counters (CWBU→SET) and splits (S51→5E2 20:1) modelled as
  corporate actions.
- **Performance** — per security in native currency, rolled up to market / account / bucket /
  total in SGD: market value, dividend income, P/L (where cost is known), per-position XIRR,
  and a portfolio **money-weighted return** (historical-FX XIRR).
- **Options** — realized return from the sold-option (wheel) book: `option_trade` table loaded
  by `ingestion/parse_options.py` from Tiger flex Activity Statements (`data/tiger-prime/*.csv`,
  `data/tiger-cash-boost/*.csv`) and the reconciled IBKR export (`data/ibkr-options/options.csv`);
  analytics in `portfolio/options.py` (realized P/L, premium collected, win-rate, by
  year/ticker/type, SGD at latest FX). API `/api/options`, `/api/options-trades`.
- **Net-worth snapshots** — dated manual assets/liabilities + frozen live portfolio value →
  net worth (and excl-housing / excl-housing-&-CPF) via `portfolio/networth.py`. Built from
  broker/bank statements by `scripts/snapshot_from_statements.py` (Tiger Prime CSV cash +
  MMF, DBS consolidated PDF Multiplier + SRS cash; other items carried forward; FX
  auto-backfilled). Dry-run by default; `--commit` writes; `--all-new --commit` ingests
  one new DBS month (month-end dated) and refuses a catch-up that would stamp the run-day
  portfolio and newest Tiger cash onto an older month. The snapshot note records the
  portfolio valuation date and the Tiger file.
- **App** (`web/`) — three modules behind a shared shell: **Portfolio** (Overview with tiles +
  allocation donuts, Holdings, Performance, Dividends, Options, Transactions), **Net Worth**
  (snapshots + trend), and **Spending** (Overview, By Category, Classify, Recurring,
  Transactions). Spending is gated per-user server-side; the shell keeps room for further modules.

## Layout

| Path | What |
|---|---|
| `data/` | raw statements (immutable) |
| `build/` | statement parsers → `ledger.csv`, `dividends.csv`, `symbols.csv` |
| `ingestion/` | DB loaders (`load.py`) + market data (`prices.py`) + options (`parse_options.py`) |
| `portfolio/` | models, db, config, money (shared kernel); `performance.py`, `twr.py`, `dividends.py`, `options.py` (portfolio); `networth.py` (net worth); `spending.py`, `classify.py`, `recurring.py`, `spend_categories.py` (spending) |
| `migrations/` | Alembic schema |
| `scripts/seed.py` | reference-data seed |
| `scripts/snapshot_from_statements.py` | net-worth snapshot from statements (`--all-new` delta) |
| `server/` | FastAPI app: `main.py` — composition root (middleware, auth gate, health/refresh/cron, PostHog proxy, built SPA); `routes/{portfolio,networth,spending}.py` — `/api/*` handlers per product module; `auth.py` — Google OAuth router |
| `api/index.py` | Vercel entrypoint — re-exports `server.main:app` |
| `web/` | React (Vite) app; `web/src/modules/{portfolio,networth,spending}/` — the three product modules |

## Status

Phases 0–6 of [PLAN.md](docs/archive/PLAN.md) implemented and verified end-to-end (DB, ingestion, prices/FX,
performance, API, frontend). Both returns are implemented: money-weighted XIRR and
time-weighted return (`portfolio/twr.py`, served by `/api/return`). Known limitation: some
units entered the book without a recorded cost, so P/L and XIRR speak only for the units whose
cost is known — every position carries a `cost_partition` (costed / free / unknown) saying how
much of it that is. [docs/runbooks/BACKEND.md](docs/runbooks/BACKEND.md) owns the cost-basis
rules, including where CDP cost comes from and when it attaches. Next: direct-to-DB parsers +
`import_batch` per file, scheduled ingest.
