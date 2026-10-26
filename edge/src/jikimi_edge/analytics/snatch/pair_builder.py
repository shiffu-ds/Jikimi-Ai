"""Candidate (rider, pedestrian) pairs and their per-frame features (F3, plan Section 8.2).

A pair is active while a pedestrian is within reach of a rider on a two-wheeler. For every
frame we record the hand distance (wrist keypoints when poses exist, box gap otherwise) and the
speeds that make up a snatch: slow approach -> contact -> pedestrian jerk -> fast departure.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from jikimi_contracts import KP, Pose, Track

from ..geometry import box_gap, dist

WRISTS = (KP["left_wrist"], KP["right_wrist"])
REACH_POINTS = (KP["left_wrist"], KP["right_wrist"], KP["left_hip"], KP["right_hip"])


@dataclass
class PairSample:
    ts: float
    hand_dist: float
    """Normalized by pedestrian height."""
    gap: float
    bike_speed: float
    ped_center: tuple[float, float]
    ped_height: float
    rider_kpts: np.ndarray | None
    ped_kpts: np.ndarray | None


@dataclass
class Pair:
    bike_id: int
    ped_id: int
    rider_id: int | None
    entity_id: str | None
    first_ts: float
    last_ts: float
    bike_median_speed: float = 0.0
    samples: deque[PairSample] = field(default_factory=lambda: deque(maxlen=120))
    close_since: float | None = None
    emitted: bool = False

    @property
    def key(self) -> tuple[int, int]:
        return (self.bike_id, self.ped_id)


def _kpts(pose: Pose | None) -> np.ndarray | None:
    return None if pose is None else np.asarray(pose.keypoints, dtype=np.float32)


def hand_distance(rider: Track | None, ped: Track, rider_pose: Pose | None, ped_pose: Pose | None) -> float:
    """Closest rider-wrist to pedestrian hand/hip distance, in pedestrian heights."""
    h = max(ped.height, 0.03)
    rk, pk = _kpts(rider_pose), _kpts(ped_pose)
    if rk is not None and pk is not None:
        best = np.inf
        for i in WRISTS:
            if rk[i, 2] < 0.2:
                continue
            for j in REACH_POINTS:
                if pk[j, 2] < 0.2:
                    continue
                best = min(best, float(np.hypot(rk[i, 0] - pk[j, 0], rk[i, 1] - pk[j, 1])))
        if np.isfinite(best):
            return best / h
    ref = rider.bbox if rider is not None else None
    if ref is None:
        return 9.0
    return box_gap(ref, ped.bbox) / h


def same_depth(bike: Track, ped: Track, low: float = 0.6, high: float = 4.0) -> bool:
    """A victim stands beside the bike, so both have the scale of the same distance: a standing
    person is about 1.3-2.5 bike-box heights tall there. People far behind the bike only *touch*
    it in the image (real footage of a crowded junction: a 0.08-high person "next to" a 0.25-high
    bike, ratio 0.32) and can never be robbed by it. Scale is the robust depth cue; the feet line
    is not (the simulator's victim stands ~1.2 bike heights above the wheels)."""
    return low <= ped.height / max(bike.height, 1e-3) <= high


def pairs_in_reach(
    tracks: list[Track], riders_of: dict[int, list[int]], rider_ids: frozenset[int], reach_heights: float = 1.2
) -> bool:
    """Cheap geometry check before running the pose model: is any pedestrian at the same depth
    within reach of a bike with riders? (Dense traffic without people beside the bikes skips the
    pose model, which costs more than the detector on a laptop CPU.)"""
    bikes = [t for t in tracks if riders_of.get(t.track_id)]
    peds = [t for t in tracks if t.cls == "person" and t.track_id not in rider_ids]
    return any(
        same_depth(b, p) and box_gap(b.bbox, p.bbox) < reach_heights * max(p.height, 0.03) * 2.0
        for b in bikes
        for p in peds
    )


def people_in_reach(tracks: list[Track], rider_ids: frozenset[int], reach_heights: float = 0.6) -> bool:
    """Two pedestrians of about the same size (same depth) within reach of each other: the pose
    model's gate for the on-foot snatch plugin."""
    peds = [t for t in tracks if t.cls == "person" and t.track_id not in rider_ids]
    for i, a in enumerate(peds):
        for b in peds[i + 1 :]:
            similar = 0.67 <= a.height / max(b.height, 1e-3) <= 1.5
            if similar and box_gap(a.bbox, b.bbox) < reach_heights * max((a.height + b.height) / 2, 0.03):
                return True
    return False


def build_samples(
    ctx_tracks: list[Track],
    riders_of: dict[int, list[int]],
    pedestrians: list[Track],
    poses: dict[int, Pose],
    ts: float,
    reach_heights: float = 1.2,
) -> list[tuple[Track, Track, Track | None, PairSample]]:
    """All (bike, pedestrian, closest rider, sample) tuples within reach on this frame."""
    by_id = {t.track_id: t for t in ctx_tracks}
    out: list[tuple[Track, Track, Track | None, PairSample]] = []
    for bike_id, rider_ids in riders_of.items():
        bike = by_id.get(bike_id)
        if bike is None or not rider_ids:
            continue
        riders = [by_id[r] for r in rider_ids if r in by_id]
        for ped in pedestrians:
            if not same_depth(bike, ped):
                continue
            h = max(ped.height, 0.03)
            near = [r for r in riders if box_gap(r.bbox, ped.bbox) < reach_heights * h]
            if not near and box_gap(bike.bbox, ped.bbox) >= reach_heights * h:
                continue
            rider = min(near or riders, key=lambda r: dist(r.center, ped.center)) if riders else None
            # any rider may reach (usually the pillion): take the closest hand of all riders
            hd = min(
                (hand_distance(r, ped, poses.get(r.track_id), poses.get(ped.track_id)) for r in riders),
                default=9.0,
            )
            sample = PairSample(
                ts=ts,
                hand_dist=hd,
                gap=box_gap(bike.bbox, ped.bbox) / h,
                bike_speed=bike.speed,
                ped_center=ped.center,
                ped_height=h,
                rider_kpts=_kpts(poses.get(rider.track_id)) if rider else None,
                ped_kpts=_kpts(poses.get(ped.track_id)),
            )
            out.append((bike, ped, rider, sample))
    return out
