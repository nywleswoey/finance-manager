# AI-DLC State Tracking

## Project Information
- **Project Type**: Brownfield
- **Start Date**: 2026-06-21T00:00:00Z
- **Current Stage**: INCEPTION - Requirements Analysis

## Workspace State
- **Existing Code**: Yes (Python / FastAPI backend, web frontend, SQLAlchemy + Alembic + Postgres)
- **Programming Languages**: Python, JavaScript/HTML (web/)
- **Build System**: uv (pyproject.toml), alembic migrations
- **Project Structure**: Monolith — `portfolio/` (domain), `api/` (FastAPI), `ingestion/`, `web/` (UI)
- **Reverse Engineering Needed**: Targeted only (relevant subsystems already mapped; full RE deferred by scope)
- **Workspace Root**: /Users/selwynyeow/personal/portofolio

## Code Location Rules
- **Application Code**: Workspace root (NEVER in aidlc-docs/)
- **Documentation**: aidlc-docs/ only

## Feature
Net-worth snapshot: maintain manual assets & liabilities (cash accounts, CPF, HDB, home loan + accrued interest), combine with live investment portfolio value, and answer: total assets, total liabilities, liquid assets, net worth, net worth excl. housing, net worth excl. housing & CPF.

## Extension Configuration
| Extension | Enabled | Decided At |
|---|---|---|
| Security Baseline | Yes | Requirements Analysis (auth unit) |
| Property-Based Testing | No | Requirements Analysis |

## Execution Plan Summary
- **Unit**: networth (single)
- **Execute**: Functional Design, Code Generation, Build and Test
- **Skip**: User Stories, Application Design, Units Generation, NFR Requirements, NFR Design, Infrastructure Design

## Stage Progress
### 🔵 INCEPTION PHASE
- [x] Workspace Detection
- [x] Reverse Engineering (SKIPPED)
- [x] Requirements Analysis
- [x] User Stories (SKIPPED)
- [x] Workflow Planning
- [ ] Application Design (SKIP)
- [ ] Units Generation (SKIP)

### 🟢 CONSTRUCTION PHASE
- [x] Functional Design (EXECUTE)
- [ ] NFR Requirements (SKIP)
- [ ] NFR Design (SKIP)
- [ ] Infrastructure Design (SKIP)
- [x] Code Generation (EXECUTE)
- [x] Build and Test (EXECUTE)

## Units
| Unit | Status |
|---|---|
| networth | Complete (5 snapshots; latest DBS ingest Apr/May/Jun 2026 -> id=3/4/5 month-end dated; scripts/snapshot_from_statements.py) |
| auth | Complete (web build OK). 2026-07-09: added DEV_AUTH_BYPASS local-dev flag — skips Google auth via single chokepoint user_from_request; force-OFF on Vercel (guard: dev_auth_bypass AND NOT env VERCEL); synthetic dev@localhost user; startup warning. 21 auth tests pass (+4 bypass tests). |
| spending-tracker | Code Generation + Verify complete — see construction/spending-tracker/code/summary.md |
| spending-recurring | Complete 2026-07-09 — recurring-spend registry (recurring_spend table, migration e7f8a9b0c1d2). portfolio/recurring.py: manual registry matched vs cash_txn (merchant ILIKE) → last seen/typical day/next due/drift/status; detect_candidates() auto-detects unregistered recurring merchants (≥3 occ, regular gap, stable amount). API GET/POST/DELETE /api/spending/recurring + /detect. New Spending 'Recurring' tab (Recurring.jsx: tiles, add form, tracked table, Detected+Track). 17 tests pass; build OK. (6 test_auth fails are pre-existing .env DEV_AUTH_BYPASS artifact, not this unit.) |
| options-flex | Complete — options reconciled from raw Tiger flex (retired archive); IBKR orphans under new IBKR account. 385 contracts (377 Tiger + 8 IBKR), latest 2026-07-07; 33 tests pass. See construction/options-flex/. Reorg 2026-07-09: fixed expired-as-open bug (open 286->9, realized P/L reconciles, sum by_month=by_year=166425.98), added by_month; UI Trades moved above By-Underlying/Type grid + monthly P/L chart. |

## Current Status
- **Current Stage**: options-flex unit — built & verified. `ingestion.parse_options` now reconciles
  option contracts from the raw Tiger flex statements (per-file header map, Activity Type / qty-sign
  open-close, real fees, Tiger Realized P/L), replacing the frozen `.archive/tiger-options` export.
  IBKR orphans (ANF/GPS/HOG/WBA) carved to `data/ibkr-options/options.csv` under a new IBKR account.
  385 contracts, latest open 2026-07-07; idempotent; 33 tests pass. Loaded to prod (ep-shiny-star)
  + local dev DB.
- **Known limitation**: HK option multiplier = 1 (pre-existing convention); HK realized approximate.
- **Next Stage**: (options-flex) run loader against any other live DB (ep-royal-band) if still used;
  Deploy already serves prod. Prior open items (spending categories long tail) still stand.
