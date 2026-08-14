#!/bin/bash
# Run one make target against the DEPLOYED database, unattended, from launchd.
#
# Two things make a scheduled run different from typing the same target yourself:
#
#   the environment — launchd starts a job with almost none. No login shell, no profile, a
#   PATH of /usr/bin:/bin, and the working directory is /. Anything the ingest shells out to
#   (pdftotext for every PDF statement and the Endowus NAV, python3 for the build/ parsers)
#   has to be findable from the PATH set here, not from the one you have interactively.
#
#   the database — `make ingest` with no DATABASE_URL writes to the local docker DB, because
#   that is config.py's default and .env sets nothing. A scheduled job that did that would
#   run green forever while the deployed site went stale. That happened once by hand; this
#   script resolves the deployed URL explicitly and refuses to run against a local one.
#
# Usage: scripts/scheduled_run.sh <make-target>     (installed by scripts/schedule.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JOB="${1:?usage: scheduled_run.sh <make-target>}"
LOG_DIR="$HOME/Library/Logs/portfolio"
LOG="$LOG_DIR/$JOB.log"

# Homebrew first: pdftotext (poppler) and python3 both live there, and neither is in the
# PATH launchd hands us.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$LOG_DIR"
# launchd never rotates anything it is given; keep one generation and cap the live log.
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 1048576 ]; then mv -f "$LOG" "$LOG.1"; fi
exec >>"$LOG" 2>&1

say() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

cd "$ROOT"

# .env.local is the file `vercel env pull` writes, and the only place the Neon URL lives.
# Unpooled by preference: ingest holds one long session, which is what the non-pooler
# endpoint is for.
if [ ! -f .env.local ]; then
  say "FATAL: no .env.local — cannot resolve the deployed database (vercel env pull)"
  exit 1
fi
set -a; . ./.env.local; set +a
export DATABASE_URL="${DATABASE_URL_UNPOOLED:-${DATABASE_URL:-}}"

case "$DATABASE_URL" in
  "")                     say "FATAL: no DATABASE_URL in .env.local"; exit 1 ;;
  *localhost*|*127.0.0.1*) say "FATAL: DATABASE_URL is the local docker DB — refusing"; exit 1 ;;
esac

# Stay awake for the whole run. launchd wakes the Mac to *start* a StartCalendarInterval job
# and then lets it go straight back to sleep — on 2026-08-14 this script logged its first line
# at 06:18:47 and the power log recorded "Sleep Service Back to Sleep" at 06:18:48, two seconds
# in. What follows is a stutter of 45-second DarkWakes, and the connection to Neon does not
# survive it. `-i` holds off idle sleep and is the one that matters here, because the machine
# runs this on battery; `-s` covers the AC case. Each flag is ignored where it doesn't apply.
#
# The ceiling is for the run that hangs anyway. A dead socket once kept one going for 50452s —
# long enough to still be holding the log when the next night's run arrived. Better a failure
# at 30 minutes, which launchd will simply try again tomorrow.
MAX_SECS="${INGEST_MAX_SECS:-1800}"
runner=(caffeinate -is make "$JOB")
# coreutils' timeout is not in a stock macOS; skip the ceiling rather than fail to run at all.
if command -v timeout >/dev/null 2>&1; then
  runner=(timeout -k 30 "$MAX_SECS" "${runner[@]}")
else
  say "note: no timeout(1) on PATH — running without the ${MAX_SECS}s ceiling"
fi

say "=== $JOB -> $(printf '%s' "$DATABASE_URL" | sed -E 's#.*@([^/?]+).*#\1#')"
start=$(date +%s)
if "${runner[@]}"; then
  say "=== $JOB ok in $(( $(date +%s) - start ))s"
else
  code=$?
  # 124 is timeout(1)'s own signal that it killed the job, and it is the interesting one:
  # it means the run hung rather than errored, which is a different thing to go looking at.
  if [ "$code" -eq 124 ]; then
    say "=== $JOB TIMED OUT after ${MAX_SECS}s (killed)"
  else
    say "=== $JOB FAILED (exit $code) in $(( $(date +%s) - start ))s"
  fi
  exit "$code"
fi
