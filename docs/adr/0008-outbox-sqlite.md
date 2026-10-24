# ADR-0008: Outbox on SQLite (WAL, synchronous=FULL)

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F4

## Context
Power cuts must not lose a committed alert.

## Decision
Every message is written to the edge outbox first and delivered idempotently (dedupe on alert id).

## Consequences
0 lost alerts in the offline tests; outbox backlog is visible in the dashboard.
