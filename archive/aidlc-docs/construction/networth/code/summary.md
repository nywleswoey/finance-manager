# Code Summary — networth

## Created
- `migrations/versions/b2c3d4e5f6a7_networth.py` — creates `nw_item`, `nw_snapshot`, `nw_value` (down_revision `a1f2c3d4e5f6`).
- `scripts/seed_networth.py` — idempotent seed of the 14-item catalogue.
- `portfolio/networth.py` — live value, FX freeze, 6-metric math, snapshot CRUD.
- `web/src/modules/networth/NetWorth.jsx` — summary cards, trend chart, create form, history table.
- `tests/test_networth.py` — stdlib unittest (in-memory SQLite); metric math, FX, BR1/BR4.

## Modified
- `portfolio/models.py` — added `NwItem`, `NwSnapshot`, `NwValue`.
- `api/main.py` — added `/api/networth/*` routes (items, snapshots list/get/create/delete, latest).
- `web/src/api.js` — `post(path, body)` JSON support + `del(path)`.
- `web/src/App.jsx` — left-nav "Net Worth" section toggles between Portfolio tabs and `<NetWorth/>`.
- `web/src/styles.css` — net-worth form/table classes.

## Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/networth/items | catalogue (14 items) |
| GET | /api/networth/snapshots | list with metrics |
| GET | /api/networth/latest | latest snapshot detail |
| GET | /api/networth/snapshots/{id} | one snapshot detail |
| POST | /api/networth/snapshots | create (freezes FX + live value) |
| DELETE | /api/networth/snapshots/{id} | delete |

## Run
```bash
# migrate + seed
PYTHONPATH=. .venv/bin/alembic upgrade head
PYTHONPATH=. .venv/bin/python scripts/seed_networth.py
# tests
PYTHONPATH=. .venv/bin/python tests/test_networth.py
# api + web
PYTHONPATH=. .venv/bin/uvicorn server.main:app --reload --port 8000
cd web && npm run dev
```

## Verification (this run)
- 7/7 unit tests pass.
- `import portfolio.models, portfolio.networth, api.main` ok.
- Single alembic head `b2c3d4e5f6a7`.
- `npm run build` succeeds.
