# ADR-0001: Edge-first processing

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F4, G15-G17, G28

## Context
Load-shedding and internet outages are common at small sites; bandwidth is costly; video leaving the site is a privacy risk.

## Decision
Detection, calibration, routing, clip recording and SMS fallback run on the edge. The server receives alerts, signed clips and metadata.

## Consequences
The alert path works offline (tested: SMS within ~5-8 s of an undelivered high alert). Edge hardware limits model size; VLM and search embeddings run on the server.
