# Portfolio Platform — Build Plan

Turn the current scripts + flat files into a **persistent, queryable, performance-aware
portfolio system** with a periodic ingestion pipeline and a modular web app (portfolio =
first module of a larger personal app).

## Where we are

- Parsers in `build/` already normalize every source → a unified event schema
  (`ledger.csv`, 1700 rows): `build_ledger.py` (Tiger flex, FSM/iFast, CDP/CPF/SRS CSVs,
  gifts), `parse_moomoo.py`, `parse_cdp.py`, `parse_endowus.py` (PDF snapshot-diff).
- `symbols.csv` = canonical alias master. Reconciliation logic replays positions vs
  `Holdings.md` and is **green** (only MSFT 100 pending a statement).
- These become the **ingestion + reference layer** of the new system — not thrown away.

## Recommended stack (swap points noted)

| Layer | Choice | Why |
|---|---|---|
| DB | **PostgreSQL 16** (Docker locally → Neon/Supabase later) | goal #1; strong SQL for analytics, window funcs |
| Backend | **Python 3.12 + FastAPI** | reuse the existing parsers verbatim; great for ETL + analytics |
| ORM / migrations | **SQLAlchemy 2.0 + Alembic** | typed models, versioned schema |
| Market data | **yfinance** (US `AAPL`, HK `0700.HK`, SG `D05.SI`), fund NAVs from statements, **MAS/exchangerate** for FX | free, covers everything held |
| Frontend | **Next.js 15 (App Router) + TypeScript + TanStack Query + Recharts** | "proper app", module-friendly, good charting |
| Auth (later) | Clerk/Auth.js | single-user now, multi-module app later |
| Infra | Docker Compose (db + api + web) | one-command local; lift to cloud unchanged |

Repo layout (monorepo):

```
portofolio/
├── data/                      # raw statements (unchanged, immutable)
├── db/                        # alembic migrations, seed
├── ingestion/                 # parsers refactored into a package (from build/)
│   ├── sources/  (tiger.py, fsm.py, cdp.py, moomoo.py, endowus.py, simple_csv.py)
│   ├── normalize.py  reconcile.py  pipeline.py
│   └── symbols.csv  corporate_actions.yaml
├── api/                       # FastAPI app (analytics endpoints)
│   └── performance/  (cost_basis.py, valuation.py, returns.py, dividends.py)
├── web/                       # Next.js app shell + modules/portfolio
├── docker-compose.yml
└── build/                     # legacy scripts (kept until ingestion/ replaces them)
```

---

## Database schema (core)

Idempotent, provenance-tracked, multi-currency. DDL sketch:

```sql
-- reference -------------------------------------------------------------
account(id, name, broker, funding_bucket /*cash|cpf|srs*/, base_currency, opened, closed)

security(id, canonical_ticker UNIQUE, name, market /*US|HK|SG*/, asset_type /*stock|fund|reit|etf|bond*/,
         currency, isin, active)
security_alias(security_id, alias /*code or name*/, source)            -- from symbols.csv
corporate_action(id, security_id, date, type /*rename|split|consolidation|merger*/,
                 from_ticker, to_ticker, ratio_num, ratio_den, notes)  -- CWBU→SET, S51→5E2 20:1, C31→9CI+C38U

-- the ledger ------------------------------------------------------------
import_batch(id, source, filename, file_hash, imported_at, rows_in, rows_new, status)
txn(id, account_id, security_id, trade_date, settle_date,
    action /*buy|sell|gift_in|rights|bonus|scrip|corp_action|transfer_in|transfer_out|fee|subscription*/,
    qty_signed NUMERIC(20,8), price NUMERIC, gross_amount NUMERIC, fees NUMERIC, currency,
    funding_bucket, source_file, raw, batch_id,
    dedup_hash UNIQUE)                                                  -- idempotent re-ingest

dividend(id, account_id, security_id, ex_date, pay_date, kind /*cash|scrip*/,
         amount_per_unit, units, gross, withholding_tax, net, currency, source_file, dedup_hash UNIQUE)

-- valuation / reconciliation -------------------------------------------
price(security_id, date, close, currency, source)                      -- daily; PK(security_id,date)
fx_rate(date, currency, rate_to_sgd)                                   -- PK(date,currency)
position_snapshot(account_id, security_id, date, units, market_value, source)  -- from statement holdings tables
```

Key rules (carried over from the reconciliation work):
- **One security, many aliases.** `security_alias` resolves every name/code variant
  (AIMSAMP CAP REIT = AIMS APAC REIT = O5RU) to one `security`.
- **Corporate actions are first-class** so renames stay continuous and splits/consolidations
  carry a ratio (S51→5E2 is 20:1, so quantities are *not* summed naively).
- **`dedup_hash`** = hash(account, security, date, action, qty, amount) → re-ingesting a
  statement that overlaps an old one inserts nothing new.
- **Inter-broker transfers** keep a `transfer_group` so CDP→FSM moves net out (already solved
  in the viewer — port that logic to a SQL view).

---

## Performance engine (goals #2, #3)

All returns computed in **SGD base** (convert via `fx_rate`). Per security → roll up to
market → account → funding-bucket → total via simple GROUP BY.

1. **Cost basis** — average cost (default) per (account, security); track realized P/L on
   sells. (FIFO optional later.) Gifts enter at market value on receipt date.
2. **Valuation** — `units × price(date) × fx(date)`. Funds use NAV from statements/Endowus.
3. **Income** — sum `dividend.net` (+ scrip reinvested as shares). This is what makes it
   *total* return, not just price.
4. **Returns**, two complementary numbers:
   - **XIRR (money-weighted)** — your personal annualised return. Cashflows = buys (−),
     sells (+), dividends (+), current value (+). One `scipy`/Newton solve per scope.
   - **TWR (time-weighted)** — geometric link of daily sub-period returns; strips out
     deposit timing, so it's comparable to an index benchmark.
   - **Total/unrealised/realised P/L** and **yield-on-cost** as headline tiles.
5. **Time series** — daily portfolio value + cumulative dividends, materialised into a
   `daily_position` table (units forward-filled × price × fx) for fast charts.

Exposed as SQL views + a thin Python layer; cached.

---

## Ingestion pipeline (goal #4)

```
new statement file ─▶ detect (file_hash unseen) ─▶ source parser ─▶ normalized rows
   ─▶ resolve security via security_alias / apply corporate_action
   ─▶ upsert txn/dividend ON CONFLICT(dedup_hash) DO NOTHING   (idempotent)
   ─▶ record import_batch
   ─▶ RECONCILE: replay positions vs latest position_snapshot  ─▶ flag mismatches
   ─▶ refresh prices/fx for held securities ─▶ rebuild daily_position
```

- **Trigger**: `python -m ingestion.pipeline --path data/` (manual now) → cron / a
  `make ingest` → later a watch on the `data/` folders or an upload endpoint.
- **Safe re-runs**: same files = no-op (dedup_hash). New month = only new rows.
- **Reconciliation gate**: pipeline fails loud if replayed units ≠ statement snapshot
  (reuses today's logic), so silent gaps can't creep in.
- **Dividends + corporate actions** parsed from the sections we currently skip (Tiger
  `Dividends`, CDP `Summary of Payments`, FSM cash dividends, Endowus distributions).

---

## API surface (FastAPI)

```
GET /accounts, /securities, /positions?as_of=
GET /performance?scope=security|market|account|bucket|total&from=&to=
GET /performance/{security_id}/timeseries
GET /dividends?from=&to=&group_by=
GET /transactions?account=&security=         (the ledger, paginated)
GET /reconciliation                          (replayed vs snapshot/Holdings)
POST /ingest                                  (upload/trigger a statement)
```

---

## Frontend (modular app)

Next.js **app shell** (sidebar of modules) with the first module `modules/portfolio`:
- **Overview** — total value, total return (XIRR + TWR), P/L, dividends YTD, allocation
  donut (market / account / bucket).
- **Holdings** — sortable table, per-row return + yield-on-cost; reuse current grouping
  (bucket → market → security).
- **Security detail** — price + cost-basis chart, transaction timeline & running balance
  (port the existing viewer), dividend history.
- **Performance** — value/return-over-time chart, benchmark overlay, per-period table.
- **Reconciliation** — current vs statement, flagged diffs.

The existing `portfolio.html` is the throwaway prototype this module replaces; its grouping
+ transfer-netting + naming logic moves into API/SQL.

---

## Roadmap (phased, each phase shippable)

| Phase | Deliverable | Builds on |
|---|---|---|
| **0 — DB foundation** ✅ DONE | Docker Compose (postgres:16 @5544), SQLAlchemy models + Alembic schema, seed accounts/securities/aliases/corporate-actions. See [BACKEND.md](BACKEND.md). | symbols.csv |
| **1 — Ingestion** 🟡 in progress | ✅ `ingestion/load.py` loads `ledger.csv`+`dividends.csv` into `txn`/`dividend` idempotently (525 txns, 485 divs, occurrence-scoped dedup). ⬜ rewrite parsers to write direct + `import_batch` per file + reconciliation gate vs `position_snapshot` | all parsers |
| **2 — Dividends + corp actions** ✅ | `build/parse_dividends.py` (485 rows) loaded; corporate_action seeded | Tiger/CDP/FSM sections |
| **3 — Market data** 🟡 | ✅ `ingestion/prices.py` — latest price (Yahoo) + Endowus NAV + FX → DB. ⬜ daily history for TWR | securities table |
| **4 — Performance engine** ✅ | `portfolio/performance.py` (per-security native + SGD rollups, P/L, per-position XIRR) + `twr.py` (portfolio money-weighted return). TWR-proper needs daily history | phases 2–3 |
| **5 — API** ✅ | `api/main.py` FastAPI: overview/positions/performance/dividends/transactions/return/reconciliation | phase 4 |
| **6 — Frontend** ✅ | `web/` React (Vite) modular app: Overview/Holdings/Performance/Dividends/Transactions/Reconciliation, served by FastAPI | phase 5 |
| **7 — Automation** 🟡 | ✅ `make ingest` / `make setup` pipeline. ⬜ scheduled trigger + upload endpoint + mismatch alerts | phase 1 |

**Suggested first cut (MVP):** Phases 0–1 + a minimal Phase 4 (current value + simple
return using latest statement prices, no daily series) + Phase 6 overview/holdings. That
already beats the static HTML and persists everything. Layer XIRR/TWR, charts, and
automation after.

## Decisions (locked 2026-06-21)

1. **Hosting** — **Local Docker now**, lift to Neon/Supabase + Vercel at Phase 6.
2. **Return headline** — **Both**: XIRR (money-weighted) as the hero tile + TWR (time-weighted) for benchmarking.
3. **Cost basis** — **Average cost** (FIFO can be added later).
4. **Price granularity** — daily for held names (enables TWR + charts).
5. **Status** — plan approved; **implementation deferred** (not building Phase 0 yet).
