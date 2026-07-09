# AI-DLC Audit Log

## Initial User Request
**Timestamp**: 2026-06-21T00:00:00Z
**User Input**: "using ai-dlc, i need to be able to mainatain a snapshot of my assets and liabilities. the items that i need are:
1. posb shared account
2. dbs multiplier account
3. srs account
4. tiger hkd
5. tigr sgd
6. tiger usd
7. tiger vault
8. ibkr sgd
9. cpf oa
10. cpf sa
11. cpf ma
12. tampines hdb
13. cpf home loan
14. cpf home loan accrued interest
15. my investment portfolio can ba included in calculation but value can be pulled live

questions i need to answer: total assest, total liabilities, liquid assets, networth, networh excluding housing (- hdb and home loan stuff), networth excluding housing and cpf (oa, sa, ma)"
**AI Response**: Ran workspace detection (brownfield, FastAPI + SQLAlchemy + Postgres portfolio app). Created aidlc-docs scaffold + state. Proceeding to Requirements Analysis.
**Context**: INCEPTION - Workspace Detection → Requirements Analysis

---

## Requirements Analysis — Clarifying Questions
**Timestamp**: 2026-06-21T00:05:00Z
**AI Response**: Generated `requirement-verification-questions.md` with 10 questions (snapshot history, broker-cash vs live-portfolio overlap, FX, liquid-asset definition, query tagging, accrued-interest liability treatment, UI vs API, fixed vs generic items, + security & PBT extension opt-ins). Awaiting answers at gate.
**Context**: INCEPTION - Requirements Analysis Step 6 gate

---

## Requirements Analysis — Answers Received
**Timestamp**: 2026-06-21T00:15:00Z
**User Input**: "done answering" — Q1:A, Q2:A, Q3:A, Q4:A,B,D,E,F, Q5:A, Q6:A, Q7:A, Q8:A, Q9:B, Q10:C
**AI Response**: Recorded extension config (Security=No, PBT=No). Wrote requirements.md (dated snapshots, native ccy + FX, fixed 14-item catalogue, 6 net-worth metrics, web UI). Awaiting approval to proceed to Workflow Planning.
**Context**: INCEPTION - Requirements Analysis Step 7-9
**Approval Prompt**: "Approve & Continue to Workflow Planning?"

---

## Requirements Analysis — Approved / Workflow Planning
**Timestamp**: 2026-06-21T00:20:00Z
**User Input**: "reviewed"
**AI Response**: Treated as approval. Generated execution-plan.md. Single unit `networth`. Execute: Functional Design, Code Generation, Build and Test. Skip: User Stories, Application Design, Units Generation, NFR Requirements/Design, Infrastructure Design. Low risk, additive. Awaiting plan approval.
**Status**: Approved (requirements) → Workflow Planning presented
**Context**: INCEPTION - Workflow Planning Step 9

---

## Workflow Planning — Approved / Functional Design
**Timestamp**: 2026-06-21T00:30:00Z
**User Input**: "proceed"
**AI Response**: Plan approved. Executed Functional Design for unit `networth`. Created domain-entities.md (nw_item catalogue, nw_snapshot, nw_value), business-logic-model.md (live value freeze, fx convert, 6-metric math), business-rules.md (BR1–BR10), frontend-components.md (React NetWorth tab). Awaiting approval to Code Generation.
**Status**: Approved (plan) → Functional Design presented
**Context**: CONSTRUCTION - Functional Design Step 7

---

## Functional Design — Approved / Code Generation Planning
**Timestamp**: 2026-06-21T00:40:00Z
**User Input**: "/commit then continue"
**AI Response**: Committed docs (4f6e7a7). Approved Functional Design. Created code-generation-plan.md (8 steps). Discovered App.jsx already has a left-nav "Net Worth" section placeholder → Net Worth implemented as nav section, not Portfolio tab. Awaiting plan approval before generating code.
**Approval Prompt**: "Approve code generation plan (8 steps) and proceed to generate code?"
**Context**: CONSTRUCTION - Code Generation Part 1 Step 7

---

## Code Generation — Approved / Generated
**Timestamp**: 2026-06-21T01:00:00Z
**User Input**: "/commit then continue" → "resume"
**AI Response**: Generated all 8 steps. Created: migration b2c3d4e5f6a7, scripts/seed_networth.py, portfolio/networth.py, web NetWorth.jsx, tests/test_networth.py, code summary. Modified: models.py, api/main.py, api.js, App.jsx, styles.css. Verified: 7/7 unit tests pass, imports clean, single alembic head, npm build succeeds.
**Status**: Code Generation complete
**Context**: CONSTRUCTION - Code Generation Part 2 Step 14

---

## Build and Test Stage
**Timestamp**: 2026-06-21T01:20:00Z
**User Input**: "/commit and continue"
**Build Status**: Success (alembic upgrade head on PG; npm build)
**Test Status**: Pass — 7 unit + 8 integration (against real live portfolio value)
**AI Response**: Migrated + seeded on Postgres, ran unit tests, end-to-end API smoke (items/create/dup-409/missing-fx-400/latest/delete), migration down/up round-trip clean. Wrote build-instructions.md, unit-test-instructions.md, integration-test-instructions.md, build-and-test-summary.md. Committed code in 3 chunks (b3bfe15 backend, 4def647 web, 5fa8c59 tests+docs).
**Files Generated**: build-instructions.md, unit-test-instructions.md, integration-test-instructions.md, build-and-test-summary.md
**Context**: CONSTRUCTION - Build and Test complete

---

## New Feature Request — Auth / Vercel Deploy
**Timestamp**: 2026-06-21T02:00:00Z
**User Input**: "create a new branch then use ai-dlc to secure the app for deployment to vercel. i need to put this behind google auth and only allow designated accounts to access"
**AI Response**: Created branch feat/google-auth-vercel. Brownfield (existing artifacts present) → adaptive Requirements Analysis. Assessed architecture: Vite SPA + FastAPI (Postgres), CORS wildcard, zero auth. Presented 3 blocking decisions via question gate.
**Context**: INCEPTION - Workspace Detection + Requirements Analysis (new unit: auth)

---

## Requirements Analysis — Decisions
**Timestamp**: 2026-06-21T02:05:00Z
**User Input**: Topology="All on Vercel (serverless)"; Auth="App-level Google OAuth + email allowlist (httponly cookie session)"; Security Baseline="Yes — enforce".
**AI Response**: Recorded decisions. Security Baseline extension ENABLED (blocking). Mapped SECURITY-01..15 to plan. Drafted consolidated Functional Design + Code Generation plan for single 'auth' unit.
**Context**: INCEPTION - Requirements Analysis complete; Extension Configuration updated

## Code Generation — Auth Unit (Generated)
**Timestamp**: 2026-06-21T02:30:00Z
**User Input**: "/commit and 2" (approve plan option 2 + commit)
**AI Response**: Implemented Google OAuth + allowlist + Vercel deploy. Backend: portfolio/config.py (auth env fields), api/auth.py (Google verify, session JWT cookie, allowlist, login router, rate-limit, logging), api/main.py (deny-by-default gate mw, security-headers mw, locked CORS+credentials, /api/health, global error handler), api/index.py (Vercel ASGI entry). Deps: google-auth, requests, PyJWT pinned (requirements.txt + pyproject + uv.lock). Frontend: web/src/auth.jsx (GIS login gate + logout), api.js (credentials:include + 401 broadcast), main.jsx (wrap in AuthGate), App.jsx + styles.css (signed-in user + sign out), web/.env.example. Deploy: vercel.json (builds + routes + static security headers), .env.example, DEPLOY.md.
**Context**: CONSTRUCTION - Code Generation (auth unit)

## Build and Test — Auth Unit
**Timestamp**: 2026-06-21T02:35:00Z
**Build Status**: Success (web: vite build OK; api imports clean)
**Test Status**: Pass — 17 auth unit tests (session mint/verify/expire/tamper, allowlist incl. revoke + case-insensitive, deny-by-default gate, login set-cookie/403/401/422, logout). Full suite 24 passed (7 networth + 17 auth), no regression.
**Security Compliance**: SECURITY-01..15 assessed — no blocking findings. Exceptions documented (13 GIS no-SRI -> CSP origin pin; 04 inline styles). Infra rules 02/06/07 platform-managed; object-level IDOR N/A (single shared owner dataset).
**Context**: CONSTRUCTION - Build and Test (auth unit) complete

## Spending Tracker — Goal & Decisions
**Timestamp**: 2026-06-22T00:00:00Z
**User Input**: "create a new branch then use ai-dlc to track the spending. Data source would be the bank statement and credit card statements (dbs-consolidated-statements, hsbc-cc, trust-cc). - avoid double counting (paying off credit card shouldn't count again since we read off cc statement) - exclude records like transfers to brokerage accounts - automatically classify transactions into categories - objective is to understand where i'm spending and my spending trends". Follow-up: shared existing tracker taxonomy (Income/Personal/Housing/Transport/Topups); "only interested in transactions from 2025 onwards".
**AI Response**: Branch `feature/spending-tracker`. Plan approved via plan mode. Clarified 3 decisions: HSBC scanned PDFs → Claude-vision one-time extract; categorization → hybrid rules + LLM fallback cached to YAML; scope 2025-01+ (so always-exclude DBS→itemised-card bill payments, no lost-history edge case). Aligned categories.yaml to the user's shared spreadsheet taxonomy.
**Context**: CONSTRUCTION - new unit `spending-tracker`

## Spending Tracker — Code Generation (Generated)
**Timestamp**: 2026-06-22T00:10:00Z
**AI Response**: Implemented cash-flow ledger. DB: `CashTxn` model + migration `c3d4e5f6a7b8_cash_txn`. Parsers: build/parse_cash.py (DBS balance-delta; Trust cycle-year + wrapped-merchant/footer handling; HSBC from vision CSV build/hsbc_extracted.csv). Classify: build/classify_cash.py over data/spending/{categories,exclusions}.yaml. Loader: ingestion/load_cash.py (idempotent). API: /api/spending/{summary,trends,transactions,categories}. UI: web/src/modules/spending/{Overview,Transactions}.jsx + App.jsx "Spending" section. Makefile: flat-cash/load-cash/spending. Dep: pyyaml.
**Key rules**: HSBC(4921)/Trust(4179) card bills in DBS excluded as cc_payment (their line items ingested); DBSC-5520 card (no statement) kept as lump spend; card-source credits = repayments (not spend); Advice Funds Transfer / FAST Collection / Investment / brokerage / CPF HOUSING excluded.
**Context**: CONSTRUCTION - Code Generation (spending-tracker unit)

## Spending Tracker — Build and Verify
**Timestamp**: 2026-06-22T00:15:00Z
**Build Status**: Success (web: vite build OK; api imports clean; `make spending` runs end-to-end, idempotent +0 on rerun).
**Verification**: 1007 rows loaded (DBS 688 / Trust 310 / HSBC 9); 793 spend; total S$141.7k / 17 mo. Invariant PASS: 0 cc_payment rows counted as spend. Exclusions: income 274k, internal_transfer 70.8k, investment 27.7k, cc_payment 23.8k, brokerage 2k. Spend by group: Personal 66.6k, Uncategorized 49.1k (35%), Housing 14.7k, Topups 10.7k, Transport 0.6k.
**Open items (need user input)**: TMLS recurring $98/mo GIRO biller; helper-salary PayNows; JB (MY) spend; DBS-card POS location codes — all currently Uncategorized.
**Context**: CONSTRUCTION - Build and Verify (spending-tracker unit) complete

## Spending Tracker — Manual Classification Round
**Timestamp**: 2026-06-22T00:30:00Z
**User Input**: Completed manual review of build/uncategorized_review.csv (172/174 rows labelled: Dining Out, Misc, Childcare, Shopping, Groceries, Other Transport, Insurance, 1 Exclude=SCL). "not too sure of the 3000+ stripe payment, make a note to inform me when this appears again since it looks recurring".
**AI Response**: Persisted labels as data/spending/merchant_overrides.yaml (96 prefix-matched overrides + 1 exclude; same-merchant conflicts resolved by $-weight — STRIPE/WHAT2DO→Misc). classify_cash.py now applies overrides ahead of categories.yaml + handles manual excludes. Added data/spending/watchlist.yaml + watch_alerts(): every `make spending` prints "⚠ WATCH" for STRIPE PAYMENTS ≥ S$1,000 (2 hits: 2025-07-20, 2026-03-20). Saved assistant memory spending-stripe-watch.md. Result: uncategorized 0.3% (2 RED DOT rows, S$434); counted spend S$130.4k (SCL excluded). Groups: Personal 67.6%, Housing 15.3%, Topups 8.2%, Misc 7.9%, Transport 0.7%.
**Context**: CONSTRUCTION - spending-tracker classification refinement

---

## Net-Worth Snapshot — Statement-Sourced Update
**Timestamp**: 2026-06-27T00:00:00Z
**User Input**: "using ai-dlc. i want to update my snapshot values with my statements: 1. dbs-consolidated-statements can be used for my POSB Shared Account, DBS Multiplier and srs account 2. tiger-prime can be used for my 4 tiger accounts"
**AI Response**: Requirements Analysis surfaced 4 gaps and resolved via AskUserQuestion — (a) target=NEW statement-dated snapshot (not in-place); (b) DBS month=latest 202603 (as at 31 Mar 2026); (c) SRS=cash only 1,869.72 (not total-incl-invested 82,405.90); (d) POSB Shared NOT present in DBS consolidated statement → left unchanged at 519.13. Tiger: confirmed Tiger Vault = Phillip USD MMF 112,707.55 USD (prior snapshot mislabeled it SGD — ~70k understatement, fixed to USD); tiger_usd = Cash Report Ending Cash +14,052.88 USD (replaced stale -24,947.12); tiger_hkd 15,535.00 / tiger_sgd 37,260.59 matched statement. Snapshot date 2026-06-18 (tiger end). Code Generation: scripts/snapshot_from_statements.py (parses tiger CSV Cash Report + Holdings/Fund and DBS PDF via pdftotext; carries forward posb/ibkr/cpf×3/hdb/loans×2 from snapshot 2026-06-21; dry-run default, --commit writes). FX backfill: inserted fx_rate 2026-06-18 for USD 1.2903 / HKD 0.1647 (carried back from 2026-06-21, the earliest existing rows) so rate_for() resolves. Dry-run reviewed + approved. COMMITTED snapshot id=2: net_worth S$1,800,252.46, total_assets 2,084,901.55, total_liabilities 284,649.09, liquid 237,990.76, excl_housing 1,690,901.55, excl_housing_cpf 1,245,367.25, portfolio 1,005,506.77.
**Context**: CONSTRUCTION - networth unit, statement-sourced snapshot update

---

## Net-Worth Snapshot — Ingest Latest DBS Statements (Apr/May/Jun 2026)
**Timestamp**: 2026-07-08T00:00:00Z
**User Input**: "using ai-dlc i want to ingest my latest dbs statements" + follow-up "are there commands to ingest delta files"
**AI Response**: 3 new DBS consolidated PDFs (202604/05/06) since last run (last was 202603). Tiger csv unchanged (period-end 2026-06-18) so tiger + carry-forward items identical across the new snapshots — only DBS figures move. Delta answer: no dedicated delta/incremental target; pattern is idempotent re-run (load/load-cash dedup by dedup_hash ON CONFLICT DO NOTHING; snapshots reject duplicate date BR1). Per user choice (AskUserQuestion): ingest all 3 months as month-end-dated snapshots. Ran scripts/snapshot_from_statements.py --dbs {202604,202605,202606} --date {2026-04-30,2026-05-31,2026-06-30} --commit. FX backfilled for Apr/May dates from nearest later rate (2026-06-18). DBS parsed: Multiplier 82,253.73/51,514.17/52,910.65; SRS cash 1,869.79/4,065.04/4,195.20. Committed snapshots id=3 (2026-04-30, NW 1,848,423.35), id=4 (2026-05-31, NW 1,819,879.04), id=5 (2026-06-30, NW 1,821,765.27). Total snapshots now 5.
**Context**: CONSTRUCTION - networth unit, monthly DBS statement ingest

## Net-Worth Snapshot — Add --all-new Delta Ingest
**Timestamp**: 2026-07-08T00:30:00Z
**User Input**: chose follow-up option 1 (add --all-new flag)
**AI Response**: Refactored snapshot_from_statements.py: extracted build_snapshot(); added --all-new (forward-delta) that ingests DBS months strictly newer than the latest already-snapshotted month, each dated month-end. Guards: requires >=1 existing snapshot to anchor "latest"; refuses to backfill older un-ingested statements (tiger/FX/portfolio can't be reconstructed historically); per-date BR1 skip. Verified: nothing-new path, single-mode SKIP on existing date, and delta loop (temp fake 202607 -> previewed @ 2026-07-31, temp removed).
**Context**: CONSTRUCTION - networth unit tooling

## Ingestion Command Reference
**Timestamp**: 2026-07-08T01:00:00Z
**User Input**: "i need specific commands to be available for reference for ingesting new data files"
**AI Response**: Added Makefile targets `snapshot` (dry-run --all-new) + `snapshot-commit` (--all-new --commit). Added README "Ingesting new data files" section: per-source table (broker->make ingest, bank/card->make spending, market->make prices, DBS->make snapshot/snapshot-commit) + one-off single-month snapshot commands. Verified `make snapshot`.
**Context**: CONSTRUCTION - networth unit tooling/docs

## Consolidated Delta Ingest — make ingest-all
**Timestamp**: 2026-07-08T01:30:00Z
**User Input**: "i need a consolidated command to ingest delta dbs consolidated statements, cdp-statements,dbs-cc,endowus statement,fsm,moomoo,tiger-cash-boost,tiger-prime and trust-cc"
**AI Response**: Verified source->pipeline coverage: brokers (tiger-prime, tiger-cash-boost, moomoo, fsm, cdp-statements, endowus) -> make ingest (build_ledger + parse_dividends/parse_cdp/parse_endowus); spending (dbs-cc, trust-cc, dbs-consolidated) -> make spending (parse_cash/classify_cash); net-worth (dbs-consolidated + tiger-prime) -> make snapshot-commit; endowus NAV/FX -> make prices. Added Makefile target `ingest-all` = ingest + spending + (-)prices + snapshot-commit via $(MAKE) sub-calls (prices non-fatal). Verified idempotent: re-run shows txn +0/532, dividend +0/555, cash_txn +0/1424, prices 33 ok, snapshot nothing-new. Documented in README ingest section.
**Context**: CONSTRUCTION - cross-unit ingestion tooling

---

## New Unit: options-flex — Initial User Request
**Timestamp**: 2026-07-08T00:00:00Z
**User Input**: "my latest options transactions are in the tiger-broker file but not shown on the app" ... "using ai-dlc, pick option 1" (build a flex-options parser that reconciles tiger flex option legs into option_trade and retires the frozen archive dependency).
**AI Response**: Diagnosed: option_trade is loaded by ingestion.parse_options from the frozen hand-export data/.archive/tiger-options/options.csv (341 reconciled contracts, latest open 2026-04-30). The live options now live in the tiger flex statements (tiger_prime_*.csv) -> build/ledger.csv as asset_type=option (503 legs, 2021-03-26 .. 2026-07-07), but load_ledger skips options and load_options doesn't read them, so 2026-05-01..07-07 options never reach the DB. Starting AI-DLC INCEPTION for new unit `options-flex`.
**Context**: INCEPTION - Workspace Detection / Requirements (new unit: options-flex)

---

## Workspace Detection
**Timestamp**: 2026-07-08T00:00:00Z
**AI Response**: Resumed existing brownfield workspace (aidlc-state.md present). Prior units: networth, auth, spending-tracker (all Complete). New unit `options-flex` added. Reverse engineering not needed — options subsystem already located (ingestion/parse_options.py, portfolio/options.py, build/build_ledger.py option parsing, portfolio/models.OptionTrade). Proceeding to Requirements Analysis.
**Context**: INCEPTION - Workspace Detection (brownfield resume)

---

## Requirements Analysis + Clarifications
**Timestamp**: 2026-07-08T00:00:00Z
**User Input**: Scope="Full replace"; Fees="the option fees are in the file?"
**AI Response**: Investigated raw Tiger flex Trades section. Confirmed fees ARE in the raw file (per-file named header; fee columns [12]..[48] Commission/Platform/OptReg/etc.; Activity Type OpenShort/Close gives open/close explicitly; [49] Realized P/L as cross-check). Column offsets shift across years (2020=54 cols, 2021-26=53) -> must map columns by header NAME, not index. Decision: FULL REPLACE with REAL fees parsed from raw flex (fees=0/estimate tradeoff void). Wrote aidlc-docs/inception/requirements/options-flex-requirements.md (FR1-10, AC1-5). Extensions: Security Baseline N/A (local file parse, no auth/secrets/network); Property-Based Testing disabled per config.
**Context**: INCEPTION - Requirements Analysis (unit: options-flex)

---

## Workflow Planning + Functional Design
**Timestamp**: 2026-07-08T00:00:00Z
**User Input**: [approve plan] "proceed"; then on orphan-scope question: "the ANF/GPS/HOG/WBA trades are from interactive brokers"
**AI Response**: Prototyped reconciler against raw flex. Found: (1) symbol has 2 formats (bare + "Name (...)"); (2) older files leave Activity Type blank -> infer open/close by qty sign; (3) Tiger Realized P/L populated on close legs; (4) FULL REPLACE IS LOSSY — ANF/GPS/HOG/WBA (~$1,772 realized, closed 2022) exist in archive but NOT in any flex file. User clarified these are IBKR trades (IBKR flex exports carry no trades, so archive was their only record). Revised scope to HYBRID: Tiger options reconciled from flex (authoritative, real fees, retire archive for Tiger); IBKR orphans carved to data/ibkr-options/options.csv, loaded under a new IBKR account. Wrote aidlc-docs/construction/options-flex/functional-design/functional-design.md (algorithm, components, test plan). Skipped NFR/Infra (local parse). Awaiting approval to Code Generation.
**Context**: CONSTRUCTION - Functional Design (unit: options-flex)

---

## Code Generation + Build & Test
**Timestamp**: 2026-07-08T00:00:00Z
**User Input**: "approve" (code-gen plan)
**AI Response**: Implemented per plan. Rewrote ingestion/parse_options.py (flex leg parser + _expiry YYYYMMDD fix caught in dry-run + reconciler + account-level prune on cutover + IBKR archive loader); added IBKR account to scripts/seed.py; carved data/ibkr-options/options.csv (8 rows ANF/GPS/HOG/WBA) with .gitignore exception; tests/test_options.py (9 tests). Build & Test: 33 tests pass (24+9); migrated local dev DB to head to fix an auth test hitting missing cdp_cost_lot (env). Loaded prod ep-shiny-star + local dev: 385 contracts (377 Tiger + 8 IBKR), latest open 2026-07-07, idempotent +0, realized_by_ticker 19 rows, IBKR orphans under IBKR account. All AC1-5 met. Unit options-flex COMPLETE.
**Context**: CONSTRUCTION - Code Generation + Build & Test (unit: options-flex) — COMPLETE

## Options Tab Reorg (bug fix + monthly view)
**Timestamp**: 2026-07-09T00:00:00Z
**User Input**: "using ai-dlc, i need to reorganise the options tab: 1. consolidated numbers doesn't match up. expired options shouldn't be left as open? 2. by underlying and by type are not as important as trades. swap their positions. 3. being able to see monthly p/l will be good" ; then "approve"
**AI Response**: Brownfield targeted change on unit options-flex. Root cause of #1: compute()/realized_by/realized_by_ticker used is_open = (close_date is None); 277 outcome='expired' legs carry close_date=None (expired worthless, never bought back) -> miscounted OPEN and their realized P/L excluded via continue. Fix: added _is_open(t) [open only if outcome=='open'; expired/closed/assigned=realized; null-outcome fallback close_date+realized_pl None] and _realized_date(t)=close_date or expiry_date; applied to compute(), realized_by(), realized_by_ticker(). #3: added by_month bucket (realized-month key YYYY-MM) to compute(). #2 + #3 UI: web/src/modules/portfolio/Options.jsx — moved Trades table above By Underlying/By Type grid; added Realized P/L by Month bar chart (last 24 months) under year chart. Verify: open 286->9, trades_closed 376, win_rate 86.4%, sum(by_month)=sum(by_year)=total_pl 166425.98 (reconciles). Tests 33 pass; web build OK.
**Context**: CONSTRUCTION - Code Generation + Build & Test (unit: options-flex) — reorg increment COMPLETE

---

## Code Generation (unit: options-flex) — monthly P/L amount labels
**Timestamp**: 2026-07-09T00:33:00Z
**User Input**: "using ai-dlc show the amount as well for the monthly p/l for options"
**AI Response**: Brownfield micro-increment on web/src/modules/portfolio/Options.jsx. Realized P/L by Month bar chart had color-coded bars + tooltip only, no always-visible amounts (year chart already had LabelList). Added <LabelList dataKey="pl" position="top" fontSize={9} formatter={kfmt}> to monthly Bar; kfmt = compact k-format (>=1000 -> "x.xk", else raw) since 24 bars are thin. Applied standing chart convention (most recent on LEFT): monthly data was slice(-24) ascending = newest on right; changed to .slice(-24).reverse() so newest is leftmost, matching year chart + preference. X-axis kept interval="preserveStartEnd" to avoid crowding. Verify: npm run build OK (841 modules, built 1.12s).
**Context**: CONSTRUCTION - Code Generation (unit: options-flex) — monthly amount labels COMPLETE

---

## Overview TWR (add time-weighted return)
**Timestamp**: 2026-07-09T00:00:00Z
**User Input**: "using ai-dlc, add the TWR to my overview dashboard as well" ; then "approve"
**AI Response**: Overview already showed a return tile but it was money-weighted (XIRR), despite portfolio/twr.py being named 'twr'. Added a TRUE time-weighted return: _twr() chains daily sub-period returns r_t=(MV_t - C_t)/MV_{t-1} over the daily-priced sleeve (funds excluded, same universe as XIRR). Key correctness fix found in verify: contribution C_t must be the MARKET VALUE of each day's UNIT DELTA (not txn.price — many opens/transfers/buys carry price=NULL), else share inflows via transfer/open register as return (first attempt gave 48.8% p.a. from spurious month-end spikes). Excludes return-in-kind (stock dividend, bonus issuance). Result: twr_annualised 1.3% vs xirr 27.6% — divergence is the expected money-vs-time weighting (most capital deployed in recent 2024-25 winners); yearly factors track real market history (2018 -15%, 2022 -10%, 2024 +18%, 2025 +25%), no artifacts. Added twr_annualised + twr_cumulative to compute_twr() return -> /api/return auto-carries; Overview.jsx new tile 'Time-weighted Return (p.a.)'. 33 tests pass; web build OK.
**Context**: CONSTRUCTION - Code Generation + Build & Test (performance/twr increment) — COMPLETE

---

## Auth: local dev bypass feature flag (DEV_AUTH_BYPASS)
**Timestamp**: 2026-07-09T00:00:00Z
**User Input**: "using ai-dlc, i need a way to skip auth when running on local. maybe a feature flag?" ; then two confirmations via AskUserQuestion: guardrail = "Guard on VERCEL env (Recommended)", tests = "Yes, add tests (Recommended)"
**AI Response**: Brownfield increment on the auth unit (Security Baseline extension enabled). Added a DEV_AUTH_BYPASS feature flag so the API+web can run locally without Google OAuth. Design routes the bypass through the SINGLE existing chokepoint auth.user_from_request() so both the deny-by-default gate (main.auth_gate) AND /api/auth/me honor it consistently. Security guardrail (SECURITY): config.auth_bypass_active = dev_auth_bypass AND NOT os.getenv("VERCEL") — every Vercel deploy sets VERCEL, so the bypass is force-OFF in any deployed env even if the flag leaks into prod env vars; fail-safe by construction. When active, user_from_request returns synthetic DEV_USER {sub: dev@localhost} without reading any cookie. main.py logs a loud ⚠️ warning at startup when active. Default false → zero behavior change to prod/existing flows. Files: portfolio/config.py (flag + auth_bypass_active property, import os), server/auth.py (DEV_USER const + bypass branch), server/main.py (startup warning), .env.example (documented DEV_AUTH_BYPASS=false). Tests: +4 in tests/test_auth.py (off-by-default, grants dev user without cookie, force-disabled on Vercel even with flag on, opens the gate) — 21 pass (17 prior + 4 new).
**Context**: CONSTRUCTION - Code Generation + Build & Test (auth unit — local dev bypass increment) — COMPLETE

---
