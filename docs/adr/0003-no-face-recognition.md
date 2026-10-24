# ADR-0003: No face recognition, ever

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** G11, G26, G27

## Context
Helmets and face covers defeat face recognition; Pakistan has no enacted PDP law; FR creates legal and social risk.

## Decision
No face templates are computed or stored. Face/demographic plugins are blocklisted in the plugin registry. Re-ID entities are anonymous and expire.

## Consequences
Privacy is a selling point (no FR, blur by default). Cross-camera linking must rely on appearance and timing, which is weaker (risk R6).
