#!/bin/bash
# Overwrite the local docker DB with an exact copy of production. Invoked by `make
# sync-from-prod`, which resolves SOURCE_DATABASE_URL from .env.local the same way NEON_ENV
# does (never expanded by make, never echoed) and leaves DEST_DATABASE_URL at its default
# below unless a test harness overrides it.
#
# Production is read-only throughout: every session opened against SOURCE_DATABASE_URL carries
# PGOPTIONS='-c default_transaction_read_only=on', and nothing here ever writes through it.
# pg_dump refuses to dump a server newer than itself, and Neon's major version moves ahead of
# whatever this repo's docker-compose.yml is pinned to — so when the source is newer than the
# pg_dump on PATH, the dump runs inside a `postgres:<major>-alpine` container instead (network
# access to the source, not a mount), matching the server it's reading.
set -euo pipefail

: "${SOURCE_DATABASE_URL:?sync_from_prod.sh: SOURCE_DATABASE_URL not set}"
DEST_DATABASE_URL="${DEST_DATABASE_URL:-postgresql://portfolio:portfolio@localhost:5544/portfolio}"

case "$DEST_DATABASE_URL" in
  *localhost*|*127.0.0.1*) ;;
  *) echo "FATAL: destination is not the local docker DB — refusing" >&2; exit 1 ;;
esac

if [ "${CONFIRM:-}" != "1" ]; then
  echo "This replaces every row in the local docker DB with a copy of production." >&2
  echo "Anything local-only since the last sync (a hand-run ingest, a test fixture) is lost." >&2
  printf "Type 'yes' to continue (or set CONFIRM=1): " >&2
  read -r reply
  if [ "$reply" != "yes" ]; then
    echo "Aborted — no changes made." >&2
    exit 1
  fi
fi

DUMP_FILE="$(mktemp -t sync-from-prod)"
trap 'rc=$?; rm -f "$DUMP_FILE"; exit $rc' EXIT

RO='-c default_transaction_read_only=on'

source_version_num=$(PGOPTIONS="$RO" psql "$SOURCE_DATABASE_URL" -tAc 'show server_version_num' | tr -d '[:space:]')
case "$source_version_num" in
  ''|*[!0-9]*) echo "FATAL: could not read production's server version — check the connection" >&2; exit 1 ;;
esac
source_major=$(( source_version_num / 10000 ))
local_major=$(pg_dump --version | grep -oE '[0-9]+' | head -1)

# host.docker.internal rewrite only matters for a loopback stand-in (tests) or a loopback
# DEST_DATABASE_URL — a real Neon hostname is untouched.
to_docker_url() { printf '%s' "$1" | sed -E 's#(@|//)(localhost|127\.0\.0\.1)([:/]|$)#\1host.docker.internal\3#'; }

if [ "$source_major" -gt "$local_major" ]; then
  # pg_restore must be at least as new as the pg_dump that wrote the archive, so both tools
  # run from the same version-matched image once a mismatch is detected.
  echo "note: production is Postgres $source_major, local tools are $local_major — running pg_dump/pg_restore via postgres:$source_major-alpine" >&2
  docker run --rm -e PGOPTIONS="$RO" "postgres:${source_major}-alpine" \
    pg_dump --format=custom --no-owner --no-privileges --dbname="$(to_docker_url "$SOURCE_DATABASE_URL")" \
    > "$DUMP_FILE"
  # The target server is genuinely $local_major, so a dump written by a newer pg_dump can
  # carry a handful of session-setup SETs for GUCs that don't exist yet on it (e.g.
  # transaction_timeout, new in 17) — pg_restore itself treats those as non-fatal and
  # continues, but still exits non-zero, so check the log rather than failing on sight.
  restore_log="$(mktemp -t sync-from-prod-restore-log)"
  if ! docker run --rm -i "postgres:${source_major}-alpine" \
      pg_restore --clean --if-exists --no-owner --no-privileges \
      --dbname="$(to_docker_url "$DEST_DATABASE_URL")" < "$DUMP_FILE" 2> "$restore_log"; then
    if grep -Evq 'unrecognized configuration parameter|errors ignored on restore:|^Command was:' "$restore_log"; then
      cat "$restore_log" >&2
      rm -f "$restore_log"
      exit 1
    fi
    n=$(grep -c 'unrecognized configuration parameter' "$restore_log") || n=0
    echo "note: ignored $n harmless session-GUC warning(s) — the dump is newer than the local server and reset a few settings it doesn't have yet" >&2
  fi
  rm -f "$restore_log"
else
  PGOPTIONS="$RO" pg_dump --format=custom --no-owner --no-privileges \
    --dbname="$SOURCE_DATABASE_URL" -f "$DUMP_FILE"
  pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$DEST_DATABASE_URL" "$DUMP_FILE"
fi

summary=$(psql "$DEST_DATABASE_URL" -tAc "
  select 'txn=' || (select count(*) from txn)
      || ' dividend=' || (select count(*) from dividend)
      || ' cash_txn=' || (select count(*) from cash_txn)
      || ' nw_snapshot=' || (select count(*) from nw_snapshot)
")
echo "synced from production: $summary"
