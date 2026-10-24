"""Real footage through the real edge, before any pilot (plan Section 15: test on real video).

    uv run python -m eval.footage_check data/footage/clip.mp4 [--profile onnx-cpu] [--zone 0,0.25,1,0.25,1,1,0,1]

YOLO detection + ByteTrack + rider association + re-ID + every plugin run on a video file. The
report answers what a site owner asks first: what was detected and tracked, the colours and riders
of the bikes, any alerts with their Roman Urdu reason, the camera-health checks, and the speed on
this machine. A few frames are written to ``data/footage/out/`` with every head blurred (never into
the repository). Footage without incidents doubles as a false-alarm check: any snatch or loitering
alert on it is a false alarm.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
CAMERA = "cam-footage-01"


class _Timed:
    """Wraps the detector / pose model: latency per call and what it returned."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.ms: list[float] = []
        self.counts: Counter[str] = Counter()
        self.last: list[Any] = []

    def __call__(self, *args: Any) -> Any:
        t0 = time.perf_counter()
        out = self.inner(*args)
        self.ms.append((time.perf_counter() - t0) * 1000)
        if isinstance(out, list):
            self.counts.update(d.cls for d in out)
            self.last = out
        return out


def _ms(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    s = sorted(values)
    return {"mean": round(statistics.fmean(s), 1), "p95": round(s[int(0.95 * (len(s) - 1))], 1), "n": len(s)}


def _snapshot(image: Any, dets: list[Any], blur: Any, path: Path) -> None:
    h, w = image.shape[:2]
    from jikimi_edge.privacy.face_blur import rider_head_proxy

    persons = [d.bbox for d in dets if d.cls == "person"]
    persons += [rider_head_proxy(d.bbox) for d in dets if d.cls in ("motorcycle", "bicycle")]
    out, _ = blur.apply(image, persons)  # heads (and riders above bikes) blurred before writing
    for d in dets:
        x1, y1, x2, y2 = (int(d.bbox[0] * w), int(d.bbox[1] * h), int(d.bbox[2] * w), int(d.bbox[3] * h))
        color = (0, 200, 255) if d.cls == "motorcycle" else (80, 220, 80) if d.cls == "person" else (255, 160, 0)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        cv2.putText(out, f"{d.cls} {d.conf:.2f}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), out, [cv2.IMWRITE_JPEG_QUALITY, 85])


def main() -> None:
    from jikimi_edge.analytics.base import CameraConfig, ZoneConfig
    from jikimi_edge.ingest.sources import VideoFileSource
    from jikimi_edge.privacy.face_blur import PrivacyBlur
    from jikimi_edge.runner import build_pipeline
    from jikimi_edge.settings import load_settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video")
    ap.add_argument("--profile", default="onnx-cpu", help="models.yaml profile")
    ap.add_argument("--zone", default="0,0.25,1,0.25,1,1,0,1", help="x,y pairs of the watched area (normalised)")
    ap.add_argument("--snapshots", type=int, default=3)
    ap.add_argument("--out", default="data/footage/out")
    ap.add_argument("--report", default="eval/reports/footage_check.json")
    args = ap.parse_args()

    xy = [float(v) for v in args.zone.split(",")]
    zone = ZoneConfig(id="road", name="Road", name_ur="سڑک", polygon=[[xy[i], xy[i + 1]] for i in range(0, len(xy), 2)])
    camera = CameraConfig(
        id=CAMERA, name="Footage", name_ur="ویڈیو", name_roman="Video", source=f"file:{args.video}", zones=[zone]
    )
    with tempfile.TemporaryDirectory() as tmp:
        base = load_settings(ROOT / "edge/config/site.demo.yaml", repo_root=ROOT)
        settings = dataclasses.replace(base, cameras=[camera], model_profile=args.profile, data_dir=Path(tmp))
        pipeline, outbox, _ = build_pipeline(settings, with_outbox=True, record_clips=False, real_perception=True)
        if pipeline.detector is None:
            raise SystemExit(f"no detector for profile '{args.profile}': export the models first (models/README.md)")
        det, pose = _Timed(pipeline.detector), _Timed(pipeline.pose) if pipeline.pose is not None else None
        pipeline.detector = det
        if pose is not None:
            pipeline.pose = pose
        src = VideoFileSource(CAMERA, args.video, fps=settings.process_fps, start_ts=time.time(), realtime=False)
        cap = cv2.VideoCapture(args.video)
        meta = {
            "file": Path(args.video).name,
            "size": f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}",
            "source_fps": round(cap.get(cv2.CAP_PROP_FPS), 2),
            "seconds": round(cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1), 1),
        }
        cap.release()
        blur = PrivacyBlur(settings.face_detector)
        total = int(meta["seconds"] * settings.process_fps)
        marks = {round(total * (k + 1) / (args.snapshots + 1)) for k in range(args.snapshots)}
        step_ms: list[float] = []
        frames = 0
        last_ts = 0.0
        while (frame := src.read()) is not None:
            t0 = time.perf_counter()
            pipeline.process(CAMERA, frame)
            step_ms.append((time.perf_counter() - t0) * 1000)
            frames += 1
            last_ts = frame.ts
            if frames in marks and frame.image is not None:
                _snapshot(frame.image, det.last, blur, Path(args.out) / f"{Path(args.video).stem}_{frames:04d}.jpg")
        health = {h.camera_id: h.checks for h in pipeline.camera_health(last_ts)}
        pipeline.flush()
        tracks = [i.payload for i in outbox.due(now=1e12, limit=1_000_000) if i.kind == "track"]
        outbox.close()

    by_type = Counter(t["object"]["type"] for t in tracks)
    bikes = [t["object"] for t in tracks if t["object"]["type"] == "motorcycle"]
    report: dict[str, Any] = {
        "video": meta,
        "processed_frames": frames,
        "process_fps": settings.process_fps,
        "detections_per_class": dict(det.counts.most_common()),
        "finished_tracks": dict(by_type.most_common()),
        "bike_colours": dict(Counter(b.get("color") or "unknown" for b in bikes).most_common()),
        "bike_riders": dict(Counter(str(b.get("riders")) for b in bikes).most_common()),
        "alerts": [
            {
                "type": a.type.value,
                "route": a.route.value,
                "severity": a.severity.value,
                "p": a.p_value,
                "why": a.explanation_roman,
            }
            for a in pipeline.alerts
        ],
        "camera_health": health,
        "ms_per_frame": {"pipeline": _ms(step_ms), "detector": _ms(det.ms), "pose": _ms(pose.ms) if pose else None},
    }
    mean = report["ms_per_frame"]["pipeline"]["mean"] if step_ms else None
    report["cameras_at_5fps_on_this_machine"] = round(1000 / mean / 5, 1) if mean else None
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
