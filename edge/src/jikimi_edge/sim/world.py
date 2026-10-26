"""Deterministic 2-D street world for development without cameras.

Actors move along keyframed paths in normalized image coordinates (the camera view). Every
appearance of an actor gets its own tracker ID, exactly like a real tracker; the *same* look on
a later appearance is how loitering bikes are recognised (by the edge's re-ID, not by us).
Poses are generated from the same skeleton that is drawn, so pose features are consistent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise

from jikimi_contracts import NUM_KEYPOINTS, Pose, Track

Color = tuple[int, int, int]

HORIZON_Y = 0.35


def scale_at(y: float) -> float:
    """Simple perspective: things further up the frame are smaller."""
    return 0.55 + 0.85 * max(0.0, (y - HORIZON_Y)) / (1.0 - HORIZON_Y)


@dataclass(frozen=True)
class PersonLook:
    shirt: Color
    pants: Color
    skin: Color = (120, 160, 205)
    hair: Color = (30, 30, 35)
    helmet: Color | None = None
    height: float = 0.15


@dataclass(frozen=True)
class VehicleLook:
    body: Color
    riders: tuple[PersonLook, ...] = ()
    delivery_box: Color | None = None
    color: str | None = None
    """Scripted colour name (ground truth for search evaluation; never shown to the pipeline)."""


@dataclass(frozen=True)
class Keyframe:
    t: float
    x: float
    y: float


@dataclass
class Actor:
    actor_id: int
    kind: str  # motorcycle | person | car | rickshaw
    path: list[Keyframe]
    person: PersonLook | None = None
    vehicle: VehicleLook | None = None
    postures: list[tuple[float, str]] = field(default_factory=list)
    """``(t, posture)`` from t on: stand | walk | phone | sit | crouch | lying (persons)."""
    reach: list[tuple[float, float, int, int]] = field(default_factory=list)
    """``(t0, t1, target_actor_id, rider_index)``: a rider's hand reaches the target's hand."""
    jerks: list[tuple[float, float, float, float]] = field(default_factory=list)
    """``(t0, t1, dx, dy)``: sudden displacement (a pedestrian being pulled)."""
    phone_until: float | None = None
    riders_from: float | None = None
    """Two-wheelers: riders sit on it only from this time (a parked bike until then)..."""
    riders_until: float | None = None
    """...and only until this time (the rider got off and parked it)."""
    label: str | None = None

    @property
    def t0(self) -> float:
        return self.path[0].t

    @property
    def t1(self) -> float:
        return self.path[-1].t

    def active(self, t: float) -> bool:
        return self.t0 <= t <= self.t1

    def pos(self, t: float) -> tuple[float, float]:
        pts = self.path
        if t <= pts[0].t:
            x, y = pts[0].x, pts[0].y
        elif t >= pts[-1].t:
            x, y = pts[-1].x, pts[-1].y
        else:
            x = y = 0.0
            for a, b in pairwise(pts):
                if a.t <= t <= b.t:
                    u = (t - a.t) / max(b.t - a.t, 1e-9)
                    x, y = a.x + (b.x - a.x) * u, a.y + (b.y - a.y) * u
                    break
        for j0, j1, dx, dy in self.jerks:
            if t >= j0:
                u = min(1.0, (t - j0) / max(j1 - j0, 1e-6))
                x, y = x + dx * u, y + dy * u
        return x, y

    def velocity(self, t: float, dt: float = 0.2) -> tuple[float, float]:
        (x0, y0), (x1, y1) = self.pos(t - dt), self.pos(t)
        return ((x1 - x0) / dt, (y1 - y0) / dt)

    def facing(self, t: float) -> int:
        vx, _ = self.velocity(t, 0.5)
        if abs(vx) < 1e-4:
            vx = self.path[-1].x - self.path[0].x
        return 1 if vx >= 0 else -1

    def posture(self, t: float) -> str:
        current = "walk" if self.kind == "person" else "sit"
        for ts, p in self.postures:
            if t >= ts:
                current = p
        if self.kind == "person" and current == "walk":
            speed = math.hypot(*self.velocity(t))
            if speed < 0.01:
                current = "stand"
            elif self.person is not None and speed > 0.9 * self.person.height * scale_at(self.pos(t)[1]):
                current = "run"  # more than ~0.9 body heights per second
        if self.phone_until is not None and t < self.phone_until and current in ("stand", "walk"):
            current = "phone"
        return current


# ---------------------------------------------------------------- geometry of drawn bodies
LOW_POSTURES = {"sit": (0.62, 0.5), "crouch": (0.62, 0.5), "lying": (0.26, 0.9)}
"""posture -> (box height, box width) as fractions of the standing height."""


def person_box(x: float, y: float, look: PersonLook, posture: str = "stand") -> tuple[float, float, float, float]:
    h = look.height * scale_at(y)
    fh, fw = LOW_POSTURES.get(posture, (1.0, 0.38))
    return (x - fw * h / 2, y - fh * h, x + fw * h / 2, y)


def bike_box(x: float, y: float) -> tuple[float, float, float, float]:
    s = scale_at(y)
    w, h = 0.095 * s, 0.07 * s
    return (x - w / 2, y - h, x + w / 2, y)


def car_box(x: float, y: float, kind: str) -> tuple[float, float, float, float]:
    s = scale_at(y)
    w, h = (0.2 * s, 0.11 * s) if kind == "car" else (0.13 * s, 0.12 * s)
    return (x - w / 2, y - h, x + w / 2, y)


def rider_box(x: float, y: float, facing: int, index: int) -> tuple[float, float, float, float]:
    s = scale_at(y)
    rx = x + facing * (0.006 - 0.026 * index) * s
    return (rx - 0.021 * s, y - 0.158 * s, rx + 0.021 * s, y - 0.012 * s)


def skeleton(
    box: tuple[float, float, float, float],
    posture: str,
    facing: int,
    phase: float = 0.0,
    reach_to: tuple[float, float] | None = None,
    reach_amount: float = 0.0,
) -> list[tuple[float, float, float]]:
    """COCO-17 keypoints (normalized) for a figure inside ``box``."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    cx = (x1 + x2) / 2
    kp: list[tuple[float, float]] = [(0.0, 0.0)] * NUM_KEYPOINTS
    if posture == "lying":  # on the ground, head towards ``facing``
        cy = (y1 + y2) / 2

        def at(u: float, dy: float = 0.0) -> tuple[float, float]:
            return (cx + facing * w * (u - 0.5), cy + dy * h)

        kp[0] = at(0.94, -0.15)
        kp[1], kp[2], kp[3], kp[4] = at(0.97, -0.25), at(0.97, -0.05), at(0.9, -0.3), at(0.9, 0.0)
        kp[5], kp[6] = at(0.8, -0.3), at(0.8, 0.3)
        kp[7], kp[8] = at(0.66, -0.4), at(0.66, 0.4)
        kp[9], kp[10] = at(0.55, -0.45), at(0.55, 0.45)
        kp[11], kp[12] = at(0.45, -0.22), at(0.45, 0.22)
        kp[13], kp[14] = at(0.25, -0.2), at(0.25, 0.2)
        kp[15], kp[16] = at(0.04, -0.2), at(0.04, 0.2)
        return [(float(px), float(py), 0.9) for px, py in kp]
    if posture in ("sit", "crouch"):
        head_y, sh_y, hip_y = y1 + 0.1 * h, y1 + 0.27 * h, y1 + 0.62 * h
        knee = (cx + facing * 0.45 * w, y1 + 0.68 * h)
        ankle = (cx + facing * 0.35 * w, y1 + 0.95 * h)
        elbow = (cx + facing * 0.45 * w, y1 + 0.42 * h)
        wrist = (cx + facing * 0.85 * w, y1 + 0.45 * h)
        kp[13] = kp[14] = knee
        kp[15] = kp[16] = ankle
        kp[7] = kp[8] = elbow
        kp[9] = kp[10] = wrist
    else:
        head_y, sh_y, hip_y = y1 + 0.09 * h, y1 + 0.22 * h, y1 + 0.55 * h
        swing = {"walk": 0.18, "run": 0.34}.get(posture, 0.0) * w * math.sin(phase)
        kp[13] = (cx - 0.12 * w + swing, y1 + 0.76 * h)
        kp[14] = (cx + 0.12 * w - swing, y1 + 0.76 * h)
        kp[15] = (cx - 0.15 * w + 1.6 * swing, y1 + 0.98 * h)
        kp[16] = (cx + 0.15 * w - 1.6 * swing, y1 + 0.98 * h)
        kp[7] = (cx - 0.38 * w - 0.5 * swing, y1 + 0.39 * h)
        kp[8] = (cx + 0.38 * w + 0.5 * swing, y1 + 0.39 * h)
        kp[9] = (cx - 0.36 * w - swing, y1 + 0.53 * h)
        kp[10] = (cx + 0.36 * w + swing, y1 + 0.53 * h)
        if posture == "phone":
            kp[8] = (cx + facing * 0.42 * w, y1 + 0.27 * h)
            kp[10] = (cx + facing * 0.3 * w, y1 + 0.12 * h)
    kp[0] = (cx + facing * 0.06 * w, head_y)
    kp[1] = (cx + facing * 0.1 * w - 0.05 * w, head_y - 0.02 * h)
    kp[2] = (cx + facing * 0.1 * w + 0.05 * w, head_y - 0.02 * h)
    kp[3] = (cx - 0.12 * w, head_y)
    kp[4] = (cx + 0.12 * w, head_y)
    kp[5] = (cx - 0.32 * w, sh_y)
    kp[6] = (cx + 0.32 * w, sh_y)
    kp[11] = (cx - 0.2 * w, hip_y)
    kp[12] = (cx + 0.2 * w, hip_y)
    if reach_to is not None and reach_amount > 0:
        side = 10 if facing > 0 else 9
        elbow_i = 8 if side == 10 else 7
        sx, sy = kp[6 if side == 10 else 5]
        wx, wy = kp[side]
        tx, ty = reach_to
        a = min(max(reach_amount, 0.0), 1.0)
        kp[side] = (wx + (tx - wx) * a, wy + (ty - wy) * a)
        kp[elbow_i] = ((sx + kp[side][0]) / 2, (sy + kp[side][1]) / 2 - 0.03 * h)
    return [(float(px), float(py), 0.9) for px, py in kp]


@dataclass
class WorldState:
    """Everything the renderer and the pipeline need at time ``t``."""

    t: float
    tracks: list[Track]
    poses: dict[int, Pose]
    draw: list[dict[str, object]]


class World:
    def __init__(self, actors: list[Actor], jitter: float = 0.0015, seed: int = 0, track_offset: int = 0) -> None:
        import random

        self.actors = sorted(actors, key=lambda a: a.t0)
        self.jitter = jitter
        self._rng = random.Random(seed)
        self._id_of: dict[tuple[int, int], int] = {}
        self._next_track = 1 + track_offset

    def _track_id(self, actor_id: int, sub: int = 0) -> int:
        key = (actor_id, sub)
        if key not in self._id_of:
            self._id_of[key] = self._next_track
            self._next_track += 1
        return self._id_of[key]

    def _j(self) -> float:
        return self._rng.gauss(0.0, self.jitter) if self.jitter else 0.0

    def _box(self, b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = (b[0] + self._j(), b[1] + self._j(), b[2] + self._j(), b[3] + self._j())
        return (max(0.0, x1), max(0.0, y1), min(1.0, max(x2, x1 + 1e-3)), min(1.0, max(y2, y1 + 1e-3)))

    def state(self, t: float, wall_ts: float) -> WorldState:
        tracks: list[Track] = []
        poses: dict[int, Pose] = {}
        draw: list[dict[str, object]] = []
        hands: dict[int, tuple[float, float]] = {}
        active = [a for a in self.actors if a.active(t)]
        # pedestrians first: their hands are reach targets
        people = []
        for a in active:
            if a.kind != "person" or a.person is None:
                continue
            x, y = a.pos(t)
            posture = a.posture(t)
            box = person_box(x, y, a.person, posture)
            phase = t * (12.0 if posture == "run" else 7.0) + a.actor_id
            kps = skeleton(box, posture, a.facing(t), phase=phase)
            hands[a.actor_id] = (kps[10][0], kps[10][1]) if posture == "phone" else (kps[9][0], kps[9][1])
            people.append((a, x, y, posture, box, phase, kps))
        for a, x, y, posture, box, phase, kps in people:
            assert a.person is not None
            for r0, r1, target_id, _ in a.reach:  # a pedestrian's hand reaching another's
                if r0 <= t <= r1 and target_id in hands:
                    amount = 1.0 - abs(t - (r0 + r1) / 2) / max((r1 - r0) / 2, 1e-6)
                    kps = skeleton(box, posture, a.facing(t), phase, reach_to=hands[target_id], reach_amount=amount)
            draw.append(
                {
                    "kind": "person",
                    "box": box,
                    "kps": kps,
                    "look": a.person,
                    "phone": posture == "phone",
                    "stand_h": a.person.height * scale_at(y),
                }
            )
            if 0.0 < x < 1.0:
                tid = self._track_id(a.actor_id)
                tracks.append(
                    Track(
                        track_id=tid,
                        cls="person",
                        conf=0.88,
                        bbox=self._box(box),
                        first_seen=wall_ts,
                        last_seen=wall_ts,
                    )
                )
                poses[tid] = Pose(track_id=tid, keypoints=kps)
        for a in active:
            if a.kind == "person":
                continue
            x, y = a.pos(t)
            facing = a.facing(t)
            if a.kind == "motorcycle" and a.vehicle is not None:
                box = bike_box(x, y)
                rider_draw = []
                on = (a.riders_from is None or t >= a.riders_from) and (a.riders_until is None or t < a.riders_until)
                riders = a.vehicle.riders if on else ()
                for i, look in enumerate(riders):
                    rbox = rider_box(x, y, facing, i)
                    target, amount = None, 0.0
                    for r0, r1, target_id, ri in a.reach:
                        if ri == i and r0 <= t <= r1 and target_id in hands:
                            target = hands[target_id]
                            mid = (r0 + r1) / 2
                            amount = 1.0 - abs(t - mid) / max((r1 - r0) / 2, 1e-6)
                    kps = skeleton(rbox, "sit", facing, reach_to=target, reach_amount=amount)
                    rider_draw.append({"box": rbox, "kps": kps, "look": look})
                    if 0.0 < x < 1.0:
                        tid = self._track_id(a.actor_id, i + 1)
                        tracks.append(
                            Track(
                                track_id=tid,
                                cls="person",
                                conf=0.84,
                                bbox=self._box(rbox),
                                first_seen=wall_ts,
                                last_seen=wall_ts,
                            )
                        )
                        poses[tid] = Pose(track_id=tid, keypoints=kps)
                draw.append(
                    {"kind": "motorcycle", "box": box, "look": a.vehicle, "facing": facing, "riders": rider_draw}
                )
                if 0.0 < x < 1.0:
                    tid = self._track_id(a.actor_id)
                    tracks.append(
                        Track(
                            track_id=tid,
                            cls="motorcycle",
                            conf=0.9,
                            bbox=self._box(box),
                            first_seen=wall_ts,
                            last_seen=wall_ts,
                        )
                    )
            elif a.vehicle is not None:
                box = car_box(x, y, a.kind)
                draw.append({"kind": a.kind, "box": box, "look": a.vehicle, "facing": facing})
                if 0.0 < x < 1.0:
                    tid = self._track_id(a.actor_id)
                    tracks.append(
                        Track(
                            track_id=tid,
                            cls=a.kind,
                            conf=0.9,
                            bbox=self._box(box),
                            first_seen=wall_ts,
                            last_seen=wall_ts,
                        )
                    )
        draw.sort(key=lambda d: d["box"][3])  # type: ignore[index]  # painter's order: far to near
        return WorldState(t=t, tracks=tracks, poses=poses, draw=draw)
