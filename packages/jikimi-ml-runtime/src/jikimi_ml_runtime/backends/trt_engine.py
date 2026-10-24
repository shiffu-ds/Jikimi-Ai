"""TensorRT backend for the Jetson profile (E2).

Engines are hardware-specific: build them on the Jetson itself
(``yolo export ... format=engine int8=True`` or ``trtexec``). This module is exercised only on
Jetson hardware; on other machines it raises ``EngineUnavailableError``.
"""

from __future__ import annotations

import numpy as np

from ..engine import EngineUnavailableError


class TRTEngine:
    name = "tensorrt"

    def __init__(self, engine_path: str) -> None:
        try:
            import tensorrt as trt  # noqa: F401
        except ImportError as exc:
            raise EngineUnavailableError("TensorRT is only available on NVIDIA devices (JetPack)") from exc
        raise EngineUnavailableError(  # pragma: no cover - needs Jetson hardware
            "TensorRT execution is enabled in the Jetson image (deploy/compose/docker-compose.edge-jetson.yml)"
        )

    input_shape: tuple[int, ...] = ()

    def infer(self, batch: np.ndarray) -> list[np.ndarray]:  # pragma: no cover
        raise NotImplementedError
