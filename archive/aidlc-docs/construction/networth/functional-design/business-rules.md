# Business Rules — networth

- **BR1 — one snapshot per date**: `nw_snapshot.date` unique. Re-POST same date → 409 (or update existing — default: reject, ask user to delete first). MVP: reject duplicate.
- **BR2 — missing line defaults to 0**: if a create request omits a catalogue item, its `native_value = 0`, `currency = item.currency_default`. Keeps form forgiving.
- **BR3 — SGD rate is exactly 1**: never look up fx for SGD.
- **BR4 — non-SGD requires a rate**: if no `fx_rate` row with `date ≤ snapshot.date` for the currency → reject snapshot with clear error (currency + date). No silent fallback.
- **BR5 — frozen values immutable**: once written, `value_sgd`, `rate_to_sgd`, `portfolio_value_sgd` never recomputed. Editing requires deleting + recreating the snapshot.
- **BR6 — liabilities stored positive**: `native_value` for liabilities entered as positive magnitude; metric math subtracts them (kind drives sign, not the stored value).
- **BR7 — negative values allowed for assets**: a cash account can legitimately be negative (overdraft); permitted.
- **BR8 — accrued interest is housing+liability**: `home_loan_accrued` tagged `kind=liability, is_housing=true`. Excluded with housing in `net_worth_excl_housing`.
- **BR9 — catalogue fixed**: no add/remove via API/UI (Q8=A). Seeded once, idempotent.
- **BR10 — live value freeze timing**: portfolio value captured at the moment of snapshot creation, regardless of snapshot.date. (Pragmatic: live prices have no historical per-date snapshot table for this.)

## Validation
- `date`: required, ISO date.
- `native_value`: numeric, finite. Decimal.
- `currency`: 3-letter; must be SGD or have an fx_rate.
- `code`/`item_id`: must resolve to an active catalogue item.
