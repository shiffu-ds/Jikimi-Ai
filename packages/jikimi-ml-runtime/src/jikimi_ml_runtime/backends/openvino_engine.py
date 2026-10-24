from __future__ import annotations

import numpy as np

from ..engine import EngineUnavailableError


class OpenVINOEngine:
    name = "openvino"

    def __init__(self, xml_path: str, device: str = "CPU", threads: int | None = None) -> None:
        try:
            import openvino as ov
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise EngineUnavailableError("pip install 'jikimi-ml-runtime[openvino]'") from exc
        core = ov.Core()
        model = core.read_model(xml_path)
        config: dict[str, str] = {"PERFORMANCE_HINT": "LATENCY"}
        if threads:
            config["INFERENCE_NUM_THREADS"] = str(threads)
        self._compiled = core.compile_model(model, device, config)
        shape = self._compiled.inputs[0].get_partial_shape()
        self.input_shape = tuple(int(d.get_length()) if d.is_static else -1 for d in shape)

    def infer(self, batch: np.ndarray) -> list[np.ndarray]:
        result = self._compiled(batch)
        return [np.asarray(result[out]) for out in self._compiled.outputs]
