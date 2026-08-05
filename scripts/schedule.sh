#!/bin/bash
# Install / remove / inspect the launchd agents that keep the deployed database fresh.
#
#   com.portfolio.prices      daily 06:15 SGT   make prices      (Yahoo closes + FX + Endowus NAV)
#   com.portfolio.ingest-all  Sunday 07:00 SGT  make ingest-all  (statements -> txn/dividend,
#                                                                 spending, prices, snapshots)
#
# Why local and not only in the cloud: every source but Yahoo is a PDF/CSV under data/, which
# is gitignored and so exists on this machine alone. Dividends in particular are parsed out of
# broker statements — nothing off this laptop can produce them. The Vercel Cron in vercel.json
# is the backstop for prices only, for the days the laptop is shut.
#
# Missed runs: StartCalendarInterval fires on wake if the machine was asleep at the time (once,
# coalesced — not once per missed occurrence). If it was powered off, at next login. Every
# target is idempotent, so a catch-up run and a duplicate run are both harmless.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/portfolio"
DOMAIN="gui/$(id -u)"
JOBS=("prices" "ingest-all")

plist_path() { echo "$AGENTS/com.portfolio.$1.plist"; }

# $1 job, $2.. the StartCalendarInterval keys
write_plist() {
  local job="$1"; shift
  cat >"$(plist_path "$job")" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.portfolio.$job</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/scripts/scheduled_run.sh</string>
    <string>$job</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key>
  <dict>
$*
  </dict>
  <!-- the run script logs to $LOGS/<job>.log itself; this catches anything that dies before
       it gets that far (a missing interpreter, a bad path). -->
  <key>StandardOutPath</key><string>$LOGS/com.portfolio.$job.launchd.log</string>
  <key>StandardErrorPath</key><string>$LOGS/com.portfolio.$job.launchd.log</string>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLIST
}

cal() { printf '    <key>%s</key><integer>%s</integer>\n' "$@"; }

install() {
  mkdir -p "$AGENTS" "$LOGS"
  [ -f "$ROOT/.env.local" ] || { echo "no .env.local — run: vercel env pull .env.local"; exit 1; }
  chmod +x "$ROOT/scripts/scheduled_run.sh"

  write_plist prices     "$(cal Hour 6; cal Minute 15)"
  write_plist ingest-all "$(cal Weekday 0; cal Hour 7; cal Minute 0)"

  for job in "${JOBS[@]}"; do
    launchctl bootout "$DOMAIN/com.portfolio.$job" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$(plist_path "$job")"
    launchctl enable "$DOMAIN/com.portfolio.$job"
    echo "installed com.portfolio.$job -> $(plist_path "$job")"
  done
  echo
  echo "logs:      $LOGS/{prices,ingest-all}.log"
  echo "run now:   make schedule-test        # runs the prices job immediately"
}

uninstall() {
  for job in "${JOBS[@]}"; do
    launchctl bootout "$DOMAIN/com.portfolio.$job" 2>/dev/null || true
    rm -f "$(plist_path "$job")"
    echo "removed com.portfolio.$job"
  done
}

status() {
  for job in "${JOBS[@]}"; do
    echo "--- com.portfolio.$job"
    if launchctl print "$DOMAIN/com.portfolio.$job" 2>/dev/null |
         grep -E '^\s+(state|path|last exit code|runs) ='; then :; else echo "  not loaded"; fi
    tail -n 3 "$LOGS/$job.log" 2>/dev/null | sed 's/^/  /' || true
  done
}

case "${1:-}" in
  install)   install ;;
  uninstall) uninstall ;;
  status)    status ;;
  # kickstart -k restarts the job now; the calendar schedule is unaffected.
  test)      launchctl kickstart -k "$DOMAIN/com.portfolio.${2:-prices}" &&
             echo "kicked com.portfolio.${2:-prices} — tail $LOGS/${2:-prices}.log" ;;
  *) echo "usage: $0 {install|uninstall|status|test [prices|ingest-all]}"; exit 2 ;;
esac
