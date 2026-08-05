# Portfolio Platform

Personal investment-portfolio system: ingests broker statements → Postgres → performance
analytics (incl. dividends) → a modular web app. Portfolio is the first module of a larger
personal app. Built per [PLAN.md](PLAN.md).

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

make setup     # db + schema + seed + ingest statements + fetch prices/FX
make app       # build frontend + serve everything on http://localhost:8000
```

Individual steps: `make db-up migrate seed ingest prices` · `make psql` · `make api`.

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
| `data/dbs-consolidated-statements/dbs_YYYYMM.pdf` (+ latest `data/tiger-prime/`) | `make snapshot` → `make snapshot-commit` | preview, then write a net-worth snapshot per DBS month newer than the latest one (month-end dated) |

Unattended, against the **deployed** database: `make schedule-install` loads two launchd
agents — `make prices` daily 06:15 and `make ingest-all` Sunday 07:00 — plus a Vercel Cron
that refreshes prices in the cloud on the days this machine is off. Dropping the statement in
its folder is still yours to do; parsing it is not. See [DEPLOY.md §6](DEPLOY.md#6-keeping-the-deployed-data-fresh-schedules).

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
  from `data/.archive/tiger-options/options.csv` by `ingestion/parse_options.py`; analytics in
  `portfolio/options.py` (realized P/L, premium collected, win-rate, by year/ticker/type, SGD at
  latest FX). API `/api/options`, `/api/options-trades`.
- **Net-worth snapshots** — dated manual assets/liabilities + frozen live portfolio value →
  net worth (and excl-housing / excl-housing-&-CPF) via `portfolio/networth.py`. Built from
  broker/bank statements by `scripts/snapshot_from_statements.py` (Tiger Prime CSV cash +
  MMF, DBS consolidated PDF Multiplier + SRS cash; other items carried forward; FX
  auto-backfilled). Dry-run by default; `--commit` writes; `--all-new --commit` ingests each
  DBS month newer than the latest snapshot (forward-delta, month-end dated).
- **App** (`web/`) — three modules behind a shared shell: **Portfolio** (Overview with tiles +
  allocation donuts, Holdings, Performance, Dividends, Options, Transactions), **Net Worth**
  (snapshots + trend), and **Spending** (Overview, By Category, Classify, Recurring,
  Transactions). Spending is gated per-user server-side; the shell keeps room for further modules.

## Layout

| Path | What |
|---|---|
| `data/` | raw statements (immutable) |
| `build/` | statement parsers → `ledger.csv`, `dividends.csv`, `symbols.csv` |
| `ingestion/` | DB loaders (`load.py`) + market data (`prices.py`) |
| `portfolio/` | models, db, `performance.py`, `twr.py` |
| `migrations/` | Alembic schema |
| `scripts/seed.py` | reference-data seed |
| `scripts/snapshot_from_statements.py` | net-worth snapshot from statements (`--all-new` delta) |
| `server/` | FastAPI app (`main.py`) — serves `/api/*` and the built SPA |
| `api/index.py` | Vercel entrypoint — re-exports `server.main:app` |
| `web/` | React (Vite) app |

## Status

Phases 0–6 of PLAN.md implemented and verified end-to-end (DB, ingestion, prices/FX,
performance, API, frontend). See [BACKEND.md](BACKEND.md). Known limitations: CDP-origin
positions carry no transaction cost (statements lack amounts) so their P/L/XIRR is shown as
n/a; true time-weighted return (TWR) needs a daily price-history backfill (money-weighted
XIRR is implemented). Next: direct-to-DB parsers + `import_batch` per file, historical
prices for TWR, scheduled ingest.
```
