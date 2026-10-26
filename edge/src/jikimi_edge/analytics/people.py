"""People on foot, measured for the person-safety plugins (foot snatch, person in danger, crowd).

Everything is in *body sizes* (a person's standing height), so one threshold holds near and far
from the camera. Ground offsets use foot points with the image's vertical stretched by ``DEPTH``:
on a pole-mounted CCTV view a metre towards the camera covers far fewer pixels than a metre
sideways. A crouching, sitting or lying person keeps the size they had standing, which is how a
fall is told from a person walking away from the camera.

Postures come from the box alone (no pose model needed): ``upright`` (box as tall as the body),
``low`` (crouching, sitting, bent over) and ``lying`` (low and wider than tall). They are not
trusted while a vehicle hides part of the body or the box touches the frame edge.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import pairwise

from jikimi_contracts import VEHICLE_CLASSES, Track

from .geometry import intersection_over

DEPTH = 2.5
RUN = 1.3
"""Body heights per second: people walk at ~0.5-0.9 and run at 2-3."""
UPRIGHT, LYING = 0.8, 0.45
"""Box height over standing size: below UPRIGHT a body is low, below LYING (and wide) lying."""


@dataclass
class Person:
    track_id: int
    size: float
    first_ts: float
    last_ts: float
    feet: deque[tuple[float, float, float]] = field(default_factory=lambda: deque(maxlen=200))
    speeds: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=200))
    posture: str = "upright"
    posture_since: float = 0.0
    upright_ts: float | None = None
    """Last time this body was seen upright."""
    track: Track | None = None

    @property
    def pos(self) -> tuple[float, float]:
        _, x, y = self.feet[-1]
        return (x, y)

    def pos_at(self, ts: float) -> tuple[float, float] | None:
        """Foot point at (or just before) ``ts``; ``None`` before the track began."""
        for t, x, y in reversed(self.feet):
            if t <= ts:
                return (x, y)
        return None

    def velocity(self, window_s: float = 0.8) -> tuple[float, float]:
        """Ground velocity in body sizes per second (x sideways, y towards the camera)."""
        if len(self.feet) < 2:
            return (0.0, 0.0)
        t1, x1, y1 = self.feet[-1]
        ref = self.feet[0]
        for p in reversed(self.feet):
            if t1 - p[0] >= window_s:
                ref = p
                break
        dt = t1 - ref[0]
        if dt <= 1e-6:
            return (0.0, 0.0)
        return ((x1 - ref[1]) / dt / self.size, DEPTH * (y1 - ref[2]) / dt / self.size)

    @property
    def speed(self) -> float:
        return self.speeds[-1][1] if self.speeds else 0.0

    def baseline_speed(self, now: float, skip_s: float = 2.0, span_s: float = 10.0) -> float | None:
        """Median speed before the last ``skip_s`` (what this person was doing until just now)."""
        vals = [s for t, s in self.speeds if now - span_s <= t <= now - skip_s]
        return statistics.median(vals) if len(vals) >= 3 else None

    def max_speed(self, t0: float, t1: float) -> float:
        return max((s for t, s in self.speeds if t0 <= t <= t1), default=0.0)

    def jitter(self, now: float, span_s: float = 1.5) -> float:
        """How much the velocity swings around (body sizes/s): a body pushed and pulled about."""
        vs = [(t, x, y) for t, x, y in self.feet if now - span_s <= t]
        if len(vs) < 5:
            return 0.0
        steps = []
        for (ta, xa, ya), (tb, xb, yb) in pairwise(vs):
            dt = tb - ta
            if dt > 1e-6:
                steps.append(((xb - xa) / dt / self.size, DEPTH * (yb - ya) / dt / self.size))
        if len(steps) < 3:
            return 0.0
        return math.hypot(statistics.pstdev(s[0] for s in steps), statistics.pstdev(s[1] for s in steps))

    def reversals(self, now: float, span_s: float = 1.5, min_speed: float = 0.3) -> int:
        """Times the sideways velocity changed sign (both sides faster than ``min_speed``)."""
        vs = [(t, x) for t, x, _ in self.feet if now - span_s - 0.4 <= t]
        vel = []
        for i in range(2, len(vs)):  # two-step velocity: frame jitter alone rarely flips it
            dt = vs[i][0] - vs[i - 2][0]
            if dt > 1e-6:
                vel.append((vs[i][1] - vs[i - 2][1]) / dt / self.size)
        flips, last = 0, 0
        for v in vel:
            if abs(v) < min_speed:
                continue
            sign = 1 if v > 0 else -1
            if last and sign != last:
                flips += 1
            last = sign
        return flips


class People:
    """Pedestrians of one camera (riders excluded), updated once per frame."""

    def __init__(self, forget_s: float = 20.0) -> None:
        self.forget_s = forget_s
        self.by_id: dict[int, Person] = {}
        self.current: list[Person] = []
        self.gone: list[Person] = []
        """People who were there on the previous frame and are not any more."""
        self.vehicles: list[Track] = []

    def update(self, pedestrians: Iterable[Track], tracks: Iterable[Track], ts: float) -> list[Person]:
        self.vehicles = [t for t in tracks if t.cls in VEHICLE_CLASSES]
        before = {p.track_id for p in self.current}
        self.current = []
        for t in pedestrians:
            p = self.by_id.get(t.track_id)
            upright_box = t.height >= 1.9 * t.width
            if p is None:
                size = t.height if upright_box else max(t.height, t.width / 0.9)
                p = self.by_id[t.track_id] = Person(t.track_id, max(size, 0.02), ts, ts, posture_since=ts)
            elif upright_box and self._trusted(t) and t.height < 1.5 * p.size:
                p.size = 0.85 * p.size + 0.15 * t.height
            fx, fy = t.foot
            p.feet.append((ts, fx, fy))
            vx, vy = p.velocity()
            p.speeds.append((ts, math.hypot(vx, vy)))
            p.last_ts, p.track = ts, t
            if self._trusted(t):
                ratio = t.height / p.size
                posture = (
                    "upright" if ratio >= UPRIGHT else ("lying" if ratio < LYING and t.width > t.height else "low")
                )
                if posture != p.posture:
                    p.posture, p.posture_since = posture, ts
            if p.posture == "upright":
                p.upright_ts = ts
            self.current.append(p)
        now = {p.track_id for p in self.current}
        self.gone = [self.by_id[i] for i in before - now if i in self.by_id]
        for k in [k for k, p in self.by_id.items() if ts - p.last_ts > self.forget_s]:
            del self.by_id[k]
        return self.current

    def _trusted(self, t: Track) -> bool:
        """A box clipped by the frame or partly hidden by a vehicle says nothing about posture."""
        x1, y1, x2, y2 = t.bbox
        if x1 < 0.005 or x2 > 0.995 or y2 > 0.995 or y1 < 0.005:
            return False
        return all(intersection_over(t.bbox, v.bbox) < 0.2 for v in self.vehicles)


def size_of(a: Person, b: Person) -> float:
    return (a.size + b.size) / 2


def same_depth(a: Person, b: Person, low: float = 0.67, high: float = 1.5) -> bool:
    return low <= a.size / b.size <= high


def vec(a: Person, b: Person, ts: float | None = None) -> tuple[float, float] | None:
    """Where ``b`` is relative to ``a`` on the ground, in body sizes (at ``ts`` if given)."""
    pa = a.pos if ts is None else a.pos_at(ts)
    pb = b.pos if ts is None else b.pos_at(ts)
    if pa is None or pb is None:
        return None
    s = size_of(a, b)
    return ((pb[0] - pa[0]) / s, DEPTH * (pb[1] - pa[1]) / s)


def distance(a: Person, b: Person, ts: float | None = None) -> float | None:
    v = vec(a, b, ts)
    return None if v is None else math.hypot(*v)


def unit(v: tuple[float, float]) -> tuple[float, float]:
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n > 1e-9 else (0.0, 0.0)


def is_night(ts: float, tz_offset_s: float) -> bool:
    hour = ((ts + tz_offset_s) % 86400) / 3600
    return hour >= 20 or hour < 6


def others_near(people: list[Person], centre: Person, exclude: set[int], radius: float = 8.0) -> int:
    """Other pedestrians within ``radius`` body sizes (anyone who could see or help)."""
    n = 0
    for p in people:
        if p.track_id in exclude or p.track_id == centre.track_id:
            continue
        d = distance(centre, p)
        if d is not None and d <= radius:
            n += 1
    return n
