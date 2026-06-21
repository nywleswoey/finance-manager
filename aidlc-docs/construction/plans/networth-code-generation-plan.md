# Code Generation Plan — networth (single source of truth)

Brownfield. Modify existing files in-place; create new ones where noted. Workspace root: `/Users/selwynyeow/personal/portofolio`. Alembic head: `a1f2c3d4e5f6`.

## Unit context
- **Unit**: networth
- **Owns entities**: `nw_item`, `nw_snapshot`, `nw_value`
- **Depends on**: `fx_rate` (read), `portfolio.performance.compute` (live value), `portfolio.db`
- **Interfaces**: REST under `/api/networth/*`; React nav section "Net Worth"

## Steps

### Step 1 — Models (backend) [ ]
- **Modify** `portfolio/models.py`: add `NwItem`, `NwSnapshot`, `NwValue` (per domain-entities.md). Reuse `MONEY`, `RATE`, `Base`. CheckConstraint kind in (asset,liability); unique snapshot.date; unique(snapshot_id,item_id); cascade delete.

### Step 2 — Migration [ ]
- **Create** `migrations/versions/<rev>_networth.py`, `down_revision='a1f2c3d4e5f6'`. `upgrade()` creates 3 tables; `downgrade()` drops them (reverse order).

### Step 3 — Catalogue seed [ ]
- **Create** `scripts/seed_networth.py`: idempotent upsert of the 14 catalogue items (code/label/kind/ccy/flags/sort_order) by `code`. Wire into Makefile if a `seed` target exists.

### Step 4 — Business logic [ ]
- **Create** `portfolio/networth.py`:
  - `live_portfolio_sgd(s)` → Σ mv_sgd from `performance.compute` (open positions).
  - `rate_for(s, ccy, on_date)` → 1 if SGD else latest `fx_rate ≤ date`; raise ValueError if none (BR4).
  - `create_snapshot(date, values, note)` → freeze portfolio value + per-line fx/value_sgd; persist; BR1 reject duplicate date; BR2 default missing items to 0.
  - `metrics(snapshot)` → the 6 figures + portfolio_value_sgd (business-logic-model.md formulas).
  - `list_snapshots()`, `get_snapshot(id)`, `latest()`, `catalogue()`.

### Step 5 — API layer [ ]
- **Modify** `api/main.py`: add routes
  - `GET /api/networth/items`
  - `GET /api/networth/snapshots`
  - `GET /api/networth/latest`
  - `GET /api/networth/snapshots/{id}`
  - `POST /api/networth/snapshots` (JSON body)
  - `DELETE /api/networth/snapshots/{id}`
  - Pydantic body model for create. Map ValueError → HTTP 400/409.

### Step 6 — Frontend [ ]
- **Modify** `web/src/api.js`: extend `post` to accept optional JSON body; add `del(path)`.
- **Create** `web/src/modules/networth/NetWorth.jsx`: SummaryCards (6 metrics) + trend chart (recharts) + create-snapshot form (prefilled from latest) + history table. `data-testid` on interactive elements.
- **Modify** `web/src/App.jsx`: add `section` state; make left-nav "Net Worth" clickable; render `<NetWorth/>` for that section, Portfolio tabs otherwise.
- **Modify** `web/src/styles.css` if needed for cards/form (reuse existing classes first).

### Step 7 — Tests [ ]
- **Create** `tests/test_networth.py`: metric math (the 6 formulas incl. housing/cpf exclusions), fx conversion (SGD=1, HKD/USD convert), BR4 missing-rate raises, BR1 duplicate-date reject. Use a throwaway in-memory/SQLite or seeded fixtures where feasible; otherwise pure-function metric tests on a constructed snapshot.

### Step 8 — Code summary doc [ ]
- **Create** `aidlc-docs/construction/networth/code/summary.md`: list created/modified files, endpoints, how to migrate+seed+run.

## Story traceability
Single unit covers all of FR1–FR7. No external unit deps.

## Scope
8 steps. ~3 new backend files, 2 modified backend files, 1 migration, 2 new + 3 modified frontend files, 1 test file.
