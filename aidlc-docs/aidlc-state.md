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
| networth | Complete (5 snapshots; latest DBS ingest Apr/May/Jun 2026 -> id=3/4/5 month-end dated; scripts/snapshot_from_statements.py). 2026-07-09 increment: added per-item Breakdown display (was never rendered) + editable manual fields. networth.AUTO_CODES (6 statement-pulled codes, single source of truth; script imports it) + is_manual flag on catalogue/values; update_snapshot() + PATCH /api/networth/snapshots/{id} edits supplied items in place (re-freeze FX at snapshot date, portfolio frozen) — fills manual fields after ingest without duplicate-date 409. api.js patch(); NetWorth.jsx Breakdown card (manual editable inline, auto read-only). 11 tests pass (+4); no schema change; build OK. |
| auth | Complete (web build OK). 2026-07-09: added DEV_AUTH_BYPASS local-dev flag — skips Google auth via single chokepoint user_from_request; force-OFF on Vercel (guard: dev_auth_bypass AND NOT env VERCEL); synthetic dev@localhost user; startup warning. 21 auth tests pass (+4 bypass tests). |
| spending-tracker | Code Generation + Verify complete — see construction/spending-tracker/code/summary.md |
| spending-recurring | Complete 2026-07-09 — recurring-spend registry (recurring_spend table, migration e7f8a9b0c1d2). portfolio/recurring.py: manual registry matched vs cash_txn (merchant ILIKE) → last seen/typical day/next due/drift/status; detect_candidates() auto-detects unregistered recurring merchants (≥3 occ, regular gap, stable amount). API GET/POST/DELETE /api/spending/recurring + /detect. New Spending 'Recurring' tab (Recurring.jsx: tiles, add form, tracked table, Detected+Track). 17 tests pass; build OK. (6 test_auth fails are pre-existing .env DEV_AUTH_BYPASS artifact, not this unit.) — 2026-07-09 increment: (A) dismiss false positives — recurring_dismissed table (migration f0a1b2c3d4e5) + dismiss(); detect_candidates() excludes dismissed AND restricts to recurring channels [source IN dbs-cc/hsbc/trust OR dbs+description ILIKE %giro%]; POST /api/spending/recurring/dismiss; ✕ on Detected rows. (B) business-day next_due (weekends only) — _infer_shift votes per-item prev vs next from history, list_recurring shifts next_due + exposes `shift`; UI →Wkdy indicator. 27 tests pass (+13); migration up/down/up clean; build OK. |
| options-flex | Complete — options reconciled from raw Tiger flex (retired archive); IBKR orphans under new IBKR account. 385 contracts (377 Tiger + 8 IBKR), latest 2026-07-07; 33 tests pass. See construction/options-flex/. Reorg 2026-07-09: fixed expired-as-open bug (open 286->9, realized P/L reconciles, sum by_month=by_year=166425.98), added by_month; UI Trades moved above By-Underlying/Type grid + monthly P/L chart. |

## Current Status
- **2026-07-09 (FSM + Malaysia)**: loaded latest iFast delta (data/fsm/ifast_20260709.csv, 20 rows May–Jul 2026
  appended into ifast_historical.csv — disjoint by date). Added Bursa Malaysia / MYR market: FSM parsers now
  infer market from Product Currency (MYR→MY, else SG) instead of hardcoding SG (build_ledger.py + parse_dividends.py);
  seed.py CCY += MY:MYR; symbols.csv 3255→HEIM (Heineken Malaysia Bhd); prices.py yahoo_symbol MY→.KL + MYR FX.
  Verified end-to-end: HEIM buy 1600 @ 19.34 MYR loaded, seeded MY/MYR, priced 19.30 MYR (.KL), MYR FX 0.3167,
  mv_sgd 9779.70. Full suite 68 pass. Fee (70.91 MYR) not captured (consistent w/ existing FSM handling).
- **2026-07-09 (trade fees)**: fees were dead plumbing (column in ledger+txn but never populated/loaded/used).
  Now captured + folded into cost basis. build_ledger: load_fsm emits Total Fee; load_tiger sums flex fee columns
  per trade via header map (fixed latent bug — Trades header is row[4]=='Symbol', not row[3]=='HEADER', so hdr was
  always None). load.load_ledger maps fees→txn.fees (+ in upsert cols). performance.compute folds fee into
  invested (buy) / proceeds (sell) in native ccy → flows through P/L, XIRR, TWR; exposes fees_sgd per position.
  Options fees stay in option_trade (no double-count). Verified: HEIM invested 31014.91 = 1600*19.34 + 70.91;
  total pl_sgd 327269.55→325801.68 (fees ~1468), total stock fees_sgd 1555.91; 68 tests pass.
- **Current Stage**: options-flex unit — built & verified. `ingestion.parse_options` now reconciles
  option contracts from the raw Tiger flex statements (per-file header map, Activity Type / qty-sign
  open-close, real fees, Tiger Realized P/L), replacing the frozen `.archive/tiger-options` export.
  IBKR orphans (ANF/GPS/HOG/WBA) carved to `data/ibkr-options/options.csv` under a new IBKR account.
  385 contracts, latest open 2026-07-07; idempotent; 33 tests pass. Loaded to prod (ep-shiny-star)
  + local dev DB.
- **Known limitation**: HK option multiplier = 1 (pre-existing convention); HK realized approximate.
- **Next Stage**: (options-flex) run loader against any other live DB (ep-royal-band) if still used;
  Deploy already serves prod. Prior open items (spending categories long tail) still stand.
