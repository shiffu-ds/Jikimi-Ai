# ADR-0020: Static dashboard export served by the API

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-23
- **Feature / gap:** -

## Context
`next start` costs ~384 MB RAM and another container.

## Decision
`next build` with `output: export`; FastAPI serves `apps/dashboard/out`; session cookie is httpOnly + SameSite=Strict with a custom header on writes.

## Consequences
Same-origin, no CORS, works offline on the LAN; dynamic routes use query strings (`/alerts/view/?id=`).
