# ADR-0026: Admin commands reach the edge as a signed, pulled bundle (first: accept a new view)

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-24
- **Feature / gap:** F10; extends ADR-0022 / ADR-0023 (signed bundles)

## Context
After a camera is turned on purpose, the `moved` check compares every frame with a reference view
that will never match again, so the camera alarms "moved" for ever. Someone has to say "this is the
new view", but the edge opens no ports, and an unsigned "reset" would let anyone who reaches the
server silence a tamper alarm.

## Decision
- The camera-health plugin accepts the current view as its new reference either by itself, after
  the camera has stood still in the new position for `reanchor_after_s` (10 min), or on an admin's
  command. Both send a low-severity TAMPER notice ("view accepted; check the zones").
- Commands use the same channel as rules and the calendar: the server signs a `CommandBundle`
  (Ed25519, the key the edge pinned on first use), the edge pulls it, refuses older bundles, runs
  each command once (ids kept on disk across restarts) and lists what it ran in its heartbeat, after
  which the server stops sending it. Commands expire after 24 h. Only admins can issue them; every
  one is audited.

## Consequences
A moved camera needs no restart or file edit. The auto path means a thief who turns a camera and
leaves it gets only 10 minutes of "moved" alarms, then a low notice: the alarm and the notice both
reach the dashboard and the hash-chained audit log, and the notice says to check the zones. New
admin actions (e.g. restart a camera) can reuse the channel instead of opening the edge.
