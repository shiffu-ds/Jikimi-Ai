#!/usr/bin/env bash
# Chaos: simulate a power cut on the edge (kill -9, no clean shutdown), then "power returns".
# Acceptance (plan F4): 0 high-severity alerts lost; alerts flowing again < 120 s (laptop).
# Run while `make demo` (or `make edge`) is running. DEV MACHINE ONLY.
set -euo pipefail
CUTS="${1:-5}"
for i in $(seq 1 "$CUTS"); do
  pid=$(pgrep -f "jikimi_edge .*run" | head -1 || true)
  [ -z "$pid" ] && { echo "edge not running"; exit 1; }
  before=$(sqlite3 data/edge/outbox.db "select count(*) from outbox where kind='alert'")
  echo "[$i/$CUTS] power cut: kill -9 $pid (alerts in outbox: $before)"
  kill -9 "$pid"
  sleep "$(( (RANDOM % 5) + 2 ))"
  start=$(date +%s)
  (uv run python -m jikimi_edge --config edge/config/site.demo.yaml run >> data/logs/edge-chaos.log 2>&1 &)
  until sqlite3 data/edge/outbox.db "select 1" >/dev/null 2>&1 && pgrep -f "jikimi_edge .*run" >/dev/null; do sleep 1; done
  echo "    restarted in $(( $(date +%s) - start ))s; alerts kept: $(sqlite3 data/edge/outbox.db "select count(*) from outbox where kind='alert'") (>= $before)"
  sleep 20
done
echo "dead (undeliverable) items: $(sqlite3 data/edge/outbox.db "select count(*) from outbox where status='dead'")"
