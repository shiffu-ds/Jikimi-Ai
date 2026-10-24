# ADR-0007: Event bus: in-process now, Redis Streams for scale-out

- **Status:** accepted (revised in v2.4)
- **Date:** 2026-10-23
- **Feature / gap:** G39

## Context
The plan specified Redis Streams. A single API replica does not need a broker, and WebSocket fan-out must reach the process holding the sockets.

## Decision
v0.1 runs workers in-process (escalation timers and verify timeouts are database-driven, so restarts lose nothing). Redis Streams + pub/sub is introduced when the API needs more than one replica.

## Consequences
Simpler pilot deployment; scale-out is a planned change, not a rewrite (side effects already go through one `Effects` dispatcher).
