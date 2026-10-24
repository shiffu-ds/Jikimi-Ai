"""Connection test for a stream before it goes into ``site.yaml`` (plan Section 8.20: resolution,
fps, bitrate, packet loss; use the sub-stream when the main one is heavy or the link is weak)."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import cv2

from ..ingest.sources import open_capture
from .templates import mask

TARGET_FPS = 5.0  # the edge processes 5 frames/s per camera on a laptop


@dataclass
class StreamReport:
    url: str
    opened: bool
    width: int | None = None
    height: int | None = None
    fps_reported: float | None = None
    fps_measured: float | None = None
    bitrate_kbps: float | None = None
    frames: int = 0
    read_failures: int = 0
    seconds: float = 0.0
    advice: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.opened and self.frames > 0

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


def advise(r: StreamReport, live: bool = True) -> list[str]:
    tips = []
    if not r.opened:
        return ["stream did not open: check IP, port 554, user/password and channel; try the other template"]
    if r.frames == 0:
        return ["opened but no frames: wrong channel, or the recorder allows fewer RTSP sessions"]
    if (r.width or 0) * (r.height or 0) > 1280 * 720:
        tips.append("heavier than 720p: use the sub-stream (decode time is wasted on the main stream)")
    loss = r.read_failures / (r.frames + r.read_failures)
    if loss > 0.02:
        tips.append(f"{loss:.0%} of reads failed: check the cable / Wi-Fi, or use the sub-stream")
    if live and r.fps_measured is not None and r.fps_measured < TARGET_FPS:
        tips.append(f"only {r.fps_measured:.1f} frames/s arrive: raise the sub-stream fps on the recorder to 5-10")
    return tips or ["ok: ready for site.yaml"]


def probe(url: str, seconds: float = 8.0, max_frames: int = 400, live: bool = True) -> StreamReport:
    cap = open_capture(url)
    report = StreamReport(url=mask(url), opened=bool(cap.isOpened()))
    if report.opened:
        t0 = time.monotonic()
        while time.monotonic() - t0 < seconds and report.frames < max_frames and report.read_failures <= 20:
            ok, frame = cap.read()
            if not ok:
                if not live:
                    break  # end of a file
                report.read_failures += 1
                continue
            report.frames += 1
            report.height, report.width = int(frame.shape[0]), int(frame.shape[1])
        report.seconds = round(time.monotonic() - t0, 2)
        report.fps_reported = round(float(cap.get(cv2.CAP_PROP_FPS)), 2) or None
        report.bitrate_kbps = round(float(cap.get(cv2.CAP_PROP_BITRATE)), 1) or None
        if report.seconds > 0:
            report.fps_measured = round(report.frames / report.seconds, 2)
    cap.release()
    report.advice = advise(report, live)
    return report
