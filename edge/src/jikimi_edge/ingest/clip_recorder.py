"""Alert clips: a 60 s JPEG ring buffer per camera and -20 s / +10 s clips on alert.

Frames are kept JPEG-encoded (~40 kB each instead of ~700 kB raw), so 60 s at 5 fps costs
~12 MB per camera. When the post-roll has been captured, the job is handed to a worker thread
that blurs, encodes, hashes, encrypts the original and signs the attestation (see pipeline).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from uuid import UUID

import cv2
import numpy as np

NormBox = tuple[float, float, float, float]


@dataclass
class BufferedFrame:
    ts: float
    jpeg: bytes
    persons: list[NormBox]


@dataclass
class ClipJob:
    alert_id: UUID
    camera_id: str
    alert_ts: float
    start: float
    end: float
    frames: list[BufferedFrame] = field(default_factory=list)


class ClipRecorder:
    def __init__(
        self, camera_id: str, pre_s: float = 20.0, post_s: float = 10.0, buffer_s: float = 60.0, quality: int = 80
    ) -> None:
        self.camera_id = camera_id
        self.pre_s = pre_s
        self.post_s = post_s
        self.buffer_s = buffer_s
        self.quality = quality
        self._buf: deque[BufferedFrame] = deque()
        self._jobs: list[ClipJob] = []
        self.latest_ts = 0.0

    def push(self, ts: float, image: np.ndarray | None, persons: list[NormBox]) -> None:
        if image is None:
            return
        ok, enc = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            return
        self._buf.append(BufferedFrame(ts, enc.tobytes(), persons))
        self.latest_ts = ts
        while self._buf and ts - self._buf[0].ts > self.buffer_s:
            self._buf.popleft()

    def request(self, alert_id: UUID, alert_ts: float, start_ts: float | None = None) -> None:
        """Clip from ``min(start_ts, alert_ts - pre_s)`` (bounded by the buffer) to ``alert_ts + post_s``."""
        if any(j.alert_id == alert_id for j in self._jobs):
            return
        start = alert_ts - self.pre_s if start_ts is None else min(start_ts, alert_ts - self.pre_s)
        start = max(start, alert_ts - self.buffer_s + self.post_s)
        self._jobs.append(ClipJob(alert_id, self.camera_id, alert_ts, start, alert_ts + self.post_s))

    def ready(self, force: bool = False) -> list[ClipJob]:
        done = [j for j in self._jobs if force or self.latest_ts >= j.end]
        for j in done:
            j.frames = [f for f in self._buf if j.start <= f.ts <= j.end]
            self._jobs.remove(j)
        return [j for j in done if j.frames]

    @property
    def buffered_s(self) -> float:
        return (self._buf[-1].ts - self._buf[0].ts) if len(self._buf) > 1 else 0.0

    def latest_jpeg(self) -> BufferedFrame | None:
        return self._buf[-1] if self._buf else None


def decode(frame: BufferedFrame) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("corrupt buffered frame")
    return img
