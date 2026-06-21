# Portfolio Platform

Personal investment-portfolio system: ingests broker statements → Postgres → performance
analytics (incl. dividends) → a modular web app. Portfolio is the first module of a larger
personal app. Built per [PLAN.md](PLAN.md).

```
statements (data/) ──▶ parsers (build/, ingestion/) ──▶ Postgres ──▶ FastAPI ──▶ React app
   csv + pdf            normalize + reconcile          txn/dividend   /api/*       web/
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

## What it does

- **Ingestion** — Tiger / Moomoo / FSM / CDP / Endowus statements (CSV + PDF) →
  normalized `txn` + `dividend`, idempotent (`dedup_hash`), securities resolved through an
  alias table. Renamed counters (CWBU→SET) and splits (S51→5E2 20:1) modelled as
  corporate actions.
- **Reconciliation** — replayed DB positions checked against `Holdings.md`
  (`/api/reconciliation`): 37 reconcile, 6 closed inter-broker transfers, 1 pending statement.
- **Performance** — per security in native currency, rolled up to market / account / bucket /
  total in SGD: market value, dividend income, P/L (where cost is known), per-position XIRR,
  and a portfolio **money-weighted return** (historical-FX XIRR).
- **App** (`web/`) — Overview (tiles + allocation donuts), Holdings, Performance, Dividends,
  Transactions, Reconciliation. Modular shell so other modules (Net Worth, Budget…) slot in.

## Layout

| Path | What |
|---|---|
| `data/` | raw statements (immutable) |
| `build/` | statement parsers → `ledger.csv`, `dividends.csv`, `symbols.csv` |
| `ingestion/` | DB loaders (`load.py`) + market data (`prices.py`) |
| `portfolio/` | models, db, `performance.py`, `twr.py`, `reconcile.py` |
| `migrations/` | Alembic schema |
| `scripts/seed.py` | reference-data seed |
| `api/` | FastAPI |
| `web/` | React (Vite) app |

## Status

Phases 0–6 of PLAN.md implemented and verified end-to-end (DB, ingestion, prices/FX,
performance, API, frontend). See [BACKEND.md](BACKEND.md). Known limitations: CDP-origin
positions carry no transaction cost (statements lack amounts) so their P/L/XIRR is shown as
n/a; true time-weighted return (TWR) needs a daily price-history backfill (money-weighted
XIRR is implemented). Next: direct-to-DB parsers + `import_batch` per file, historical
prices for TWR, scheduled ingest.
```
