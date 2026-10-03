#!/usr/bin/env bash
# Rounds of enrich.py until the user's limit: a 5 h stop waits for the window to reset and goes on;
# a 7-day stop, a finished queue or any other stop ends the loop. Then verify_discovery.py runs once.
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1 DATABASE_URL="postgresql+psycopg://biker@127.0.0.1:6543/biker"
export PGPASSFILE="$(cygpath -w ../../backend/gcp-prod-pgpass.conf)"
PY=../../backend/.venv/Scripts/python.exe
LOG=runs/loop.log
round=1
while true; do
  echo "LOOP round $round start $(date '+%F %T')" >> "$LOG"
  "$PY" enrich.py --allow-remote --batch 5 --since 2026-10-02T12:00 >> "$LOG" 2>&1
  last=$(grep "^queue:" "$LOG" | tail -1)
  echo "LOOP round $round end $(date '+%F %T') | $last" >> "$LOG"
  case "$last" in
    *"stopped: 5h usage"*)
      echo "LOOP waiting for the 5h window (checking every 15 min)" >> "$LOG"
      sleep 900
      until "$PY" -c "import enrich,sys; u,w=enrich.Guard(101,101)._read(); sys.exit(0 if u < 70 else 1)" 2>/dev/null; do
        sleep 900
      done ;;
    *) break ;;
  esac
  round=$((round + 1))
done
echo "LOOP finished $(date '+%F %T')" >> "$LOG"
"$PY" verify_discovery.py --allow-remote --since 2026-10-02T12:00 --recheck 20 >> "$LOG" 2>&1
echo "LOOP verify exit $? $(date '+%F %T')" >> "$LOG"
