# ADR-0006: PostgreSQL + pgvector (and SQLite in the lite profile)

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F1, G39

## Context
Few services fit a 12 GB laptop better than many.

## Decision
One relational store with JSONB and vector search; SQLAlchemy models run on SQLite for zero-setup development.

## Consequences
No separate vector DB. Brute-force similarity is fine at pilot scale; HNSW on halfvec(768) partitions for production scale.
