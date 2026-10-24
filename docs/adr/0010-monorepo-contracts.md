# ADR-0010: Monorepo with one contracts package

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** -

## Context
Edge, server and dashboard must never disagree about payloads.

## Decision
`packages/jikimi-contracts` holds Pydantic models; `scripts/gen_contract_types.py` generates TypeScript; CI fails on drift.

## Consequences
One source of truth; changing a contract is one PR.
