# ADR-0004: Pose-based snatch model (ST-GCN), heuristic baseline first

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F3, G08

## Context
RGB video models are heavy for CPU and privacy-unfriendly; snatching has a clear kinematic signature.

## Decision
Baseline B1 = interpretable pose/box heuristic (contact, slow approach, fast departure, pedestrian jerk). ST-GCN (2-person, ~0.4 M params) replaces the score when trained; features stay for the Urdu explanation.

## Consequences
Runs on CPU via ONNX. Needs consented PakSnatch data for real accuracy; synthetic pre-training (PakSnatch-sim) helps but is not enough.
