#!/usr/bin/env bash
# Chaos: cut the edge's link to the server for N seconds (no root needed: the sync agent honours
# data/edge/OFFLINE). High-severity alerts must arrive by SMS (data/edge/sms/outbox.jsonl) within
# ~5-8 s and be synced when the link returns. For a real cut use: sudo iptables -A OUTPUT -p tcp --dport 8000 -j DROP
set -euo pipefail
SECS="${1:-120}"
touch data/edge/OFFLINE
echo "link DOWN for ${SECS}s - watch: tail -f data/edge/sms/outbox.jsonl"
sleep "$SECS"
rm -f data/edge/OFFLINE
echo "link UP - backlog: $(sqlite3 data/edge/outbox.db "select count(*) from outbox where status in ('pending','sms_sent')")"
