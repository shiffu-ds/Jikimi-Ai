# ADR-0002: Inference backend abstraction (OpenVINO / ONNX Runtime / TensorRT)

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F5, F6, G20

## Context
Development happens on an Intel i5-6200U laptop; pilots may use Intel mini PCs or Jetson devices.

## Decision
All models run through `jikimi-ml-runtime` (`load_engine(path, backend)`); the profile in `edge/config/models.yaml` picks files and backends.

## Consequences
One code path for every device; TensorRT engines must be built on the Jetson itself.
