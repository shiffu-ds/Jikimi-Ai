# ADR-0019: Torch-free edge runtime

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-23
- **Feature / gap:** F5, G20

## Context
Running Ultralytics on the edge pulls PyTorch (~1.5 GB) onto every device.

## Decision
Models are exported once (Ultralytics/PyTorch on Kaggle or the laptop); the edge decodes YOLO11 and YOLO26 outputs with numpy and tracks with a compact ByteTrack.

## Consequences
Smaller images and RAM; export becomes an explicit, versioned step.
