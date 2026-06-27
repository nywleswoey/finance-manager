# Code Summary — spending-tracker

Goal: ingest bank + credit-card statements (2025-01 onward) into a cash-flow ledger so the
user can see where money goes and spending trends — without double-counting credit-card
bill payments, excluding transfers, and auto-classifying into the user's existing taxonomy.

## Created
- `migrations/versions/c3d4e5f6a7b8_cash_txn.py` — creates `cash_txn` (down_revision `b2c3d4e5f6a7`).
- `build/parse_cash.py` — parses 3 sources → `build/cash_ledger_raw.csv`:
  - DBS consolidated bank (`pdftotext -layout`; Multiplier account only; direction from
    running-balance delta).
  - Trust card (`pdftotext -layout`; year inferred from statement cycle; `+` = credit;
    wrapped-merchant + footer-noise handling).
  - HSBC card (reads `build/hsbc_extracted.csv`; scanned PDFs are Claude-vision extracted).
- `build/hsbc_extracted.csv` — vision-extracted HSBC transactions (one-time; re-run for new months).
- `build/classify_cash.py` — applies `exclusions.yaml` then `categories.yaml` →
  `build/cash_ledger.csv` (is_spend, exclude_reason, category=group, subcategory=line item).
- `data/spending/categories.yaml` — two-level taxonomy mirroring the user's tracker.
- `data/spending/exclusions.yaml` — keyword rules per exclude_reason.
- `ingestion/load_cash.py` — idempotent upsert into `cash_txn` (reuses `ingestion.load`).
- `web/src/modules/spending/Overview.jsx` — tiles, category donut, monthly stacked-bar trend, line-item table.
- `web/src/modules/spending/Transactions.jsx` — filterable table (category, source, show-excluded).

## Modified
- `portfolio/models.py` — added `CashTxn`.
- `server/main.py` — added `/api/spending/*` routes.
- `web/src/App.jsx` — activated left-nav "Spending" section with Overview/Transactions sub-tabs.
- `Makefile` — `flat-cash`, `load-cash`, `spending` targets.
- `pyproject.toml` / `uv.lock` — added `pyyaml`.

## Key correctness rules
- **No double-counting**: DBS bank outflows that pay the HSBC (`4921…`) or Trust (`4179…`)
  card bills are excluded (`cc_payment`) because those cards' own line items are ingested.
  Bill payments to cards we DON'T itemise (e.g. `DBSC-5520…`) are KEPT as lump spend.
- **Card credits**: any inflow on a card source = repayment/refund → never spend.
- **Transfers excluded**: `Advice Funds Transfer`, `Advice FAST Collection` (DCOM sweeps),
  `Advice Investment`, brokerage names, `CPF HOUSING` → `is_spend=false`.
- **Idempotent**: dedup_hash over a stable natural key; re-classification updates in place.

## Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/spending/summary | total, avg/mo, by group, by line item, by month |
| GET | /api/spending/trends | monthly spend stacked by category |
| GET | /api/spending/transactions | filterable ledger (category/source/excluded) |
| GET | /api/spending/categories | categories + totals |

## Status (as built)
- 1007 cash rows loaded (DBS 688, Trust 310, HSBC 9); 793 counted as spend.
- Total counted spend S$141.7k over 17 months (~S$8.3k/mo).
- Coverage: ~65% of spend categorized; ~35% Uncategorized (long-tail merchants — iterative
  via `categories.yaml`). Open items needing a user decision: `TMLS` (recurring $98/mo GIRO
  biller), helper-salary PayNows, JB (Malaysia) spend, DBS-card POS location codes.
- Verified invariant: 0 rows with `exclude_reason='cc_payment'` counted as spend.
