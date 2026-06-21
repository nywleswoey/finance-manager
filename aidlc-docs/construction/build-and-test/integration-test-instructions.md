# Integration Test Instructions — networth

Tests the API ↔ DB ↔ live-portfolio compute path end to end.

## Setup
```bash
docker compose up -d db
PYTHONPATH=. .venv/bin/alembic upgrade head
PYTHONPATH=. .venv/bin/python scripts/seed_networth.py
PYTHONPATH=. .venv/bin/uvicorn api.main:app --port 8000
```

## Scenarios (executed this run, port 8011/8012)
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | GET /api/networth/items | 200, 14 items | ✓ |
| 2 | POST /api/networth/snapshots (5 lines) | 200, 6 metrics computed off **real** live portfolio value; missing items default 0 (14 stored) | ✓ |
| 3 | Verify math | total_assets = Σassets + live; net_worth, excl-housing, excl-housing+cpf per formulas | ✓ (see summary) |
| 4 | POST same date | 409 duplicate | ✓ |
| 5 | POST currency with no fx_rate (EUR) | 400 | ✓ |
| 6 | GET /api/networth/latest | 200, 14 values | ✓ |
| 7 | DELETE /api/networth/snapshots/{id} | 200 ok; list empty after | ✓ |
| 8 | Migration down/up round-trip | nw_* dropped then recreated cleanly | ✓ |

## Cleanup
DB left at head + seeded (test snapshot deleted).
