"""Snatching on foot (F3 extension): someone walks up to a person, a hand reaches them, then they
run off. Phones are the usual target, and people talking on one the usual victims.

A pair of pedestrians is watched from the moment they touch (feet within half a body size, or a
wrist on the other's hand or hip when poses exist). The pattern is the bike snatch's shape on
foot: the two came from apart (they were not walking together), touched, and within three seconds
one of them broke into a run from walking pace, away from the other, while the other jerked or
stayed. Hard negatives: greetings and hand-overs (nobody runs), a jogger brushing past (already
running), children playing tag (running before and after), friends jogging off together.

Every touching pair is a calibration unit (``snatch_on_foot``). The score is a hand-set logistic
over these features, like the bike snatch's B1 baseline, until on-foot footage can train a model.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from jikimi_contracts import KP, AlertCandidate, AlertType, ObjectSummary, Pose

from ..base import CameraConfig, FrameContext
from ..people import RUN, People, Person, distance, is_night, same_depth, size_of

WRISTS = (KP["left_wrist"], KP["right_wrist"])
TARGETS = (KP["left_wrist"], KP["right_wrist"], KP["left_hip"], KP["right_hip"])


@dataclass
class _Pair:
    a: int
    b: int
    first_ts: float
    last_ts: float
    min_d: float = 9.0
    min_hand: float = 9.0
    apart_before: float = 1.0
    """1 = both seen 3 s before and well apart, 0.5 = one of them just appeared, 0 = close."""
    together_s: float = 0.0
    pre_speed: dict[int, float] = field(default_factory=dict)
    phone: dict[int, bool] = field(default_factory=dict)
    best: float = 0.0
    emitted: bool = False


def on_phone(pose: Pose | None, size: float) -> bool:
    """A wrist up at the head, above the shoulder: talking on a phone."""
    if pose is None:
        return False
    k = np.asarray(pose.keypoints, dtype=np.float32)
    nose = k[KP["nose"]]
    if nose[2] < 0.3:
        return False
    for w, sh in ((KP["left_wrist"], KP["left_shoulder"]), (KP["right_wrist"], KP["right_shoulder"])):
        up = k[w, 2] >= 0.3 and k[sh, 2] >= 0.3 and k[w, 1] < k[sh, 1]
        if up and math.hypot(k[w, 0] - nose[0], k[w, 1] - nose[1]) < 0.3 * size:
            return True
    return False


def hand_gap(pa: Pose | None, pb: Pose | None, size: float) -> float:
    """Closest wrist of one to a hand or hip of the other, in body sizes (9 without poses)."""
    if pa is None or pb is None:
        return 9.0
    ka, kb = np.asarray(pa.keypoints, dtype=np.float32), np.asarray(pb.keypoints, dtype=np.float32)
    best = math.inf
    for k1, k2 in ((ka, kb), (kb, ka)):
        for w in WRISTS:
            if k1[w, 2] < 0.3:
                continue
            for j in TARGETS:
                if k2[j, 2] >= 0.3:
                    best = min(best, math.hypot(k1[w, 0] - k2[j, 0], k1[w, 1] - k2[j, 1]))
    return best / size if math.isfinite(best) else 9.0


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score(f: dict[str, Any]) -> float:
    z = (
        -5.2
        + 1.6 * f["contact"]
        + 1.0 * f["approach"]
        + 3.4 * f["run"]
        + 1.5 * f["fled"]
        + 1.2 * f["sudden"]
        + 1.0 * f["jerk"]
        + 0.8 * f["phone"]
        - 2.0 * f["together"]
        - 2.5 * f["both_ran"]
        - 1.5 * f["victim_moving"]
        - 2.0 * f["long_contact"]
    )
    return 1.0 / (1.0 + math.exp(-z))


class FootSnatchPlugin:
    name = "foot_snatch"
    version = "foot-heuristic-v1"
    needs = frozenset({"tracks", "person_poses"})

    def __init__(self) -> None:
        self.min_score = 0.3
        self.contact_d = 0.55
        """Feet within about half a body size: the two bodies touch."""
        self.window_s = 3.0
        """The run has to start within this long after the last touch."""
        self.people = People()
        self._pairs: dict[tuple[int, int], _Pair] = {}
        self._near_since: dict[tuple[int, int], float] = {}
        self.score_logs: dict[str, dict[str, float]] | None = None

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        cfg = (site_cfg.get("plugins") or {}).get(self.name, {}) or {}
        self.min_score = float(cfg.get("min_score", self.min_score))
        self.contact_d = float(cfg.get("contact_d", self.contact_d))

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        ts = ctx.ts
        people = self.people.update(ctx.pedestrians, ctx.tracks, ts)
        for i, a in enumerate(people):
            for b in people[i + 1 :]:
                key = (min(a.track_id, b.track_id), max(a.track_id, b.track_id))
                d = distance(a, b) if same_depth(a, b) else None
                if d is None or d > 1.5:
                    self._near_since.pop(key, None)
                    continue
                if d < 1.0:
                    self._near_since.setdefault(key, ts)
                else:
                    self._near_since.pop(key, None)
                hand = hand_gap(ctx.poses.get(a.track_id), ctx.poses.get(b.track_id), size_of(a, b))
                if d > self.contact_d and hand > 0.3:
                    continue
                pair = self._pairs.get(key)
                if pair is None:
                    pair = self._open(key, a, b, ts, ctx)
                pair.last_ts = ts
                pair.min_d, pair.min_hand = min(pair.min_d, d), min(pair.min_hand, hand)
        out: list[AlertCandidate] = []
        for key, pair in list(self._pairs.items()):
            f = self._features(pair, ts)
            s = score(f)
            if f["runner"] is not None and self._crowd_running(f["runner"], pair):
                f["runner"] = None  # many people running at once: a crowd scattering, not a grab
            if f["runner"] is not None:  # only a pair where someone ran can alert: calibrate on those
                pair.best = max(pair.best, s)
            finished = ts - pair.last_ts > self.window_s + 1.5
            if not pair.emitted and f["runner"] is not None and (f["separated"] or finished):
                pair.emitted = True
                if s >= self.min_score:
                    out.append(self._alert(ctx, pair, f, s))
            if finished:
                if self.score_logs is not None:
                    log = self.score_logs.setdefault("snatch_on_foot", {})
                    log[f"{key[0]}-{key[1]}-{pair.first_ts:.1f}"] = pair.best
                del self._pairs[key]
        return out

    def _crowd_running(self, runner: int, pair: _Pair) -> bool:
        """Two more people broke into a run around the same time (runners leave the view fast, so
        everyone seen recently counts, not only who is still there)."""
        t0, t1 = pair.first_ts - 1.0, pair.last_ts + self.window_s
        others = [p for p in self.people.by_id.values() if p.track_id != runner and p.max_speed(t0, t1) >= RUN]
        return len(others) >= 2

    def _open(self, key: tuple[int, int], a: Person, b: Person, ts: float, ctx: FrameContext) -> _Pair:
        pair = _Pair(key[0], key[1], ts, ts)
        before = distance(a, b, ts - 3.0)
        pair.apart_before = 0.5 if before is None else float(before >= 1.5)
        since = self._near_since.get(key)
        pair.together_s = ts - since if since is not None else 0.0
        for p in (a, b):
            base = p.baseline_speed(ts, skip_s=0.0, span_s=3.0)
            if base is None and ts - p.first_ts >= 1.0:
                base = statistics.median(s for t, s in p.speeds if ts - t <= 3.0)
            # a body that just walked (or ran) into view has no "before": not evidence of a sudden start
            pair.pre_speed[p.track_id] = base if base is not None else RUN
            pair.phone[p.track_id] = on_phone(ctx.poses.get(p.track_id), p.size)
        self._pairs[key] = pair
        return pair

    def _features(self, pair: _Pair, ts: float) -> dict[str, Any]:
        a, b = self.people.by_id.get(pair.a), self.people.by_id.get(pair.b)
        f: dict[str, Any] = {"runner": None, "victim": None, "separated": False, "run": 0.0, "both_ran": 0.0}
        f["fled"] = 0.0
        f["victim_moving"] = 0.0
        f["long_contact"] = _clip((pair.last_ts - pair.first_ts - 1.5) / 3.0)  # a grab is quick
        contact = max(_clip(1.0 - pair.min_d / self.contact_d), _clip(1.0 - pair.min_hand / 0.3))
        f.update(contact=contact, approach=pair.apart_before)
        f["together"] = _clip((pair.together_s - 2.0) / 5.0)
        f.update(sudden=0.0, jerk=0.0, phone=0.0, runner_speed=0.0)
        if a is None or b is None:
            return f
        t1 = min(ts, pair.last_ts + self.window_s)
        best: tuple[float, Person, Person] | None = None
        for p, q in ((a, b), (b, a)):
            top = p.max_speed(pair.first_ts, t1)
            pre = pair.pre_speed.get(p.track_id, 0.0)
            if top >= RUN and top >= 2.2 * pre + 0.3 and (best is None or top > best[0]):
                best = (top, p, q)
        if best is None:
            return f
        top, runner, victim = best
        d_now = distance(runner, victim)
        gone = ts - runner.last_ts > 0.5
        f["separated"] = gone or (d_now is not None and d_now >= 3.0)
        # ran out of sight or well away *still running* (children at play run about and come back)
        f["fled"] = 1.0 if f["separated"] and runner.speed >= 0.8 * RUN else 0.0
        pre_run = pair.pre_speed.get(runner.track_id, 0.0)
        pre_vic = pair.pre_speed.get(victim.track_id, 0.0)
        f.update(runner=runner.track_id, victim=victim.track_id, runner_speed=round(top, 2))
        f["run"] = _clip((top - RUN) / RUN)
        f["sudden"] = _clip(1.0 - pre_run / RUN)
        f["jerk"] = _clip((victim.max_speed(pair.first_ts - 0.5, pair.last_ts + 1.0) - pre_vic) / 1.5)
        f["phone"] = 1.0 if pair.phone.get(victim.track_id) else 0.0
        f["victim_moving"] = _clip(pre_vic / RUN)  # victims stand or stroll; children at play run
        vic_top = victim.max_speed(pair.first_ts, t1)
        if vic_top >= RUN and d_now is not None and d_now < 1.2 and not f["separated"]:
            f["both_ran"] = 1.0  # ran off together and stayed together: friends; a victim chasing falls behind
        return f

    def _alert(self, ctx: FrameContext, pair: _Pair, f: dict[str, Any], s: float) -> AlertCandidate:
        victim = self.people.by_id.get(f["victim"])
        alone = victim is not None and not any(
            p.track_id not in (pair.a, pair.b) and (distance(victim, p) or 99) <= 8.0 for p in self.people.current
        )
        features = {
            "on_foot": True,
            "vehicle": None,
            "item": "phone" if f["phone"] else None,
            **{k: round(float(v), 3) for k, v in f.items() if k not in ("runner", "victim", "separated")},
            "night": is_night(ctx.ts, ctx.tz_offset_s),
            "alone": alone,
            "calibration_key": "snatch_on_foot",
            "dedupe_key": f"foot-{pair.a}-{pair.b}",
        }
        return ctx.make_alert(
            AlertType.SNATCH,
            s,
            pair.first_ts,
            track_ids=[f["runner"], f["victim"]],
            features=features,
            objects=[ObjectSummary(type="person", count=2)],
            model_versions={"snatch": self.version},
        )

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None
