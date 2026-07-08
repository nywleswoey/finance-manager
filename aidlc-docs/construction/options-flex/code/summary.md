# Code Summary — Unit: options-flex

**Status**: Complete (Code Generation + Build & Test verified)
**Date**: 2026-07-08

## What changed

- **`ingestion/parse_options.py`** — rewritten. Reconciles option contracts from the **raw Tiger
  flex** statements (`data/tiger-prime/*.csv`, `data/tiger-cash-boost/*.csv`) instead of the frozen
  `data/.archive/tiger-options/options.csv`:
  - `_flex_option_legs()` — per-file header→index map (offsets shift by year); symbol regex handles
    bare + `Name (...)` forms and `LNK.HK`; open/close from `Activity Type` (`OpenShort`/`Close`),
    falling back to qty sign on older blank-type files; fees summed by column NAME; captures Tiger
    `Realized P/L`, trade date, market.
  - `_expiry()` — parses the 8-digit `YYYYMMDD` expiry from the symbol (pdate couldn't).
  - `_reconcile()` — groups legs by `(underlying, expiry, strike, type)` → one `OptionTrade` row;
    realized = Tiger's figure for closed, computed premium credit for expired, None for open.
  - `_archive_legs()` — retained 12-col parser, now loads the **IBKR** orphan export.
  - `load_options()` — Tiger (flex) + IBKR (orphan file); account-level `_prune` removes the retired
    archive rows on cutover; idempotent upsert.
- **`scripts/seed.py`** — new `IBKR` account (Interactive Brokers, cash bucket).
- **`data/ibkr-options/options.csv`** — 8 orphan contracts (ANF/GPS/HOG/WBA) carved from the archive;
  IBKR flex exports carry no trades, so this is their only record. Committed via `.gitignore`
  exception (like `dividends-master.csv`).
- **`tests/test_options.py`** — 9 tests: money/`_und`/`_expiry`/symbol-regex helpers; reconcile
  (expired keeps premium, closed uses Tiger realized, open→None, contract-key split, weighted premium).

## Verification (Build & Test)

- 33 tests pass (24 existing + 9 new). Local dev DB migrated to head to fix an auth test that
  hit the missing `cdp_cost_lot` table (env, not this unit).
- Load against prod (`ep-shiny-star`) + local dev: **385 contracts** (377 Tiger + 8 IBKR), latest
  `open_date` = **2026-07-07**; outcomes 9 open / 95 closed / 281 expired. Idempotent re-run `+0`.
  `portfolio.options.realized_by_ticker` → 19 rows. IBKR orphans present under IBKR account.
- Per-underlying realized tracks the old archive closely (BABA/PLTR/NVDA/PYPL/TLT/RIVN within
  rounding); higher where 2026 trades were added; LNK now positive (correctly keeps expired-put
  premium — the archive's negative was a mult-1/high-fee artifact).

## Known limitation

- HK option multiplier = 1 (pre-existing `MULT` convention) → HK (LNK) realized approximate.

## Not changed

- `OptionTrade` schema (no migration); `portfolio/options.py`; frontend options view.
