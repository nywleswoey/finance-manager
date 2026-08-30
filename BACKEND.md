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

- Rewrite parsers to write **directly** to the DB + record `import_batch` per file —
  currently we load the pre-built `ledger.csv`/`dividends.csv` as the bridge.
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
into the cash-bucket position. Positions still come from the authoritative
CDP statements; `alloc_by_account()` gives the per-account MV split for charts.

CDP cost is matched at **position** level, not per row — a CDP `txn` row is a month-end
statement diff that routinely aggregates several trade-dated cost lots, and matching per row
invents shortfalls that do not exist. `performance.cost_partition` carries the detail.

## Cost truth is a partition of units

A boolean cannot say the thing that is actually true of Q01: *17,000 of its 68,000 units
entered with no recorded cost*. So every entering unit lands in exactly one of three
conditions, computed after the corporate-action carry and the switch rebasing run and shipped
as a nested `cost_partition` on every position row:

```json
"cost_partition": { "units_in": 68000, "costed": 51000, "free": 0,
                    "unknown": 17000, "unknown_pct": 0.25 }
```

The three **sum to gross units in** on every position — 73 of 73 in the live book, which totals
1,574,652 units in: 1,521,274 costed, 545 free, 52,833 unknown. Nested so the counts cannot
drift apart among ~25 flat siblings and the self-check is visible in one place.
`tests/test_performance_live.py` holds those figures to the ledger they were measured against.

- **A carried unit is `costed`** — its cost is known, it just came from a predecessor (9CI's
  2,700 from C31). Likewise a transfer in whose paired transfer out sits in the same position:
  the cost never left.
- **`free` units carry a price, not only a count** — `cost_basis = 0.0`, never `null`. They
  enter `buy_qty` at zero cost, which is what makes AAPL's basis a *measured* zero (and stops
  D05's 280 bonus shares inflating its cost basis past what was ever invested).
- **The action string cannot decide free from transferred.** Every unpriced carry-in is
  `open/transfer_in` on one account, covering a landed corporate-action carry, a real in-specie
  distribution and two windfalls. That distinction lives in a per-transaction annotation
  (`portfolio/cost_annotations.py`) defaulting to `unknown` — refuse rather than invent a free
  lot. `gifted stock in` and `bonus issuance` are mechanical and need no annotation.
- **`cost_known` is the partition read as a boolean**: false only when *every* entering unit is
  unknown. Not `unknown == 0`, which would flip C38U to false and delete its 7,756.75 Net.
  Live, the refusal set is ASTREA6B alone; the caveat set is S51 40.0%, SET 27.9%, Q01 25.0%,
  C38U 7.5%.
