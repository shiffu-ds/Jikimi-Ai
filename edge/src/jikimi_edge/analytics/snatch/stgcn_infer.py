"""ST-GCN scorer on the edge (OpenVINO / ONNX Runtime, no torch).

Input tensor (plan Section 8.2): ``(N=1, C=3, T=32, V=17, M=2)`` with channels ``(x, y, conf)``.
Improvement over plan v2.3: the window is defined in *seconds* (3.2 s) and resampled to T=32
frames, so a 5 fps laptop and a 10 fps Jetson feed the same model.
Keypoints are centred on the rider's hip midpoint and scaled by the pedestrian height.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from .pair_builder import PairSample

T_FRAMES = 32
WINDOW_S = 3.2
CONTACT_SPAN = 4  # samples either side of the closest approach, as in training


def build_input(
    samples: Sequence[PairSample], t_frames: int = T_FRAMES, window_s: float = WINDOW_S
) -> np.ndarray | None:
    usable = [s for s in samples if s.rider_kpts is not None and s.ped_kpts is not None]
    if len(usable) < 4:
        return None
    t_end = usable[-1].ts
    times = np.linspace(t_end - window_s, t_end, t_frames)
    src_t = np.array([s.ts for s in usable])
    rider = np.stack([s.rider_kpts for s in usable])  # type: ignore[misc]
    ped = np.stack([s.ped_kpts for s in usable])  # type: ignore[misc]
    out = np.zeros((1, 3, t_frames, 17, 2), dtype=np.float32)
    for m, seq in enumerate((rider, ped)):
        for c in range(3):
            for v in range(17):
                out[0, c, :, v, m] = np.interp(times, src_t, seq[:, v, c], left=0.0, right=seq[-1, v, c])
    hip = (out[0, :2, :, 11, 0] + out[0, :2, :, 12, 0]) / 2.0  # rider hip midpoint (2, T)
    scale = max(float(np.median([s.ped_height for s in usable])), 0.03)
    out[0, :2] = (out[0, :2] - hip[:, :, None, None]) / scale
    return out


class StgcnScorer:
    def __init__(self, model_path: str | Path, backend: str = "onnxruntime") -> None:
        from jikimi_ml_runtime import load_engine

        self.engine = load_engine(model_path, backend)

    def __call__(self, samples: Sequence[PairSample]) -> float | None:
        """Highest score over the windows that end near the closest approach.

        Training labels a window positive only when it ends within ``CONTACT_SPAN`` samples of the
        closest approach (``ml/.../synthetic.py``); a window cut when the pair is released, after the
        bike has gone, is what training called negative. Scoring the same windows here keeps
        training and serving aligned (measured: in-pipeline margin 0.508 vs 0.499 before).
        """
        if not samples:
            return None
        closest = min(range(len(samples)), key=lambda k: samples[k].hand_dist)
        best: float | None = None
        for end in range(max(3, closest - CONTACT_SPAN), min(len(samples), closest + CONTACT_SPAN + 1)):
            x = build_input(samples[: end + 1])
            if x is None:
                continue
            p = float(1.0 / (1.0 + np.exp(-self.engine.infer(x)[0].reshape(-1)[-1])))
            best = p if best is None else max(best, p)
        return best
