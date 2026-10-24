"""Appearance re-identification without identity (Tier-1 baseline for F2).

A bike that leaves the frame and comes back gets a *new* tracker ID. To count "chakkar" we
link re-entries with an appearance descriptor built from the *foreground* only: the bike body
and the riders' torsos (shirts). Whole-box histograms are dominated by road and wall pixels
and make every bike look alike. An OSNet / vehicle re-ID model can replace ``descriptor()``
later without touching the plugins.

Entity IDs are anonymous session labels (``cam-gate-01:mot:17``), expire with the window
(24 h retention, Section 8.3) and are never linked to names or faces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

H_BINS, S_BINS, V_BINS = 18, 3, 3
NormBox = tuple[float, float, float, float]


def _hist(crop_bgr: np.ndarray) -> np.ndarray | None:
    if crop_bgr is None or crop_bgr.size == 0 or min(crop_bgr.shape[:2]) < 3:
        return None
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    hs = cv2.calcHist([hsv], [0, 1], None, [H_BINS, S_BINS], [0, 180, 0, 256]).ravel()
    v = cv2.calcHist([hsv], [2], None, [V_BINS], [0, 256]).ravel()
    vec = np.concatenate([hs, v]).astype(np.float32)
    total = float(vec.sum())
    return np.sqrt(vec / total) if total > 0 else None  # Hellinger kernel, unit L2 norm


def _crop(frame: np.ndarray, box: NormBox, fx: tuple[float, float], fy: tuple[float, float]) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    X1, X2 = int((x1 + fx[0] * bw) * w), int((x1 + fx[1] * bw) * w)
    Y1, Y2 = int((y1 + fy[0] * bh) * h), int((y1 + fy[1] * bh) * h)
    return frame[max(Y1, 0) : max(Y2, Y1 + 1), max(X1, 0) : max(X2, X1 + 1)]


def descriptor(
    frame: np.ndarray, box: NormBox, riders: Sequence[NormBox] = (), is_person: bool = False
) -> np.ndarray | None:
    """Unit-norm foreground descriptor ``[part A | part B]`` (each half unit-norm, or zeros).

    Vehicles: A = bike body, B = mean rider torso (shirts). Persons: A = torso, B = legs.
    Matching compares the halves *separately* (see ``similarity``) so a similar bike with
    different riders, or the same shirts on a different bike, does not link.
    """
    if is_person:
        a = _hist(_crop(frame, box, (0.25, 0.75), (0.22, 0.55)))
        b = _hist(_crop(frame, box, (0.3, 0.7), (0.6, 0.9)))
    else:
        a = _hist(_crop(frame, box, (0.22, 0.78), (0.12, 0.62)))
        torsos = [t for t in (_hist(_crop(frame, r, (0.25, 0.75), (0.22, 0.55))) for r in riders) if t is not None]
        b = None
        if torsos:
            m = np.mean(torsos, axis=0)
            n = float(np.linalg.norm(m))
            b = m / n if n > 0 else None
    if a is None and b is None:
        return None
    size = (a if a is not None else b).shape[0]  # type: ignore[union-attr]
    return np.concatenate(
        [a if a is not None else np.zeros(size, np.float32), b if b is not None else np.zeros(size, np.float32)]
    )


def similarity(x: np.ndarray, y: np.ndarray) -> float:
    """Part-wise similarity: the *weakest* shared part decides (stricter than one cosine)."""
    half = x.shape[0] // 2
    sims = []
    for sl in (slice(0, half), slice(half, None)):
        xa, ya = x[sl], y[sl]
        nx, ny = float(np.linalg.norm(xa)), float(np.linalg.norm(ya))
        if nx > 0 and ny > 0:
            sims.append(float(np.dot(xa, ya) / (nx * ny)))
    return min(sims) if sims else 0.0


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return similarity(a, b)


@dataclass
class _Entity:
    entity_id: str
    cls: str
    descriptor: np.ndarray | None
    last_seen: float
    riders: int = 0
    active: bool = False


class EntityLinker:
    def __init__(
        self, camera_id: str, window_s: float = 900.0, threshold: float = 0.95, min_gap_s: float = 4.0
    ) -> None:
        self.camera_id = camera_id
        self.window_s = window_s
        self.threshold = threshold
        self.min_gap_s = min_gap_s
        self._entities: dict[str, _Entity] = {}
        self._counter = 0

    def _new_id(self, cls: str) -> str:
        self._counter += 1
        return f"{self.camera_id}:{cls[:3]}:{self._counter}"

    def assign(self, cls: str, desc: np.ndarray | None, ts: float, riders: int = 0) -> str:
        """Return the entity for a *new* track: a recent inactive look-alike or a fresh id."""
        self._expire(ts)
        best_id, best_sim = None, self.threshold
        if desc is not None:
            for ent in self._entities.values():
                if ent.active or ent.cls != cls or ent.descriptor is None or ts - ent.last_seen < self.min_gap_s:
                    continue
                if cls == "motorcycle" and riders and ent.riders and riders != ent.riders:
                    continue  # rider count changed: a different bike (or someone got off)
                sim = cosine(desc, ent.descriptor)
                if sim >= best_sim:
                    best_id, best_sim = ent.entity_id, sim
        if best_id is None:
            best_id = self._new_id(cls)
            self._entities[best_id] = _Entity(best_id, cls, desc, ts, riders)
        ent = self._entities[best_id]
        ent.active = True
        ent.last_seen = ts
        if desc is not None and ent.descriptor is None:
            ent.descriptor = desc
        return best_id

    def release(self, entity_id: str, desc: np.ndarray | None, ts: float, riders: int = 0) -> None:
        ent = self._entities.get(entity_id)
        if ent is None:
            return
        ent.active = False
        ent.last_seen = ts
        if riders:
            ent.riders = riders
        if desc is not None:
            ent.descriptor = desc if ent.descriptor is None else _blend(ent.descriptor, desc)

    def _expire(self, ts: float) -> None:
        dead = [k for k, e in self._entities.items() if not e.active and ts - e.last_seen > self.window_s]
        for k in dead:
            del self._entities[k]

    def state_dict(self) -> dict[str, object]:
        return {"counter": self._counter}

    def load_state(self, state: dict[str, object]) -> None:
        counter = state.get("counter", 0)
        self._counter = int(counter) if isinstance(counter, (int, float, str)) else 0


def _blend(old: np.ndarray, new: np.ndarray, alpha: float = 0.3) -> np.ndarray:
    v = (1 - alpha) * old + alpha * new
    half = v.shape[0] // 2
    for sl in (slice(0, half), slice(half, None)):
        n = float(np.linalg.norm(v[sl]))
        if n > 0:
            v[sl] = v[sl] / n
    return v
