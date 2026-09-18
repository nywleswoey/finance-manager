# Requirements — Net-Worth Snapshot

## Intent Analysis
- **User request**: Maintain a dated snapshot of manual assets & liabilities, combine with the live investment portfolio value, and compute net-worth metrics.
- **Request type**: New Feature (Enhancement of existing portfolio app)
- **Scope estimate**: Multiple Components — new DB table(s) + migration, domain compute, API endpoints, web UI page.
- **Complexity estimate**: Moderate.
- **Depth**: Standard.

## Context (brownfield)
- Existing app: FastAPI (`api/`), domain (`portfolio/`), SQLAlchemy 2.0 + Alembic + Postgres, web UI (`web/`).
- Live portfolio value already available via `GET /api/overview` → `market_value_sgd` (SGD).
- FX rates available in `fx_rate(date, currency, rate_to_sgd)`.

## Manual line items (fixed list of 14)
Each item has a **kind** (asset/liability), a **native value + currency**, and **tags** for grouping.

| # | Item | Kind | Native ccy (typical) | Liquid | Housing | CPF |
|---|------|------|------|:--:|:--:|:--:|
| 1 | POSB shared account | asset | SGD | ✓ | | |
| 2 | DBS Multiplier | asset | SGD | ✓ | | |
| 3 | SRS account | asset | SGD | | | |
| 4 | Tiger HKD (cash) | asset | HKD | ✓ | | |
| 5 | Tiger SGD (cash) | asset | SGD | ✓ | | |
| 6 | Tiger USD (cash) | asset | USD | ✓ | | |
| 7 | Tiger Vault | asset | SGD | ✓ | | |
| 8 | IBKR SGD (cash) | asset | SGD | ✓ | | |
| 9 | CPF OA | asset | SGD | | | ✓ |
| 10 | CPF SA | asset | SGD | | | ✓ |
| 11 | CPF MA | asset | SGD | | | ✓ |
| 12 | Tampines HDB | asset | SGD | | ✓ | |
| 13 | CPF Home Loan | liability | SGD | | ✓ | |
| 14 | CPF Home Loan Accrued Interest | liability | SGD | | ✓ | |
| 15 | Investment portfolio (LIVE, not stored) | asset | SGD | | | |

Notes:
- Items 4–8 are **cash balances only**; invested positions come live (item 15) — **no overlap / no double-count** (Q2=A).
- Item 15 value is pulled live from `/api/overview.market_value_sgd`; it is **not** a stored manual item.
- Liquid set excludes SRS, CPF, HDB, and the live portfolio (Q4 = A,B,D,E,F).

## Functional Requirements
- **FR1 — Dated snapshots (Q1=A)**: Net worth is captured as dated snapshots. User creates a new snapshot (a set of line-item values on a date). History is retained; trends over time are viewable.
- **FR2 — Native currency + FX (Q3=A)**: Each line item stores a native value + currency. SGD value = native × `rate_to_sgd` (latest rate ≤ snapshot date; SGD = 1).
- **FR3 — Live portfolio inclusion**: When computing a snapshot's totals, include live investment portfolio value (`market_value_sgd`). Stored on the snapshot at capture time so historical snapshots stay stable.
- **FR4 — Metrics** (all in SGD):
  - **Total assets** = Σ asset line items (SGD) + live portfolio value.
  - **Total liabilities** = Σ liability line items (SGD). (items 13, 14)
  - **Liquid assets** = Σ items tagged liquid = POSB + DBS + Tiger HKD/SGD/USD + Tiger Vault + IBKR (items 1,2,4,5,6,7,8).
  - **Net worth** = Total assets − Total liabilities.
  - **Net worth excl. housing** = Net worth − (HDB asset) + (home-loan + accrued-interest liabilities). I.e. remove all housing-tagged items (12,13,14) from both sides.
  - **Net worth excl. housing & CPF** = Net worth excl. housing, additionally removing CPF-tagged assets (OA/SA/MA = items 9,10,11).
- **FR5 — Accrued interest is a liability (Q6=A)**: Item 14 reduces net worth; excluded together with housing in the housing-exclusion metric.
- **FR6 — Edit via web UI (Q7=A)**: New page/section in `web/` with a form to enter/edit the 14 line-item native values + currencies for a snapshot, plus a summary panel showing the 6 metrics. Create-new-snapshot and view-history supported.
- **FR7 — Fixed catalogue (Q8=A)**: The 14 items are a fixed, seeded catalogue (no user add/remove in UI). Tags (kind/liquid/housing/cpf) are item properties.

## Net-worth metric definitions (precise)
Let `A` = Σ asset items SGD, `L` = Σ liability items SGD, `P` = live portfolio SGD.
- total_assets = A + P
- total_liabilities = L
- liquid = Σ liquid-tagged items SGD
- net_worth = (A + P) − L
- net_worth_excl_housing = net_worth − Σ(housing assets) + Σ(housing liabilities)
  = net_worth − HDB + (home_loan + accrued_interest)
- net_worth_excl_housing_cpf = net_worth_excl_housing − Σ(CPF assets)
  = net_worth_excl_housing − (OA + SA + MA)

## Non-Functional Requirements
- **NFR1**: Reuse existing stack — SQLAlchemy model + Alembic migration, FastAPI endpoint(s), existing FX table. No new infra.
- **NFR2**: Money as Numeric/Decimal (match existing `MONEY = Numeric(20,4)`); no float drift in stored values.
- **NFR3**: Historical snapshots immutable in computed totals — store live portfolio value + FX-converted SGD at capture so past snapshots don't change when prices move.
- **NFR4**: Single-user personal app; no auth/security extension (Q9=B).
- **NFR5**: Testing — standard unit tests for metric math; PBT not enforced (Q10=C).

## Extensions
- Security Baseline: **Disabled** (Q9=B).
- Property-Based Testing: **Disabled** (Q10=C).

## Open / assumed
- "Latest FX rate ≤ snapshot date" assumed for conversion; if no rate exists for a currency, error/flag rather than assume 1.
- HDB value and CPF balances are user-entered manually (no live source).
