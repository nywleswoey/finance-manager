# Functional Design — Unit: options-flex

**Status**: Functional Design (awaiting approval)
**Date**: 2026-07-08
**Requirements**: `aidlc-docs/inception/requirements/options-flex-requirements.md`

## Decisions (from analysis + user)

- **Scope = Hybrid** (revised from "full replace" once data proved flex is not a superset):
  - **Tiger** options: reconciled from raw flex statements — authoritative, full history, real fees.
    Retire `data/.archive/tiger-options/options.csv` for Tiger.
  - **IBKR** orphans (`ANF, GPS, HOG, WBA`; ~$1,772 realized, closed 2022) are IBKR trades manually
    kept in the Tiger archive (IBKR flex exports carry no trades). Preserve them under a new
    **IBKR** account, sourced from a carved-out `data/ibkr-options/options.csv`.

## Data facts (validated against raw files)

- Source sections: `data/tiger-prime/*.csv`, `data/tiger-cash-boost/*.csv`, `Trades` section,
  `row[1] == "Option"`, `row[3] == "DATA"`.
- **Header is per-file** (`row[4] == "Symbol"`); column offsets shift (2020 = 54 cols, else 53) →
  build a `name → index` map per file. Never hardcode indices.
- **Symbol** appears two ways: bare `"AMD 20210917 PUT 77.5"` (older) and wrapped
  `"Advanced Micro Devices (AMD 20260109 PUT 205.0)"` (newer). Regex
  `([A-Z0-9.]+)\s+(\d{8})\s+(PUT|CALL)\s+([\d.]+)` (searched, not anchored) matches both. HK tickers
  carry a dot (`LNK.HK`) → normalise via existing `canon`/alias (`LNK.HK` → `LNK`).
- **Open/close**: `Activity Type` = `OpenShort` (sold-to-open) / `Close` (bought-to-close). Older
  files leave it **blank** → infer from qty sign: `qty < 0` = open, `qty > 0` = close.
- **Fees**: sum the fee-named columns (Transaction Fee, Commission, Platform Fee, Option Regulatory
  Fee, Settlement Fee, SEC Fee, Other Tripartite, Clearing, Exchange, GST, …). Exclude `Amount`,
  `Accrued Interest in Trade`, `Realized P/L`. Fees are negative in-file → use absolute for costs.
- **Realized P/L** column is populated on close legs (both new + old files) — used as cross-check.
- Blank-`Symbol` rows are continuation lines → skip.

## Reconciliation algorithm

1. **Collect legs** across all flex files. Per leg: underlying, expiry, type, strike, market,
   qty (signed), price, fees (abs), realized (Tiger), open|close flag, trade_date.
2. **Group by contract key** `(underlying, expiry, strike, type)`.
3. Per group → one `OptionTrade` row:
   - `contracts` = Σ|qty of open legs|; `open_date` = earliest open; `close_date` = latest close.
   - `premium_open` = Σ(open px×|qty|) / Σ|qty_open|  (weighted avg per share).
   - `premium_close` = Σ(close px×|qty|) / Σ|qty_close|  (0 if no close).
   - `fees_open` / `fees_close` = Σ abs fees of open / close legs.
   - **outcome**: has close legs → `closed`; else expiry passed → `expired` (assignment lumped here —
     its stock leg lives in `txn`, matching archive behaviour); else `open`.
   - **realized_pl** (native ccy):
     - closed (fully): Σ Tiger `Realized P/L` of close legs (already fee-net) — most accurate.
     - expired/assigned: `premium_open × contracts × mult − fees_open` (full credit kept).
     - partially closed: Tiger realized of closed portion + expired credit of the remainder.
     - open: `null` (unrealised).
   - `multiplier`: US = 100, HK per existing `MULT` (default 1 for HK).
   - `currency`: US → USD, HK → HKD.
4. **Idempotent**: `dedup_hash = h(underlying, type, strike, expiry, open_date, occ)`; upsert in place.

## Components

- **`ingestion/parse_options.py`** — rewritten:
  - `load_options(session, acct, alias)` now parses the raw flex files (per-file header map,
    symbol regex, leg classification, grouping, realized) → `option_trade`, account `Tiger Prime`.
  - Helper `_flex_option_legs()` yields normalised legs; `_reconcile(legs)` builds contract rows.
  - Retains `money`/`num`/`pdate` helpers.
- **IBKR orphans**: `data/ibkr-options/options.csv` (carved from the archive; the 4 underlyings) +
  a small loader path (reuse the existing archive-format parser) under account **IBKR**.
- **`scripts/seed.py`** — add `("IBKR", "Interactive Brokers", "cash")` to `ACCOUNTS`.
- **Pipeline**: `load_options` already runs inside `ingestion.load.main` → covered by `make ingest`.

## Impact / non-goals

- `OptionTrade` schema unchanged; `portfolio/options.py` (realized_by_ticker) unchanged — reads the
  same table.
- No migration (no schema change). No new external surface (Security Baseline N/A).
- The archive file `data/.archive/tiger-options/options.csv` is retired for Tiger (kept on disk as
  historical reference; loader no longer reads it).

## Test plan (Build & Test stage)

- Unit: symbol parse (both formats + HK dot), leg classification (Activity Type + qty-sign
  fallback), fee sum (name-based, offset-shift file), reconciliation of a known contract.
- Integration: run loader against DB → assert options through `2026-07-07`; idempotent re-run
  `+0`; per-underlying realized sanity vs prior (differences explained by new 2026 trades + real
  fees); IBKR orphans present under IBKR account.
- Regression: existing 24 tests still pass; `portfolio.options.realized_by_ticker` returns rows.
