.PHONY: db-up db-down migrate seed flat load prices ingest api web build-web app psql reset net \
        flat-cash load-cash spending snapshot snapshot-commit ingest-all

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

ingest: flat seed load   ## full ingest: statements -> flat -> seed -> DB
	@# seed runs BETWEEN flat and load: it reads build/ledger.csv for the ticker->market
	@# mapping, and load silently drops trades whose ticker has no security row yet. A
	@# statement introducing a new ticker (e.g. FSM's first Bursa buy) needs both, in order.

flat-cash:    ## parse bank/card statements -> classified spending ledger (build/cash_ledger.csv)
	$(PY) build/parse_cash.py
	$(PY) build/classify_cash.py
load-cash:    ## load the spending ledger into DB (idempotent)
	$(PY) -m ingestion.load_cash
spending: flat-cash load-cash   ## full spending ingest: statements -> classify -> DB
	@echo "spending ingested. (HSBC scanned PDFs are vision-extracted to build/hsbc_extracted.csv)"

snapshot:     ## preview net-worth snapshots for DBS months newer than latest (dry-run)
	$(PY) scripts/snapshot_from_statements.py --all-new
snapshot-commit:   ## write those new net-worth snapshots to DB (forward-delta)
	$(PY) scripts/snapshot_from_statements.py --all-new --commit

ingest-all:   ## delta-ingest EVERY source: brokers + spending + prices + net-worth snapshots (all idempotent)
	$(MAKE) ingest        # tiger-prime, tiger-cash-boost, moomoo, fsm, cdp-statements, endowus -> txn/dividend
	$(MAKE) spending      # dbs-cc, trust-cc, dbs-consolidated -> spending ledger
	-$(MAKE) prices       # endowus NAV + FX (needs network; non-fatal if offline)
	$(MAKE) snapshot-commit   # new DBS months (+ tiger-prime) -> net-worth snapshots

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
