# Backend — Phase 0/1 (DB foundation + load)

Implements [PLAN.md](PLAN.md) Phase 0 (Postgres + schema + seed) and the first half of
Phase 1 (load the existing `build/*.csv` into the DB, idempotently).

## Stack in place

- **Postgres 16** via `docker-compose.yml` (host port **5544**).
- **SQLAlchemy 2.0** models (`portfolio/models.py`) + **Alembic** migrations (`migrations/`).
- **Seed** (`scripts/seed.py`): accounts, securities, aliases, corporate actions.
- **Loader** (`ingestion/load.py`): `build/ledger.csv` + `build/dividends.csv` → `txn` / `dividend`.

## Quick start

```bash
uv venv .venv && uv pip install --python .venv/bin/python \
    sqlalchemy alembic "psycopg[binary]" pydantic-settings python-dotenv
cp .env.example .env
make refresh        # db-up + migrate + seed + load   (idempotent)
make psql           # poke around
```

## What's in the DB now

| Table | Rows | Notes |
|---|---|---|
| `account` | 7 | Tiger Prime/Cash Boost, Moomoo, FSM, CDP, CPF, SRS (with funding_bucket) |
| `security` | 79 | canonical ticker + name + market + asset_type + currency |
| `security_alias` | 197 | every name/code variant → security (from `symbols.csv`) |
| `corporate_action` | 4 | CWBU→SET rename, S51→5E2 20:1, C31→9CI/C38U split |
| `txn` | 525 | all share-affecting events (stocks + Amundi fund) |
| `dividend` | 485 | cash dividends, all sources |

Views: `current_position` (units per account+security), `dividend_summary` (by
bucket/market/currency). Verified vs Holdings — e.g. SRS UD1U = 222,205, Tiger HK all match.

## Idempotency

Each row gets a `dedup_hash` = `sha256(account, ticker, date, action, qty, amount, occurrence)`.
The **occurrence** counter (nth identical row within a file) keeps two genuinely-identical
lots distinct (e.g. the two `2-Sep-20 UD1U 11100` SRS buys) while re-ingesting the same
file inserts nothing new (`ON CONFLICT (dedup_hash) DO NOTHING`).

## Next (rest of Phase 1 → Phase 4)

- Rewrite parsers to write **directly** to the DB + record `import_batch` per file, and add
  the **reconciliation gate** (replay vs `position_snapshot`) — currently we load the
  pre-built `ledger.csv`/`dividends.csv` as the bridge.
- Load `position_snapshot` from statement holdings tables (Moomoo/CDP/Endowus parsers
  already produce these).
- Phase 3: `price` + `fx_rate` loaders (yfinance + statement NAVs).
- Phase 4: performance engine (avg cost, valuation, XIRR + TWR, dividends) as SQL views +
  a thin Python layer.

## Cost basis sources

Performance is computed **per funding bucket × security** (not per account): transfers
within the cash bucket (CDP→FSM) don't change ownership, so a position moved into FSM
keeps its original CDP purchase cost. CDP cost (which the CDP statements omit) is taken
from `data/cdp-stocks/transactions.csv` via `portfolio/performance.cdp_cost()` and pooled
into the cash-bucket position. Positions/reconciliation still come from the authoritative
CDP statements; `alloc_by_account()` gives the per-account MV split for charts.

Result: **31/37** bucket-positions have a known cost basis (XIRR + P/L) — incl. the
FSM-transferred D05 / O5RU / UD1U. The remaining 6 are the Amundi fund (Endowus units, no
unit price stored) and Moomoo 9CI/C38U/HMN (free shares from the 2021 CapitaLand
restructuring — no purchase price).
