"""Pipeline throughput and memory on this machine (feeds the table in plan Section 7.8).

Measures frames/s of the full edge step (render + perception enrichment + plugins + routing) for
the simulator, and peak RSS. With real models, run the same harness with ``--source rtsp``.
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import resource
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--report", default="eval/reports/bench.json")
    args = ap.parse_args()
    logging.disable(logging.WARNING)
    from jikimi_edge.runner import build_pipeline
    from jikimi_edge.settings import load_settings
    from jikimi_edge.sim.source import SimSource

    s = load_settings(ROOT / "edge/config/site.demo.yaml", repo_root=ROOT)
    pipeline, _, _ = build_pipeline(s, with_outbox=False, record_clips=False)
    sources = {
        cam.id: SimSource(
            cam.id,
            (cam.source or "sim:normal_traffic")[4:],
            fps=s.process_fps,
            realtime=False,
            start_ts=1_793_000_000.0,
        )
        for cam in s.cameras
    }
    frames = 0
    render_s = 0.0
    t_end = time.perf_counter() + args.seconds
    t0 = time.perf_counter()
    while time.perf_counter() < t_end:
        for cid, src in sources.items():
            r0 = time.perf_counter()
            frame = src.read()
            render_s += time.perf_counter() - r0
            if frame is None:
                continue
            pipeline.process(cid, frame)
            frames += 1
    wall = time.perf_counter() - t0
    report = {
        "machine": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "frames": frames,
        "fps_total": round(frames / wall, 1),
        "fps_pipeline_only": round(frames / max(wall - render_s, 1e-6), 1),
        "cameras_at_5fps_supported": round(frames / wall / 5, 1),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
