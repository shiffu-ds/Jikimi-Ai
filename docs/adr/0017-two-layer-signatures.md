# ADR-0017: Two-layer evidence signatures

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-23
- **Feature / gap:** F8

## Context
The plan signed the evidence manifest with the device key, but manifests are built on the server and the device key must never leave the site. Clips also finish ~10 s after the alert.

## Decision
Layer 1: the edge key signs each alert immediately and each clip attestation after the post-roll. Layer 2: the server evidence key signs the manifest that embeds the layer-1 signatures.

## Consequences
Alerts stay fast (< 5 s) and the verifier can check origin (edge) and packaging (server) separately.
