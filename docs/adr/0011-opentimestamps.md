# ADR-0011: OpenTimestamps for public time anchoring

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F8, G23

## Context
Admins could otherwise back-date or alter evidence.

## Decision
Daily RFC 6962 Merkle root of manifest hashes is stamped with OpenTimestamps (Bitcoin) when the `ots` client is installed.

## Consequences
Free and independent; confirmation takes hours, so the portal shows 'pending' until then.
