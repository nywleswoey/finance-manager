.PHONY: db-up db-down migrate seed flat load prices ingest api web build-web app psql reset net

PY = PYTHONPATH=. .venv/bin/python
AL = PYTHONPATH=. .venv/bin/alembic

db-up:        ## start postgres
	docker compose up -d
db-down:      ## stop postgres
	docker compose down
migrate:      ## apply alembic migrations
	$(AL) upgrade head
seed:         ## seed accounts / securities / aliases / corporate actions
	$(PY) scripts/seed.py

flat:         ## (re)build the normalized flat files from statements
	$(PY) build/parse_moomoo.py >/dev/null
	$(PY) build/parse_cdp.py >/dev/null
	$(PY) build/parse_endowus.py >/dev/null
	python3 build/build_ledger.py >/dev/null
	python3 build/parse_dividends.py >/dev/null

load:         ## load ledger + dividends into DB (idempotent)
	$(PY) -m ingestion.load
	$(PY) build/export_dividends_master.py
prices:       ## fetch latest prices + FX (needs network)
	$(PY) -m ingestion.prices

ingest: flat load   ## full ingest: statements -> flat -> DB

api:          ## run the API (serves built web/ at /)
	$(PY) -m uvicorn server.main:app --reload --port 8000
build-web:    ## build the React frontend
	cd web && npm install && npm run build
app: build-web   ## build frontend then run API+web on :8000
	$(PY) -m uvicorn server.main:app --port 8000

net:          ## per-ticker net verdict (+/-) incl dividends + option premiums
	$(PY) scripts/net.py $(filter-out $@,$(MAKECMDGOALS))
psql:         ## open a psql shell
	docker exec -it portfolio_db psql -U portfolio
reset:        ## drop + recreate schema (destructive)
	$(AL) downgrade base && $(AL) upgrade head

setup: db-up migrate seed ingest prices   ## one-shot local bring-up
