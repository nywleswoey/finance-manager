# Build Instructions — networth

## Prerequisites
- Python 3.12, `uv` venv at `.venv`; Node 18+ for `web/`.
- Postgres via `docker compose up -d db` (host port 5544). `DATABASE_URL` from `.env`.

## Build steps
```bash
# 1. backend deps (already in uv.lock)
uv sync

# 2. DB up + migrate + seed catalogue
docker compose up -d db
PYTHONPATH=. .venv/bin/alembic upgrade head
PYTHONPATH=. .venv/bin/python scripts/seed_networth.py

# 3. frontend build
cd web && npm install && npm run build
```

## Verify
- `alembic heads` → single head `b2c3d4e5f6a7`.
- `nw_item` has 14 rows after seed.
- `web/dist/` produced (FastAPI serves it at `/`).

## Troubleshooting
- **PG refused**: `docker compose up -d db`, wait for healthcheck.
- **Multiple alembic heads**: should not occur; `b2c3d4e5f6a7` down_revision is `a1f2c3d4e5f6`.
