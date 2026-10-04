#!/bin/bash
# Overwrite the local docker DB with an exact copy of production. Invoked by `make
# sync-from-prod`, which resolves SOURCE_DATABASE_URL from .env.local (unpooled by preference,
# never expanded by make, never echoed). The destination is always the docker-compose DB.
#
# Production is read-only throughout: every session opened against SOURCE_DATABASE_URL carries
# PGOPTIONS='-c default_transaction_read_only=on', and nothing here ever writes through it.
# pg_dump refuses to dump a server newer than itself, and Neon's major version moves ahead of
# whatever this repo's docker-compose.yml is pinned to — so when the source is newer than the
# pg_dump on PATH, the dump and restore run inside a `postgres:<major>-alpine` container instead
# (network access to both databases, not a mount), matching the server it's reading.
set -euo pipefail

: "${SOURCE_DATABASE_URL:?sync_from_prod.sh: SOURCE_DATABASE_URL not set}"
DEST_DATABASE_URL="postgresql://portfolio:portfolio@localhost:5544/portfolio"

if [ "${CONFIRM:-}" != "1" ]; then
  echo "This replaces everything in the local docker DB with a copy of production." >&2
  echo "Anything local-only since the last sync (a hand-run ingest, a test fixture, a migration" >&2
  echo "production doesn't have yet) is lost." >&2
  printf "Type 'yes' to continue (or set CONFIRM=1): " >&2
  read -r reply
  if [ "$reply" != "yes" ]; then
    echo "Aborted — no changes made." >&2
    exit 1
  fi
fi

DUMP_FILE="$(mktemp -t sync-from-prod)"
RESTORE_LOG="$(mktemp -t sync-from-prod-restore-log)"
trap 'rm -f "$DUMP_FILE" "$RESTORE_LOG"' EXIT

RO='-c default_transaction_read_only=on'

source_version_num=$(PGOPTIONS="$RO" psql "$SOURCE_DATABASE_URL" -tAc 'show server_version_num' | tr -d '[:space:]')
case "$source_version_num" in
  ''|*[!0-9]*) echo "FATAL: could not read production's server version — check the connection" >&2; exit 1 ;;
esac
source_major=$(( source_version_num / 10000 ))
local_major=$(pg_dump --version | grep -oE '[0-9]+' | head -1)

if [ "$source_major" -gt "$local_major" ]; then
  # pg_restore must be at least as new as the pg_dump that wrote the archive, so both tools
  # run from the same version-matched image once a mismatch is detected.
  echo "note: production is Postgres $source_major, local tools are $local_major — running pg_dump/pg_restore via postgres:$source_major-alpine" >&2
  pg_tool() { docker run --rm -i -e PGOPTIONS "postgres:${source_major}-alpine" "$@"; }
  tool_dest_url="postgresql://portfolio:portfolio@host.docker.internal:5544/portfolio"
else
  pg_tool() { "$@"; }
  tool_dest_url="$DEST_DATABASE_URL"
fi

( export PGOPTIONS="$RO"; pg_tool pg_dump --format=custom --no-owner --no-privileges \
    --dbname="$SOURCE_DATABASE_URL" ) > "$DUMP_FILE"

# --clean only drops what the dump contains; a local-only table, view or sequence would survive
# it. Start from an empty schema so the result is exactly production.
psql "$DEST_DATABASE_URL" -q -v ON_ERROR_STOP=1 -c 'drop schema public cascade; create schema public;'

# A dump written by a pg_dump newer than the docker-compose server (whether from the image
# above or a local libpq upgrade) can carry session-setup SETs for GUCs the server doesn't have
# yet (e.g. transaction_timeout, new in 17) — pg_restore treats those as non-fatal and
# continues, but still exits non-zero, so check the log rather than failing on sight.
if ! pg_tool pg_restore --no-owner --no-privileges --dbname="$tool_dest_url" \
    < "$DUMP_FILE" 2> "$RESTORE_LOG"; then
  if grep -Evq 'unrecognized configuration parameter|errors ignored on restore:|^Command was:' "$RESTORE_LOG"; then
    cat "$RESTORE_LOG" >&2
    exit 1
  fi
  n=$(grep -c 'unrecognized configuration parameter' "$RESTORE_LOG") || n=0
  echo "note: ignored $n harmless session-GUC warning(s) — the dump is newer than the local server and reset a few settings it doesn't have yet" >&2
fi

summary=$(psql "$DEST_DATABASE_URL" -tAc "
  select 'txn=' || (select count(*) from txn)
      || ' dividend=' || (select count(*) from dividend)
      || ' cash_txn=' || (select count(*) from cash_txn)
      || ' nw_snapshot=' || (select count(*) from nw_snapshot)
")
echo "synced from production: $summary"
