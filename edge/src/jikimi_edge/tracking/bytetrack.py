"""Compact ByteTrack (Zhang et al., ECCV 2022) for the real-camera path.

Two-stage association: confident detections first, then low-score detections are matched to
the remaining tracks (they are usually occluded objects, not noise). Constant-velocity Kalman
filter with *time-based* steps, because edge frames arrive at irregular intervals.
Greedy IoU matching keeps the edge free of scipy; with < 50 objects per frame it matches the
Hungarian solution in practice.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from jikimi_contracts import Detection, Track

from ..analytics.geometry import iou

_STD_POS = 1.0 / 20.0
_STD_VEL = 1.0 / 160.0


def _to_xywh(b: tuple[float, float, float, float]) -> np.ndarray:
    x1, y1, x2, y2 = b
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1], dtype=np.float64)


@dataclass
class _STrack:
    track_id: int
    cls: str
    score: float
    x: np.ndarray
    p: np.ndarray
    last_ts: float
    first_ts: float
    pred_ts: float
    hits: int = 1
    state: str = "tracked"

    @classmethod
    def start(cls, track_id: int, det: Detection, ts: float) -> _STrack:
        z = _to_xywh(det.bbox)
        x = np.concatenate([z, np.zeros(4)])
        h = max(z[3], 1e-3)
        std = np.array([2 * _STD_POS * h] * 4 + [10 * _STD_VEL * h] * 4)
        return cls(track_id, det.cls, det.conf, x, np.diag(std**2), ts, ts, ts)

    def predict(self, ts: float) -> None:
        dt = max(ts - self.pred_ts, 0.0)
        if dt == 0.0:
            return
        f = np.eye(8)
        f[0:4, 4:8] = np.eye(4) * dt
        h = max(self.x[3], 1e-3)
        q = np.diag(np.array([_STD_POS * h] * 4 + [_STD_VEL * h] * 4) ** 2) * max(dt, 1e-3) * 5
        self.x = f @ self.x
        self.x[2:4] = np.maximum(self.x[2:4], 1e-4)
        self.p = f @ self.p @ f.T + q
        self.pred_ts = ts

    def update(self, det: Detection, ts: float) -> None:
        z = _to_xywh(det.bbox)
        hm = np.zeros((4, 8))
        hm[:, :4] = np.eye(4)
        r = np.diag(np.full(4, (_STD_POS * max(z[3], 1e-3)) ** 2))
        s = hm @ self.p @ hm.T + r
        k = self.p @ hm.T @ np.linalg.inv(s)
        self.x = self.x + k @ (z - hm @ self.x)
        self.p = (np.eye(8) - k @ hm) @ self.p
        self.score = det.conf
        self.last_ts = ts
        self.hits += 1
        self.state = "tracked"

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        cx, cy, w, h = self.x[:4]
        return (float(cx - w / 2), float(cy - h / 2), float(cx + w / 2), float(cy + h / 2))


def _greedy_match(
    tracks: list[_STrack], dets: list[Detection], iou_min: float
) -> tuple[list[tuple[_STrack, Detection]], list[_STrack], list[Detection]]:
    pairs = []
    for ti, t in enumerate(tracks):
        for di, d in enumerate(dets):
            if d.cls != t.cls:
                continue
            v = iou(t.bbox, d.bbox)
            if v >= iou_min:
                pairs.append((v, ti, di))
    pairs.sort(reverse=True)
    used_t: set[int] = set()
    used_d: set[int] = set()
    matches = []
    for _, ti, di in pairs:
        if ti in used_t or di in used_d:
            continue
        used_t.add(ti)
        used_d.add(di)
        matches.append((tracks[ti], dets[di]))
    return (
        matches,
        [t for i, t in enumerate(tracks) if i not in used_t],
        [d for i, d in enumerate(dets) if i not in used_d],
    )


class ByteTracker:
    def __init__(
        self,
        high_thresh: float = 0.5,
        low_thresh: float = 0.1,
        new_track_thresh: float = 0.6,
        buffer_s: float = 2.0,
    ) -> None:
        self.high_thresh = high_thresh
        self.low_thresh = low_thresh
        self.new_track_thresh = new_track_thresh
        self.buffer_s = buffer_s
        self._tracks: list[_STrack] = []
        self._next_id = 1

    def update(self, dets: list[Detection], ts: float) -> list[Track]:
        high = [d for d in dets if d.conf >= self.high_thresh]
        low = [d for d in dets if self.low_thresh <= d.conf < self.high_thresh]
        for t in self._tracks:
            t.predict(ts)
        m1, um_tracks, um_high = _greedy_match(self._tracks, high, iou_min=0.2)
        for t, d in m1:
            t.update(d, ts)
        still_tracked = [t for t in um_tracks if t.state == "tracked"]
        m2, um2, _ = _greedy_match(still_tracked, low, iou_min=0.5)
        for t, d in m2:
            t.update(d, ts)
        for t in um2:
            t.state = "lost"
        for d in um_high:
            if d.conf >= self.new_track_thresh:
                self._tracks.append(_STrack.start(self._next_id, d, ts))
                self._next_id += 1
        self._tracks = [t for t in self._tracks if t.state == "tracked" or ts - t.last_ts <= self.buffer_s]
        out: list[Track] = []
        for t in self._tracks:
            if t.state != "tracked" or t.last_ts != ts:
                continue
            x1, y1, x2, y2 = t.bbox
            out.append(
                Track(
                    track_id=t.track_id,
                    cls=t.cls,
                    conf=float(min(max(t.score, 0.0), 1.0)),
                    bbox=(max(0.0, x1), max(0.0, y1), min(1.0, x2), min(1.0, y2)),
                    velocity=(float(t.x[4]), float(t.x[5])),
                    first_seen=t.first_ts,
                    last_seen=ts,
                )
            )
        return out
