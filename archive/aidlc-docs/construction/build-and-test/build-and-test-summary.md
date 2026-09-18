# Build and Test Summary — networth

## Build Status
- **Backend**: alembic `upgrade head` → `b2c3d4e5f6a7` applied on Postgres. Imports clean. **Success.**
- **Seed**: `nw_item` 14 rows; re-run idempotent (stays 14).
- **Frontend**: `npm run build` → `web/dist/` produced (589 kB bundle; pre-existing chunk-size warning, benign). **Success.**

## Test Execution Summary

### Unit Tests
- **Total**: 7 · **Passed**: 7 · **Failed**: 0 · **Status**: Pass
- Metric math (6 figures + housing/CPF exclusions), FX latest-on-or-before, BR1 dup-date, BR2 default-0, BR4 missing-rate.

### Integration Tests (live API + PG)
- 8/8 scenarios pass. Verified against **real live portfolio value** S$1,029,006.95:
  - total_assets 1,691,587.55 · total_liabilities 300,000.00 · liquid 12,580.60
  - net_worth 1,391,587.55 · excl_housing 1,091,587.55 · excl_housing_cpf 1,041,587.55
- Duplicate date → 409; unknown-FX currency → 400; delete → list empties.

### Migration
- Down/up round-trip clean (`nw_*` dropped then recreated). Single head.

### Performance / Contract / Security / E2E
- N/A — single-user personal app; security extension disabled (Q9=B); no perf NFR. Frontend E2E not automated (manual UI usable via `npm run dev`).

## Overall Status
- **Build**: Success
- **All Tests**: Pass (7 unit + 8 integration)
- **Ready for Operations**: Yes (Operations stage is a placeholder)
