"""Inference backend abstraction (ADR-002): change config, not code.

``openvino``  Intel CPU / iGPU (the i5-6200U laptop, Intel mini PCs)
``onnxruntime``  any CPU (fallback)
``tensorrt``  NVIDIA Jetson / GPU (engine files are built on the target device)

The edge runtime never imports torch: YOLO detection, pose, ST-GCN and re-ID all run through
this layer, which keeps the edge image ~1.5 GB smaller than an Ultralytics/torch runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class InferenceEngine(Protocol):
    name: str
    input_shape: tuple[int, ...]

    def infer(self, batch: np.ndarray) -> list[np.ndarray]: ...


class EngineUnavailableError(RuntimeError):
    """Backend library missing or model file not found."""


def load_engine(
    model_path: str | Path, backend: str, device: str = "CPU", threads: int | None = None
) -> InferenceEngine:
    path = Path(model_path)
    if not path.exists():
        raise EngineUnavailableError(f"model not found: {path} (run `make models`)")
    if backend == "openvino":
        from .backends.openvino_engine import OpenVINOEngine

        return OpenVINOEngine(str(path), device, threads)
    if backend == "onnxruntime":
        from .backends.ort_engine import ORTEngine

        return ORTEngine(str(path), threads)
    if backend == "tensorrt":
        from .backends.trt_engine import TRTEngine

        return TRTEngine(str(path))
    raise ValueError(f"Unknown inference backend: {backend}")


def available_backends() -> list[str]:
    found: list[str] = []
    try:
        import openvino  # noqa: F401

        found.append("openvino")
    except ImportError:
        pass
    try:
        import onnxruntime  # noqa: F401

        found.append("onnxruntime")
    except ImportError:
        pass
    try:
        import tensorrt  # noqa: F401

        found.append("tensorrt")
    except ImportError:
        pass
    return found
