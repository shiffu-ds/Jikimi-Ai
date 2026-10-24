from __future__ import annotations

import numpy as np

from ..engine import EngineUnavailableError


class ORTEngine:
    name = "onnxruntime"

    def __init__(self, onnx_path: str, threads: int | None = None) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise EngineUnavailableError("pip install 'jikimi-ml-runtime[onnx]'") from exc
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self._session = ort.InferenceSession(onnx_path, opts, providers=["CPUExecutionProvider"])
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        self.input_shape = tuple(d if isinstance(d, int) else -1 for d in inp.shape)

    def infer(self, batch: np.ndarray) -> list[np.ndarray]:
        outputs = self._session.run(None, {self._input_name: batch})
        return [np.asarray(o) for o in outputs]
