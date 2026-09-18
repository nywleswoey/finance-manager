# Requirements — Unit: options-flex

**Status**: Requirements Analysis (awaiting approval)
**Date**: 2026-07-08
**Depth**: Standard (brownfield feature; correctness-sensitive reconciliation)

## Problem

Sold-option trades (wheel strategy) are loaded into `option_trade` by `ingestion.parse_options`
from a **frozen hand-maintained export** — `data/.archive/tiger-options/options.csv` (341
reconciled contracts, latest open **2026-04-30**). The live options now arrive in the Tiger
flex Activity Statements (`data/tiger-prime/*.csv`, `data/tiger-cash-boost/*.csv`), so options
opened **2026-05-01 … 2026-07-07 are missing** from the app.

## Goal

Reconcile options directly from the **raw Tiger flex statements** into `option_trade`, retiring
the archive export (user decision: **full replace**). App shows all options through the latest
statement, with accurate fees and realized P&L.

## Functional requirements

- **FR1 — Source**: parse `data/tiger-prime/*.csv` + `data/tiger-cash-boost/*.csv`, `Trades`
  section, rows where asset type = `Option`. (Archive CSV no longer read.)
- **FR2 — Column mapping by name**: each file's `Trades` HEADER row maps column name → index.
  Positions shift across years (2020 = 54 cols, 2021-2026 = 53). Never hardcode indices.
- **FR3 — Symbol parse**: `"Name (TICKER YYYYMMDD PUT|CALL strike)"` → underlying, expiry date,
  option type, strike. Tolerate HK tickers with dots (e.g. `LNK.HK`).
- **FR4 — Open/close from Activity Type**: `OpenShort` = sold-to-open (credit leg),
  `Close` = bought-to-close (debit leg). Blank-symbol continuation rows skipped. Any other
  activity type (e.g. `OpenLong`/`CloseLong`) logged and handled or flagged (wheel is short-only).
- **FR5 — Fees**: total fees per leg = sum of the fee-named columns (Transaction Fee, Commission,
  Platform Fee, Option Regulatory Fee, Settlement Fee, SEC Fee, Other Tripartite, Clearing,
  Exchange, GST, …) — everything between `Amount` and `Realized P/L`, EXCLUDING `Accrued Interest`.
- **FR6 — Reconcile to contracts**: group legs by (underlying, expiry, strike, type). FIFO-match
  `OpenShort` (open) legs to `Close` (close) legs. An open leg with no matching close whose expiry
  has passed → `expired` (assignment's stock leg already lives in `txn`; lumped with expired, as
  the archive loader did). Open, unexpired, unclosed → `open`.
- **FR7 — Realized P&L** (native ccy): `(premium_open − premium_close) × contracts × multiplier
  − fees_open − fees_close`. Multiplier: US = 100, HK varies (default per current MULT map).
  `Realized P/L` column retained as a cross-check.
- **FR8 — Schema**: reuse `OptionTrade` model unchanged (source_file updated to the flex path).
- **FR9 — Idempotent**: dedup_hash on the contract natural key; re-runs upsert in place.
- **FR10 — Pipeline**: loader runs inside the existing `ingestion.load` main (so `make ingest`
  covers it); archive-based `load_options` retired/replaced.

## Non-functional / constraints

- Idempotent + safe re-run (matches existing loaders).
- No new external surface, no secrets, no network → **Security Baseline** extension mostly N/A.
- **Property-Based Testing** extension: disabled (per project config).

## Acceptance criteria

- AC1: `option_trade` contains options with `open_date` through **2026-07-07** after ingest.
- AC2: Reconciled contract set is compared against the archive's 341 (parity report; differences
  explained by real fees now included and by any reconciliation corrections).
- AC3: Re-running the loader yields `+0 new` (idempotent).
- AC4: `portfolio.options.realized_by_ticker` and the app's options view surface the new contracts;
  existing tests still pass.
- AC5: The archive file is no longer required for a correct load (can be absent).

## Open questions — RESOLVED

- Scope → **Full replace** (user).
- Fees → **Fees are in the raw flex file** (columns [12]–[48]); reconstruct with real fees. The
  earlier "fees=0 vs estimate" tradeoff is void.

## Out of scope

- Long/bought options strategy P&L beyond the wheel (flag if encountered).
- Options on other brokers (only Tiger trades options here).
