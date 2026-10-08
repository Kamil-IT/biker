#!/usr/bin/env bash
# Rounds of enrich.py until the user's limit (5 h window 60 %, 7 days 85 %): a 5 h stop waits for the
# window to reset (below 50 %) and goes on;
# an unreadable usage waits the same way; a 7-day stop, a finished queue or any other stop ends the loop. Then verify_discovery.py runs once.
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1 DATABASE_URL="postgresql+psycopg://biker@127.0.0.1:6543/biker"
export PGPASSFILE="$(cygpath -w ../../backend/gcp-prod-pgpass.conf)"
PY=../../backend/.venv/Scripts/python.exe
LOG=runs/loop.log
round=1
while true; do
  echo "LOOP round $round start $(date '+%F %T')" >> "$LOG"
  "$PY" enrich.py --allow-remote --batch 5 --stop-at 60 --since 2026-10-02T12:00 >> "$LOG" 2>&1
  last=$(grep "^queue:" "$LOG" | tail -1)
  echo "LOOP round $round end $(date '+%F %T') | $last" >> "$LOG"
  case "$last" in
    *"stopped: 5h usage"*|*"stopped: usage unreadable"*)
      # an unreadable usage (the endpoint answers 429 for a while) waits like a 5 h stop:
      # the check below only passes once the usage can be read again and is low enough
      echo "LOOP waiting for the 5h window / a readable usage (checking every 15 min)" >> "$LOG"
      sleep 900
      until "$PY" -c "import enrich,sys; u,w=enrich.Guard(101,101)._read(); sys.exit(0 if u < 50 else 1)" 2>/dev/null; do
        sleep 900
      done ;;
    *) break ;;
  esac
  round=$((round + 1))
done
echo "LOOP finished $(date '+%F %T')" >> "$LOG"
"$PY" verify_discovery.py --allow-remote --since 2026-10-02T12:00 --recheck 20 >> "$LOG" 2>&1
echo "LOOP verify exit $? $(date '+%F %T')" >> "$LOG"
