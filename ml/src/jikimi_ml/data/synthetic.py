"""PakSnatch-sim: licence-free synthetic pose windows for ST-GCN *pre-training*.

The plan pre-trains on NTU RGB+D interaction classes, which are research-only. The edge
simulator already produces consistent 2-person poses, so we randomise encounters (snatch with
random direction/speed/lane/reach timing; hard negatives: delivery hand-over, asking directions,
close passes) and cut the exact tensors the edge feeds the model. Fine-tuning on real, consented
PakSnatch clips remains mandatory: synthetic data teaches the *shape* of the motion only.

    uv run python -m jikimi_ml.data.synthetic --out data/ml/paksnatch_sim.npz --episodes 400
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class Episode:
    windows: list[np.ndarray] = field(default_factory=list)
    labels: list[int] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    meta: list[tuple[float, int, int]] = field(default_factory=list)
    """Per window: (time of its last sample, bike track id, pedestrian track id) - to render it."""
    world: Any = None


def _episode(kind: str, seed: int, fps: float = 5.0) -> tuple[list[np.ndarray], list[int], list[str]]:
    e = episode(kind, seed, fps)
    return e.windows, e.labels, e.groups


def episode(kind: str, seed: int, fps: float = 5.0) -> Episode:
    from jikimi_edge.analytics.base import CameraConfig, FrameContext
    from jikimi_edge.analytics.snatch.pair_builder import build_samples
    from jikimi_edge.analytics.snatch.stgcn_infer import CONTACT_SPAN, build_input
    from jikimi_edge.sim.scenarios import _Ids, add_asking_directions, add_delivery, add_snatch, background_traffic
    from jikimi_edge.sim.world import World
    from jikimi_edge.tracking.riders import associate_riders
    from jikimi_edge.tracking.track_store import TrackStore

    rng = random.Random(seed)
    ids = _Ids(seed * 1000)
    actors = background_traffic(40.0, rng, ids, density=0.35)
    positive_bike: int | None = None
    t0 = 20.0
    if kind == "snatch":
        info = add_snatch(
            actors,
            ids,
            rng,
            t0,
            {
                "direction": rng.choice((1, -1)),
                "speed": rng.uniform(0.18, 0.32),
                "depart_speed": rng.uniform(0.38, 0.65),
                "x_meet": rng.uniform(0.3, 0.7),
                "y": rng.uniform(0.52, 0.55),
                "reach_rider": rng.choice((1, 1, 1, 0)),
                "reach_lead": rng.uniform(0.1, 0.4),
                "reach_len": rng.uniform(0.6, 1.2),
                "jerk": (rng.uniform(-0.05, -0.015), rng.uniform(0.01, 0.045)),
                "victim_y": rng.uniform(0.465, 0.475),
                "phone": rng.random() < 0.8,
            },
        )
        positive_bike = info["bike_actor"]
    elif kind == "delivery":
        add_delivery(actors, ids, rng, t0)
    elif kind == "directions":
        add_asking_directions(actors, ids, rng, t0)
    world = World(actors, seed=seed)
    store = TrackStore(CameraConfig(id="sim"))
    out = Episode(world=world)
    samples: dict[tuple[int, int], list] = {}
    for i in range(int(40 * fps)):
        t = i / fps
        st = world.state(t, 1_700_000_000.0 + t)
        riders = associate_riders(st.tracks)
        rider_ids = frozenset(x for v in riders.values() for x in v)
        tracks, _, _ = store.update(st.tracks, t, None, riders)
        ctx = FrameContext(site_id="sim", camera_id="sim", ts=t, frame=None, tracks=tracks, poses=st.poses, riders_of=riders, rider_ids=rider_ids)
        for bike, ped, _, sample in build_samples(tracks, riders, ctx.pedestrians, st.poses, t):
            samples.setdefault((bike.track_id, ped.track_id), []).append(sample)
    track_actor = {tid: aid for (aid, sub), tid in world._id_of.items() if sub == 0}
    for (bike_id, ped_id), ss in samples.items():
        if len(ss) < 4:
            continue
        # slide windows ending at every sample with enough history: positives only around contact
        closest = min(range(len(ss)), key=lambda k: ss[k].hand_dist)
        for end in range(3, len(ss)):
            x = build_input(ss[: end + 1])
            if x is None:
                continue
            is_pos = track_actor.get(bike_id) == positive_bike and abs(end - closest) <= CONTACT_SPAN
            if not is_pos and end % 3:  # thin out negatives
                continue
            out.windows.append(x[0])
            out.labels.append(int(is_pos))
            out.groups.append(f"{kind}-{seed}")
            out.meta.append((ss[end].ts, bike_id, ped_id))
    return out


def generate(episodes: int, seed: int = 0) -> dict[str, np.ndarray]:
    rng = random.Random(seed)
    xs: list[np.ndarray] = []
    ys: list[int] = []
    gs: list[str] = []
    kinds = ["snatch"] * 4 + ["delivery"] * 2 + ["directions"] * 2 + ["normal"] * 2
    for e in range(episodes):
        w, y, g = _episode(rng.choice(kinds), seed * 100_000 + e)
        xs += w
        ys += y
        gs += g
    return {"x": np.stack(xs).astype(np.float32), "y": np.asarray(ys, np.int64), "group": np.asarray(gs)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/ml/paksnatch_sim.npz")
    ap.add_argument("--episodes", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    data = generate(args.episodes, args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, **data)
    print(f"wrote {args.out}: {len(data['y'])} windows, {int(data['y'].sum())} positive, groups={len(set(data['group']))}")


if __name__ == "__main__":
    main()
