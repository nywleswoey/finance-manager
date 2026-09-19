.PHONY: db-up db-down migrate seed flat load prices ingest api web build-web app psql reset net \
        flat-cash load-cash spending snapshot snapshot-commit ingest-all test-web capture-web-fixtures \
        api-local \
        schedule-install schedule-status schedule-uninstall schedule-test sync-requirements

PY = PYTHONPATH=. .venv/bin/python
AL = PYTHONPATH=. .venv/bin/alembic

db-up:        ## start postgres
	docker compose up -d
db-down:      ## stop postgres
	docker compose down
migrate:      ## apply alembic migrations
	@$(LOCAL_GUARD)
	$(AL) upgrade head
seed:         ## seed accounts / securities / aliases / corporate actions / net-worth catalogue
	$(PY) scripts/seed.py
	@# nw_item must exist before any snapshot: create_snapshot writes one value per catalogue
	@# item, so an unseeded catalogue yields a snapshot with zero values and an empty breakdown.
	$(PY) scripts/seed_networth.py

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

schedule-install:   ## install the launchd agent: ingest-all daily 06:15
	@# Runs against the DEPLOYED (Neon) database, not the local docker one — the point of
	@# scheduling is that the site is fresh without you. See DEPLOY.md §6.
	scripts/schedule.sh install
schedule-status:    ## is the agent loaded, when did it last run, what did it say
	@scripts/schedule.sh status
schedule-uninstall: ## remove the agent
	scripts/schedule.sh uninstall
schedule-test:      ## run the agent right now
	scripts/schedule.sh test

# The local API reads the DEPLOYED Neon DB (DATABASE_URL from .env.local) so local shows the same
# data as prod. Only `api`/`app` do: every other make target — reset, migrate, seed, ingest,
# tests — stays on the docker DB via .env, so no destructive make TARGET can reach prod. The
# running `api`/`app` server is a different matter: it serves mutating routes (refresh, snapshot
# POST/PATCH/DELETE, the spending classify/recurring writes) against the deployed DB, and a local
# DEV_AUTH_BYPASS authorises every localhost request. Deleting a snapshot in the local UI deletes
# it in prod.
# The URL carries the password, so it is read inside the recipe's shell and never expanded by make:
# `make -n` / `make -d` show only the sed, never the value.
NEON_ENV = u=$$(sed -nE 's/^DATABASE_URL="?([^"]*)"?$$/\1/p' .env.local 2>/dev/null); test -n "$$u" || { echo "FATAL: no DATABASE_URL in .env.local (vercel env pull)"; exit 1; }
# An exported DATABASE_URL beats .env, so it would reach reset/migrate/api-local. Refuse a
# non-localhost one, as scripts/scheduled_run.sh does in the other direction. Unset is fine.
LOCAL_GUARD = case "$$DATABASE_URL" in ""|*localhost*|*127.0.0.1*) ;; *) echo "FATAL: DATABASE_URL in the environment is not the local docker DB — refusing"; exit 1 ;; esac

api:          ## run the API against Neon (serves built web/ at /)
	@$(NEON_ENV); DATABASE_URL="$$u" $(PY) -m uvicorn server.main:app --reload --port 8000
# The other half of the split above. `ingest-all` typed by hand writes the DOCKER db (config.py
# falls back to its localhost default, or .env's localhost URL), while `api` reads Neon —
# so a hand-run ingest is invisible from `api` until the 06:15 agent repeats it against the
# deployed db. This target is how you look at what you just ingested, without a write path to
# prod existing anywhere near it. Different port so it can run BESIDE `api`: the question is
# usually "is the new statement in there", and that is answered by comparing the two.
# Serves its own built web/dist (run `make build-web` first); the vite dev server proxies to 8000.
api-local:    ## run the API against the local docker DB (what a hand-run ingest wrote)
	@$(LOCAL_GUARD)
	$(PY) -m uvicorn server.main:app --reload --port 8001
build-web:    ## build the React frontend
	cd web && npm install && npm run build
app: build-web   ## build frontend then run API+web on :8000, against Neon
	@$(NEON_ENV); DATABASE_URL="$$u" $(PY) -m uvicorn server.main:app --port 8000

test-web: build-web   ## Playwright viewport suite: 10 named viewports x 13 views (see web/TESTING.md)
	@# Runs against the production build through vite's preview server, not the dev server,
	@# so the suite tests what ships. Every API call is served from web/tests/fixtures — no
	@# database, no network. First run on a machine needs `cd web && npx playwright install chromium`.
	cd web && npx playwright test

capture-web-fixtures:   ## re-derive the suite's fixtures from the live DB (needs the API running)
	@# Rarely. Regenerating re-tethers every measured assertion to whatever the DB holds
	@# today — read the docstring in the script before running it.
	$(PY) scripts/capture_web_fixtures.py --base http://localhost:8000

sync-requirements:   ## re-pin requirements.txt from uv.lock (only when CI reports drift)
	@# Two manifests, one resolver: uv.lock resolves everything, requirements.txt is the
	@# runtime subset Vercel installs. NOT a step for dependabot PRs — it updates both files
	@# itself. This is for a hand-run `uv lock`, which is how the lockfile once ended up with
	@# no entry for anthropic while requirements.txt pinned it.
	$(PY) scripts/sync_requirements.py

net:          ## per-ticker net verdict (+/-) incl dividends + option premiums
	$(PY) scripts/net.py $(filter-out $@,$(MAKECMDGOALS))
psql:         ## open a psql shell
	docker exec -it portfolio_db psql -U portfolio
reset:        ## drop + recreate schema (destructive)
	@$(LOCAL_GUARD)
	$(AL) downgrade base && $(AL) upgrade head

setup: db-up migrate seed ingest prices   ## one-shot local bring-up
