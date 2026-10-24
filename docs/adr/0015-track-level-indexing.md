# ADR-0015: Activity-gated, track-level indexing

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F1

## Context
Indexing every 2 s would create ~43k rows per camera per day.

## Decision
One index row per finished vehicle track (+ every alert clip) with attributes and a blurred thumbnail.

## Consequences
~10x+ less storage; the plan's Section 8.6 '2 s segments' line is corrected in v2.4.
