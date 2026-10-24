"""RUVR-sim: Roman Urdu video retrieval on simulated scenes with exact ground truth (F1, F9).

Corpus: every finished track of ``normal_traffic`` scenes, run through the real edge pipeline
(colour named from pixels, riders associated from boxes) and indexed by the real server.
Queries: Roman Urdu (several spellings) and Urdu-script templates over the scripted bike colour
and number of riders. Relevant = every bike whose *scripted* colour (and riders) match; tracks
without ground truth count as wrong answers. Recall@10 and MRR with 95 % bootstrap CIs.

    uv run python -m eval.ruvr_sim --scenes 4

Simulated pixels are cleaner than night-time CCTV: this measures the pipeline and the parser
end to end, not real-world accuracy (that needs the RUVR annotations of real footage).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import secrets
import tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCENE_S = 600.0
CAMERAS = ("cam-gate-01", "cam-street-02")
COLOR_WORDS = {
    "black": ["kaali", "kali", "kala"],
    "red": ["laal", "lal", "surkh"],
    "white": ["safaid", "sufaid", "safed"],
    "blue": ["neeli", "nili", "neela"],
    "green": ["hari", "sabz", "hara"],
    "yellow": ["peeli", "pili", "zard"],
    "silver": ["silver", "chandi"],
}
URDU_COLOR = {"black": "کالی", "red": "لال", "white": "سفید", "blue": "نیلی", "green": "ہری", "yellow": "پیلی"}
BIKE_WORDS = ["bike", "motorsaikal", "honda"]
RIDER_WORDS = {1: ["akela", "ek sawar"], 2: ["2 sawar", "do sawar", "double sawari"]}


def _scene(job: tuple[str, int, float]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Run one scene through the edge; return its track summaries and per-track ground truth."""
    from jikimi_edge.runner import build_pipeline
    from jikimi_edge.settings import load_settings
    from jikimi_edge.sim.source import SimSource

    camera, seed, start = job
    with tempfile.TemporaryDirectory() as tmp:
        settings = dataclasses.replace(
            load_settings(ROOT / "edge/config/site.demo.yaml", repo_root=ROOT), data_dir=Path(tmp)
        )
        pipeline, outbox, _ = build_pipeline(settings, with_outbox=True, record_clips=False)
        assert outbox is not None
        src = SimSource(
            camera,
            "normal_traffic",
            fps=settings.process_fps,
            realtime=False,
            loop=False,
            start_ts=start,
            seed=seed,
            tz=settings.tz,
        )
        while (frame := src.read()) is not None:
            pipeline.process(camera, frame)
        pipeline.flush()
        tracks = [i.payload for i in outbox.due(now=1e12, limit=1_000_000) if i.kind == "track"]
        actors = {a.actor_id: a for a in src.scenario.actors}
        truth: dict[str, dict[str, Any]] = {}
        for (actor_id, sub), track_id in src._world._id_of.items():  # simulator ground truth
            a = actors.get(actor_id)
            if sub == 0 and a is not None and a.kind == "motorcycle" and a.vehicle is not None and a.vehicle.color:
                truth[f"{camera}:{int(start)}:{track_id}"] = {"color": a.vehicle.color, "riders": len(a.vehicle.riders)}
        outbox.close()
    return tracks, truth


def _queries(truth: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    present: dict[tuple[str, int], int] = defaultdict(int)
    for t in truth.values():
        present[(t["color"], t["riders"])] += 1
    colors = sorted({c for c, _ in present})
    out: list[dict[str, Any]] = []
    for i, color in enumerate(colors):
        words = COLOR_WORDS[color]
        for j, word in enumerate(words):
            out.append({"kind": "colour", "text": f"{word} {BIKE_WORDS[(i + j) % len(BIKE_WORDS)]}", "color": color})
        if color in URDU_COLOR:
            out.append({"kind": "urdu", "text": f"{URDU_COLOR[color]} موٹر سائیکل", "color": color})
        for riders, phrases in RIDER_WORDS.items():
            if present.get((color, riders)):
                for k, phrase in enumerate(phrases):
                    text = f"{words[k % len(words)]} bike {phrase}"
                    out.append({"kind": "colour+riders", "text": text, "color": color, "riders": riders})
    return out


def _relevant(q: dict[str, Any], truth: dict[str, dict[str, Any]]) -> set[str]:
    return {
        key
        for key, t in truth.items()
        if t["color"] == q["color"] and ("riders" not in q or t["riders"] == q["riders"])
    }


def main() -> None:
    import numpy as np
    from fastapi.testclient import TestClient
    from jikimi_crypto import Signer, generate_private_key
    from jikimi_ml.eval.stats import bootstrap_ci
    from jikimi_server.db.session import Database
    from jikimi_server.main import create_app
    from jikimi_server.seed import seed_site
    from jikimi_server.settings import ServerSettings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenes", type=int, default=4, help="scenes per camera (10 min each)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--report", default="eval/reports/ruvr_sim.json")
    args = ap.parse_args()

    from datetime import UTC, datetime

    base = datetime.now(UTC).timestamp() - 2 * 86400  # inside the default "last 7 days" search window
    jobs = [
        (cam, 70_000 + 10 * k + c, base + k * (SCENE_S + 100))
        for k in range(args.scenes)
        for c, cam in enumerate(CAMERAS)
    ]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        scenes = list(pool.map(_scene, jobs))
    truth: dict[str, dict[str, Any]] = {}
    for _, t in scenes:
        truth.update(t)
    starts = sorted({int(j[2]) for j in jobs})

    def key_of(ref: str) -> str:
        _, cam, track_id, ts = ref.split(":")
        start = max(s for s in starts if s <= int(ts) + 1)
        return f"{cam}:{start}:{track_id}"

    password = "ruvr-" + secrets.token_urlsafe(12)  # throwaway login for this in-process server
    with tempfile.TemporaryDirectory() as tmp:
        settings = ServerSettings(
            database_url=f"sqlite:///{tmp}/db.sqlite",
            data_dir=Path(tmp) / "server",
            jwt_secret=secrets.token_urlsafe(40),
            public_base_url="http://testserver",
            dashboard_dir=Path(tmp) / "none",
            workers_inprocess=False,
        )
        db = Database(settings.database_url)
        db.create_all()
        device = Signer.from_key(generate_private_key(), prefix="edge")
        token_file = Path(tmp) / "device.token"
        site = seed_site(
            db, ROOT / "edge/config/site.demo.yaml", password, device.public_key, device.key_id, token_file
        )
        with TestClient(create_app(settings)) as client:
            edge = {"Authorization": f"Bearer {token_file.read_text()}"}
            indexed = sum(
                client.post("/v1/edge/tracks", json=t, headers=edge).json()["indexed"] for s, _ in scenes for t in s
            )
            tok = client.post("/v1/auth/login", json={"username": "sana", "password": password}).json()["token"]
            auth = {"Authorization": f"Bearer {tok}"}
            rows = []
            for q in _queries(truth):
                rel = _relevant(q, truth)
                res = client.post(
                    "/v1/search", json={"site_id": site.site_id, "query": q["text"], "limit": 10}, headers=auth
                ).json()
                ranked = [key_of(r["clip_id"]) for r in res["results"] if r["kind"] == "track"]
                hits = [i for i, k in enumerate(ranked) if k in rel]
                rows.append(
                    {
                        **q,
                        "relevant": len(rel),
                        "recall_at_10": len(set(ranked) & rel) / min(len(rel), 10),
                        "mrr": 1.0 / (hits[0] + 1) if hits else 0.0,
                        "took_ms": res.get("took_ms"),
                    }
                )
    out: dict[str, Any] = {
        "scenes": len(jobs),
        "tracks_indexed": indexed,
        "bikes_with_truth": len(truth),
        "queries": len(rows),
    }
    for name, subset in [
        ("all", rows),
        *((k, [r for r in rows if r["kind"] == k]) for k in ("colour", "colour+riders", "urdu")),
    ]:
        if not subset:
            continue
        rec = bootstrap_ci(np.array([r["recall_at_10"] for r in subset]))
        mrr = bootstrap_ci(np.array([r["mrr"] for r in subset]))
        out[name] = {
            "n": len(subset),
            "recall_at_10": [round(rec.estimate, 3), round(rec.low, 3), round(rec.high, 3)],
            "mrr": [round(mrr.estimate, 3), round(mrr.low, 3), round(mrr.high, 3)],
        }
    out["worst"] = sorted(rows, key=lambda r: (r["recall_at_10"], r["mrr"]))[:5]
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "worst"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
