# Code Generation Plan — Unit: options-flex

**Status**: Planning (awaiting approval)
**Date**: 2026-07-08

## Steps

- [ ] **1. Seed IBKR account** — `scripts/seed.py`: add `("IBKR", "Interactive Brokers", "cash")`
      to `ACCOUNTS`.
- [ ] **2. Carve IBKR orphans** — create `data/ibkr-options/options.csv` containing the archive
      rows for `ANF, GPS, HOG, WBA` (same 12-column archive format). Header + those rows only.
- [ ] **3. Rewrite `ingestion/parse_options.py`**:
    - [ ] 3a. `_flex_option_legs()` — walk `data/tiger-prime/*.csv` + `tiger-cash-boost/*.csv`,
          `Trades`→`Option` DATA rows; per-file header→index map; parse symbol (both formats,
          HK dot); classify open/close (Activity Type, else qty sign); sum fees by name; capture
          Tiger `Realized P/L`, trade date, market. Skip blank-symbol rows.
    - [ ] 3b. `_reconcile(legs)` — group by `(underlying, expiry, strike, type)`; build one
          contract dict (contracts, open/close dates, weighted premiums, fees, outcome, realized
          per the design rules), `security_id` via alias, account `Tiger Prime`.
    - [ ] 3c. `_load_archive_options(session, acct, alias, src, account)` — retain the existing
          12-col archive parser, generalised to load `data/ibkr-options/options.csv` under `IBKR`.
    - [ ] 3d. `load_options(session, acct, alias)` — run flex reconciler (Tiger) + archive loader
          (IBKR orphans); single idempotent `upsert` per source. Keep `source_file` distinct.
- [ ] **4. Pipeline** — confirm `ingestion.load.main` still calls `load_options` (no change needed);
      `make ingest` covers it.
- [ ] **5. Tests** — `tests/test_options.py`: symbol parse (bare / wrapped / `LNK.HK`), leg
      classification (Activity Type + qty-sign fallback), fee sum on an offset-shifted header,
      reconcile a known closed contract + an expired one, idempotency of the natural key.
- [ ] **6. Verify (Build & Test)** — seed + load against DB; assert: options `open_date` reaches
      `2026-07-07`; re-run `+0`; IBKR orphans present under `IBKR`; per-underlying realized sane vs
      prior; existing 24 tests pass.

## Out of scope
- No `OptionTrade` schema change / migration. No frontend change (options view already reads the table).
