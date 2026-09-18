# Unit Test Execution — networth

## Run
```bash
PYTHONPATH=. .venv/bin/python tests/test_networth.py
```
Stdlib `unittest` on in-memory SQLite — no Postgres, no pytest dependency.

## Coverage
| Test | Asserts |
|------|---------|
| test_six_metrics | all 6 metrics incl. housing/CPF exclusion math |
| test_usd_fx_freeze | value_sgd = native × frozen rate |
| test_rate_sgd_is_one | SGD → 1 |
| test_rate_latest_on_or_before | picks latest fx_rate ≤ date |
| test_rate_missing_raises | BR4 — no rate → ValueError |
| test_create_freezes_and_defaults_missing_to_zero | BR2 — omitted items default 0; freezes |
| test_duplicate_date_rejected | BR1 — one snapshot per date |

## Result (this run)
**7 passed, 0 failed.**
