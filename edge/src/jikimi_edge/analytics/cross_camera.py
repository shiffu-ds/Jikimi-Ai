"""Cross-camera bike trajectories (F2 Tier 2, plan Section 8.3).

Finished bike tracks of every camera on this edge are linked into one *global trajectory* when
the appearance matches (re-ID descriptor, same rider count) and the gap fits the camera graph (no
faster than the typical travel time minus 3 std). Each new segment - camera, dwell, gap, speed,
turns, time of day - re-scores the trajectory with the trajectory transformer (ONNX): the mean
negative log-likelihood of each segment given the others, i.e. how unusual this route is for the
site. The score is calibrated like the plugins' (``loitering_xcam`` set), so the alert says "rarer
than p of this site's normal routes", and a scout circling gate -> street -> gate is caught
before he stops anywhere for long.

Training and serving share ``segment_features`` (the ST-GCN taught us what a mismatch costs).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..tracking.reid import cosine

NUM_CONT = 6  # log dwell, log gap, speed, turns, sin(time of day), cos(time of day)
MIN_SEGMENTS = 3
MAX_LEN = 16  # the exported model's fixed length (padded)


@dataclass(frozen=True)
class Segment:
    camera: str
    start: float
    end: float
    speed: float
    """Median image speed while in view (fractions of the frame width per second)."""
    turns: int
    """Direction reversals while in view (u-turns, back and forth)."""
    tod_h: float
    """Local time of day of ``start``, in hours."""


def segment_features(seg: Segment, prev_end: float | None) -> np.ndarray:
    dwell = max(seg.end - seg.start, 0.0)
    gap = 0.0 if prev_end is None else max(seg.start - prev_end, 0.0)
    angle = 2 * math.pi * seg.tod_h / 24.0
    return np.asarray(
        [
            math.log1p(dwell) / 5.0,
            math.log1p(gap) / 7.0,
            min(seg.speed, 1.0) * 4.0,
            min(seg.turns, 6) / 3.0,
            math.sin(angle),
            math.cos(angle),
        ],
        dtype=np.float32,
    )


def encode(segments: list[Segment], cameras: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """``(camera indices (L,), continuous features (L, 6))`` for the model."""
    index = {c: i for i, c in enumerate(cameras)}
    cams = np.asarray([index.get(s.camera, 0) for s in segments], dtype=np.int64)
    prev: list[float | None] = [None, *(s.end for s in segments[:-1])]
    cont = np.stack([segment_features(s, p) for s, p in zip(segments, prev, strict=True)])
    return cams, cont


def turns_of(xs: list[float], min_step: float = 0.01) -> int:
    """Direction reversals in a horizontal path (noise below ``min_step`` ignored)."""
    turns, direction, anchor = 0, 0, xs[0] if xs else 0.0
    for x in xs[1:]:
        step = x - anchor
        if abs(step) < min_step:
            continue
        d = 1 if step > 0 else -1
        if direction and d != direction:
            turns += 1
        direction, anchor = d, x
    return turns


@dataclass
class Trajectory:
    gid: str
    riders: int
    descriptor: np.ndarray | None
    segments: list[Segment] = field(default_factory=list)
    color: str | None = None
    max_score: float = -math.inf
    """Highest score after any segment so far: one route is one calibration unit."""

    @property
    def end(self) -> float:
        return self.segments[-1].end

    @property
    def span_s(self) -> float:
        return self.segments[-1].end - self.segments[0].start


class CrossCameraLinker:
    def __init__(
        self,
        graph: list[dict[str, Any]],
        threshold: float = 0.9,
        window_s: float = 1800.0,
        max_segments: int = 16,
    ) -> None:
        self.travel: dict[tuple[str, str], tuple[float, float]] = {}
        for g in graph:
            mean, std = float(g.get("mean_s", 30.0)), float(g.get("std_s", 10.0))
            self.travel[(g["from"], g["to"])] = self.travel[(g["to"], g["from"])] = (mean, std)
        self.threshold = threshold
        self.window_s = window_s
        self.max_segments = max_segments
        self._open: dict[str, Trajectory] = {}
        self._counter = 0

    def _fits(self, traj: Trajectory, camera: str, start: float) -> bool:
        gap = start - traj.end
        if gap < 0 or gap > self.window_s:
            return False
        last = traj.segments[-1].camera
        if last == camera:
            return gap >= 4.0  # a re-entry on the same camera (the per-camera linker's rule)
        mean, std = self.travel.get((last, camera), (30.0, 15.0))
        return gap >= max(mean - 3 * std, 0.0)  # cannot be faster than the road allows

    def add(
        self,
        camera: str,
        seg: Segment,
        descriptor: np.ndarray | None,
        riders: int,
        color: str | None = None,
    ) -> Trajectory:
        """Append a finished bike track to the best matching open trajectory, or start one."""
        self._expire(seg.start)
        best, best_sim = None, self.threshold
        if descriptor is not None:
            for t in self._open.values():
                if t.descriptor is None or (riders and t.riders and riders != t.riders):
                    continue
                if not self._fits(t, camera, seg.start):
                    continue
                sim = cosine(descriptor, t.descriptor)
                if sim >= best_sim:
                    best, best_sim = t, sim
        if best is None:
            self._counter += 1
            best = Trajectory(gid=f"xcam:{self._counter}", riders=riders, descriptor=descriptor, color=color)
            self._open[best.gid] = best
        best.segments = [*best.segments, seg][-self.max_segments :]
        best.riders = best.riders or riders
        best.color = best.color or color
        return best

    def _expire(self, now: float) -> None:
        for gid in [g for g, t in self._open.items() if now - t.end > self.window_s]:
            del self._open[gid]


class TrajectoryScorer:
    """Leave-one-out masked NLL of a trajectory under the ONNX trajectory transformer."""

    def __init__(self, model_path: str, cameras: list[str]) -> None:
        import onnxruntime as ort

        self.cameras = cameras
        self._s = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.mask_id = len(cameras)

    def __call__(self, segments: list[Segment]) -> float:
        segments = segments[-MAX_LEN:]
        cams, cont = encode(segments, self.cameras)
        n = len(segments)
        nll = []
        for i in range(n):
            c = np.zeros((1, MAX_LEN), np.int64)
            x = np.zeros((1, MAX_LEN, NUM_CONT), np.float32)
            pad = np.ones((1, MAX_LEN), bool)
            c[0, :n], x[0, :n], pad[0, :n] = cams, cont, False
            c[0, i], x[0, i] = self.mask_id, 0.0
            logits, mu, logvar = self._s.run(None, {"cams": c, "cont": x, "pad": pad})
            lg = logits[0, i] - logits[0, i].max()
            ce = float(np.log(np.exp(lg).sum()) - lg[cams[i]])
            var = np.exp(logvar[0, i])
            gauss = float(0.5 * (logvar[0, i] + (cont[i] - mu[0, i]) ** 2 / var + math.log(2 * math.pi)).sum())
            nll.append(ce + gauss)
        return float(np.mean(nll))
