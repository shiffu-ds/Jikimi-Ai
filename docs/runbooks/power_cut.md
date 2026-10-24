# Runbook: power cut / internet outage

**What the system does by itself**
- Edge alerts are committed to the SQLite outbox before anything else (survives `kill -9`, tested).
- If a high-severity alert is not delivered within 5 s, it goes out by SMS to `GUARD_SMS_NUMBERS`.
- Guards reply `1` (seen), `2` (false alarm), `3` (need help), optionally with the code: `1 A7F2`.
- On battery the frame rate drops (profiles `battery` / `critical`), alerts keep flowing.
- systemd/Docker restart the edge after power returns; plugin state (loitering counts) is restored.

**What to check after an outage**
1. Dashboard → System health: device online, outbox backlog draining to 0, no `dead` items.
2. Alerts sent by SMS show the "SMS se bheja gaya" badge and the SMS acks in their timeline.
3. If the backlog does not drain: check `JIKIMI_SERVER_URL`, WireGuard, server `/v1/health`.

**Drill:** `eval/chaos/net_cut.sh 120` and `eval/chaos/power_cut.sh 5` (development machines only).
