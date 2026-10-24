# ADR-0018: Local object store instead of MinIO

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-23
- **Feature / gap:** -

## Context
MinIO community Docker images stopped in Oct 2025 and the repository was archived in Feb 2026, so pinned images get no security fixes.

## Decision
Files live in a local store keyed like S3; tamper evidence comes from hashes in signed manifests, Merkle batches and OpenTimestamps, not from bucket object lock.

## Consequences
0 MB extra RAM; an S3-compatible backend (AWS S3 Object Lock or a maintained self-hosted store) can be added behind the same three methods.
