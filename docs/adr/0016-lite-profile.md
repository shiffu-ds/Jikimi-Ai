# ADR-0016: Lite profile for daily development

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-23
- **Feature / gap:** R13

## Context
The compose memory limits add up to ~9 GB + ~3 GB OS on a machine with ~10 GB usable.

## Decision
`make demo` runs API + dashboard + simulated edge in two processes with SQLite and local storage (~1 GB).

## Consequences
Every feature can be demonstrated on the laptop; compose remains for integration and pilots.
