"""Baseline B1 snatch scorer: interpretable features + logistic combination.

Snatching has a characteristic shape (plan Section 8.2): the bike slows near a pedestrian, a
rider's hand reaches the pedestrian's hand/bag, the pedestrian jerks, and the bike speeds away
within ~3 s. Hard negatives (asking directions, handing over a delivery) have contact but no
fast departure, or a long stay. The ST-GCN (``stgcn_infer.py``) replaces this score once
trained on PakSnatch; these features stay for the Urdu explanation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from .pair_builder import PairSample


@dataclass(frozen=True)
class SnatchFeatures:
    min_hand_dist: float
    contact: float
    slow_approach: float
    depart_accel: float
    ped_jerk: float
    close_duration_s: float

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in self.__dict__.items()}


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def extract(samples: Sequence[PairSample], bike_median_speed: float, reach: float = 0.35) -> SnatchFeatures:
    if not samples:
        return SnatchFeatures(9.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    i_min = min(range(len(samples)), key=lambda i: samples[i].hand_dist)
    closest = samples[i_min]
    ref_speed = max(bike_median_speed, 0.1)  # cruising speed before the encounter
    contact = _clip(1.0 - closest.hand_dist / reach)
    slow = _clip(1.0 - closest.bike_speed / ref_speed)
    after = samples[i_min:]
    max_after = max((s.bike_speed for s in after), default=closest.bike_speed)
    depart = _clip((max_after - closest.bike_speed) / ref_speed, 0.0, 1.5) / 1.5
    jerk = 0.0
    for a, b in pairwise(samples):
        dt = b.ts - a.ts
        if dt <= 1e-6 or abs(b.ts - closest.ts) > 1.5:
            continue
        v = math.hypot(b.ped_center[0] - a.ped_center[0], b.ped_center[1] - a.ped_center[1]) / dt
        jerk = max(jerk, v / max(b.ped_height, 0.03))
    close = [s for s in samples if s.hand_dist < 2 * reach]
    duration = (close[-1].ts - close[0].ts) if len(close) >= 2 else 0.0
    return SnatchFeatures(
        min_hand_dist=closest.hand_dist,
        contact=contact,
        slow_approach=slow,
        depart_accel=depart,
        ped_jerk=_clip(jerk / 2.5),
        close_duration_s=duration,
    )


def score(f: SnatchFeatures) -> float:
    long_stay = _clip((f.close_duration_s - 5.0) / 5.0)
    z = -5.0 + 3.2 * f.contact + 1.0 * f.slow_approach + 3.0 * f.depart_accel + 2.0 * f.ped_jerk - 2.5 * long_stay
    return 1.0 / (1.0 + math.exp(-z))
