"""The six "person in danger" patterns, each a small state machine over ``People``.

Every pattern keeps one calibration unit per episode (a pair walking one behind the other, a person
with people around them, two bodies in contact, a boarding, a time down on the ground) and logs the
episode's highest score, so ``calibrate`` can learn how often ordinary street life looks like it.
Scores are hand-set logistic combinations of interpretable features (same idea as the bike
snatch's B1 baseline); the conformal p-value, not the raw score, decides whether anyone is told.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from jikimi_contracts import TWO_WHEELERS, Track

from ..people import DEPTH, People, Person, distance, same_depth, unit, vec


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Finding:
    pattern: str
    key: str
    """Dedupe key: one alert per pattern and people involved (upgrades go through the gate)."""
    score: float
    start_ts: float
    track_ids: list[int]
    centre: int
    """The person who may be in danger."""
    features: dict[str, Any]


class Pattern:
    name = ""

    def __init__(self) -> None:
        self.log: dict[str, float] | None = None

    def record(self, unit_key: str, s: float) -> None:
        if self.log is not None:
            self.log[unit_key] = max(s, self.log.get(unit_key, 0.0))


def _pairs(people: list[Person], max_d: float) -> Iterable[tuple[Person, Person, float]]:
    for i, a in enumerate(people):
        for b in people[i + 1 :]:
            if not same_depth(a, b):
                continue
            d = distance(a, b)
            if d is not None and d <= max_d:
                yield a, b, d


# ------------------------------------------------------------------ following
@dataclass
class _Follow:
    lead: int
    follower: int
    since: float
    last_ts: float
    last_behind: float
    behind_s: float = 0.0
    matched_stops: int = 0
    matched_speedups: int = 0
    companion: bool = False
    overtaken: bool = False
    stop_open: float | None = None
    stop_matched: bool = False
    lead_speedup: float | None = None
    speedup_matched: bool = False
    gap: list[float] = field(default_factory=list)
    best: float = 0.0
    emitted: float = 0.0


class Following(Pattern):
    """Someone keeps a few steps behind a walker, stops when they stop and hurries when they hurry.
    Friends and families walk *beside* each other, or come up beside them at a stop (companion);
    strangers going the same way do not stop with you and soon overtake."""

    name = "following"

    def __init__(self) -> None:
        super().__init__()
        self.rel: dict[tuple[int, int], _Follow] = {}
        self.heading: dict[int, tuple[float, float]] = {}

    @staticmethod
    def score(r: _Follow) -> float:
        z = (
            -5.5
            + 0.1 * min(r.behind_s, 40.0)
            + 2.0 * min(r.matched_stops, 3)  # stopping with someone while keeping the distance
            + 1.0 * min(r.matched_speedups, 2)
            - 3.0 * r.companion
            - 2.5 * r.overtaken
        )
        return _sig(z)

    def step(self, people: People, ts: float) -> list[Finding]:
        out: list[Finding] = []
        for p in people.current:
            if p.speed >= 0.3:
                self.heading[p.track_id] = unit(p.velocity(1.5))
        for lead in people.current:
            h = self.heading.get(lead.track_id)
            if h is None:
                continue
            for f in people.current:
                if f.track_id == lead.track_id or not same_depth(lead, f):
                    continue
                r = vec(lead, f)
                if r is None:
                    continue
                d = math.hypot(*r)
                along, lateral = r[0] * h[0] + r[1] * h[1], abs(r[0] * h[1] - r[1] * h[0])
                behind = along < -0.8 and lateral < 1.6 and 1.0 <= d <= 8.0
                key = (lead.track_id, f.track_id)
                rel = self.rel.get(key)
                if rel is None:
                    if not (behind and lead.speed >= 0.3 and f.speed >= 0.3):
                        continue
                    rel = self.rel[key] = _Follow(lead.track_id, f.track_id, ts, ts, ts)
                dt = min(ts - rel.last_ts, 0.5)
                rel.last_ts = ts
                fh = unit(f.velocity(1.5))
                if behind and lead.speed >= 0.3 and f.speed >= 0.3 and fh[0] * h[0] + fh[1] * h[1] >= 0.7:
                    rel.behind_s += dt
                    rel.gap.append(d)
                if behind:
                    rel.last_behind = ts
                if along > 0.5 and lead.speed >= 0.2 and f.speed >= 0.2:
                    rel.overtaken = True
                self._stops(rel, lead, f, d, along, ts)
                self._speedups(rel, lead, f, ts)
                s = self.score(rel)
                eligible = (rel.matched_stops >= 1 and rel.behind_s >= 8.0) or (
                    rel.matched_stops + rel.matched_speedups >= 2 and rel.behind_s >= 4.0
                )
                rel.best = max(rel.best, s if eligible else 0.0)  # calibrate on what could alert
                if eligible and s > rel.emitted + 0.05:
                    rel.emitted = s
                    out.append(
                        Finding(
                            self.name,
                            f"following:{lead.track_id}-{f.track_id}",
                            s,
                            rel.since,
                            [lead.track_id, f.track_id],
                            lead.track_id,
                            {
                                "follow_s": round(ts - rel.since),
                                "stops_matched": rel.matched_stops,
                                "speedups_matched": rel.matched_speedups,
                                "gap": round(sorted(rel.gap)[len(rel.gap) // 2], 1) if rel.gap else None,
                            },
                        )
                    )
        for key, rel in list(self.rel.items()):
            lost = ts - rel.last_ts > 3.0
            if lost or (ts - rel.last_behind > 6.0 and rel.stop_open is None) or rel.overtaken:
                if rel.behind_s >= 5.0:
                    self.record(f"{key[0]}-{key[1]}-{rel.since:.0f}", rel.best)
                del self.rel[key]
        return out

    @staticmethod
    def _stops(rel: _Follow, lead: Person, f: Person, d: float, along: float, ts: float) -> None:
        if lead.speed < 0.15:
            if rel.stop_open is None:
                rel.stop_open, rel.stop_matched = ts, False
            if d < 1.0:
                rel.companion = True  # came up beside them: walking together
            if not rel.stop_matched and 0.5 <= ts - rel.stop_open <= 4.0 and f.speed < 0.25 and along < -0.8:
                rel.matched_stops += 1
                rel.stop_matched = True
        elif lead.speed > 0.3:
            rel.stop_open = None

    @staticmethod
    def _speedups(rel: _Follow, lead: Person, f: Person, ts: float) -> None:
        base = lead.baseline_speed(ts, skip_s=1.5, span_s=6.0)
        hurried = base is not None and base >= 0.25 and lead.speed >= max(1.35 * base, 0.6)
        if hurried and (rel.lead_speedup is None or ts - rel.lead_speedup > 6.0):
            rel.lead_speedup, rel.speedup_matched = ts, False
        if rel.lead_speedup is not None and not rel.speedup_matched and ts - rel.lead_speedup <= 2.5:
            fb = f.baseline_speed(ts, skip_s=1.5, span_s=6.0)
            if fb is not None and f.speed >= max(1.35 * fb, 0.6):
                rel.matched_speedups += 1
                rel.speedup_matched = True


# ------------------------------------------------------------------ surrounded
@dataclass
class _Ring:
    centre: int
    since: float
    last_ts: float
    halted: bool
    best_cov: float = 0.0
    max_n: int = 0
    arrivals: dict[int, float] = field(default_factory=dict)
    came_from: dict[int, float] = field(default_factory=dict)
    """neighbour -> bearing (from the centre) of where they were 4 s before closing in."""
    together: int = 0
    spread: float = 0.0
    best: float = 0.0
    emitted: float = 0.0


def coverage(bearings: list[float]) -> float:
    """Share of the full circle around a person that the people next to them close off."""
    if len(bearings) < 2:
        return 0.0
    b = sorted(x % (2 * math.pi) for x in bearings)
    gaps = [b[i + 1] - b[i] for i in range(len(b) - 1)] + [2 * math.pi - b[-1] + b[0]]
    return 1.0 - max(gaps) / (2 * math.pi)


class Surrounded(Pattern):
    """Several people close in on one person from different sides at once. Someone *on* a circle
    of friends never has others all round them (they are all on one side), the person in the
    middle of a ring does; and a group arriving together, from different sides, within seconds is
    not how customers reach a stall or friends a meeting point."""

    name = "surrounded"
    radius = 1.3

    def __init__(self) -> None:
        super().__init__()
        self.rings: dict[int, _Ring] = {}

    @staticmethod
    def score(r: _Ring, ts: float) -> float:
        z = (
            -6.5
            + 0.6 * (min(r.max_n, 4) - 2)
            + 3.0 * r.best_cov
            + 1.0 * (r.together >= 2)
            + 1.0 * (r.together >= 3)
            + 1.0 * r.spread
            + 1.5 * (r.halted and r.together >= 2)  # stopped by people closing in, not by arriving
            + 0.05 * min(ts - r.since, 20.0)
            - 1.0 * (r.max_n >= 6)  # a gathering (a crowded corner, a stall), not a ring round one
        )
        return _sig(z)

    @staticmethod
    def closing_in(r: _Ring) -> tuple[int, float]:
        """Most people who closed in within 4 s of each other (a coordinated approach; friends
        and customers arrive one by one), and whether they came from directions at least 120
        degrees apart (1.0) rather than together from one side."""
        q = sorted((r.arrivals[k], b) for k, b in r.came_from.items())
        best, spread = 0, 0.0
        for i in range(len(q)):
            group = [b for t, b in q if q[i][0] <= t <= q[i][0] + 4.0]
            if len(group) >= 2 and len(group) >= best:
                best = len(group)
                spread = max(spread, 1.0 if coverage(group) >= 1 / 3 - 1e-6 else 0.0)
        return best, spread

    def step(self, people: People, ts: float) -> list[Finding]:
        out: list[Finding] = []
        for p in people.current:
            near = []
            for q in people.current:
                if q.track_id == p.track_id or not same_depth(p, q):
                    continue
                v = vec(p, q)
                if v is not None and math.hypot(*v) <= self.radius:
                    near.append((q, math.atan2(v[1], v[0])))
            cov = coverage([b for _, b in near]) if len(near) >= 2 else 0.0
            ring = self.rings.get(p.track_id)
            if cov < 0.55:
                continue
            if ring is None:
                base = p.baseline_speed(ts, skip_s=2.0, span_s=8.0)
                ring = self.rings[p.track_id] = _Ring(
                    p.track_id, ts, ts, halted=base is not None and base >= 0.3 and p.speed < 0.25
                )
            ring.last_ts = ts
            ring.best_cov, ring.max_n = max(ring.best_cov, cov), max(ring.max_n, len(near))
            for q, _ in near:
                if q.track_id not in ring.arrivals:
                    ring.arrivals[q.track_id] = ts
                    q_then = q.pos_at(ts - 4.0) or (q.feet[0][1], q.feet[0][2])  # or where they appeared
                    s_ = (p.size + q.size) / 2
                    v = ((q_then[0] - p.pos[0]) / s_, DEPTH * (q_then[1] - p.pos[1]) / s_)
                    if math.hypot(*v) >= 2.0:
                        ring.came_from[q.track_id] = math.atan2(v[1], v[0])
                    n_in, spread = self.closing_in(ring)
                    ring.together, ring.spread = max(ring.together, n_in), max(ring.spread, spread)
            s = self.score(ring, ts)
            eligible = ring.max_n >= 3 and ts - ring.since >= 3.0  # two people either side: too common
            ring.best = max(ring.best, s if eligible else 0.0)
            if eligible and s > ring.emitted + 0.05:
                ring.emitted = s
                out.append(
                    Finding(
                        self.name,
                        f"surrounded:{p.track_id}",
                        s,
                        ring.since,
                        [p.track_id, *sorted(ring.arrivals)],
                        p.track_id,
                        {
                            "people_around": ring.max_n,
                            "closed_in_pct": round(100 * ring.best_cov),
                            "came_together": ring.together,
                            "duration_s": round(ts - ring.since),
                        },
                    )
                )
        for cid, ring in list(self.rings.items()):
            if ts - ring.last_ts > 2.0:
                self.record(f"{cid}-{ring.since:.0f}", ring.best)
                del self.rings[cid]
        return out


# ------------------------------------------------------------------ contact: struggle and dragging
@dataclass
class _Contact:
    a: int
    b: int
    since: float
    last_ts: float
    agitated_s: float = 0.0
    peak: float = 0.0
    comove_s: float = 0.0
    dragged_s: float = 0.0
    best_struggle: float = 0.0
    best_drag: float = 0.0
    emitted_struggle: float = 0.0
    emitted_drag: float = 0.0


class Contact(Pattern):
    """Two bodies in contact. ``struggle``: both pushed and pulled about (their velocities swing
    back and forth) for seconds; a hug or a handshake is contact without that. ``dragged``: they
    move off together while one of them is held low (bent, sitting, on the ground) or keeps
    jerking against it; friends arm in arm and a parent leading a child walk upright and smooth."""

    name = "contact"
    agitation = 0.4
    touch = 0.6
    """Feet this close (body sizes): the two bodies are against each other."""

    def __init__(self) -> None:
        super().__init__()
        self.pairs: dict[tuple[int, int], _Contact] = {}
        self.drag_log: dict[str, float] | None = None
        self.resist: dict[int, tuple[float, float]] = {}
        """person -> (last ts, how hard they were held or fought, 0..1): for boardings."""
        self.touched: dict[int, float] = {}
        """person -> last time anyone was in contact with them (for falls)."""

    @staticmethod
    def struggle_score(c: _Contact) -> float:
        return _sig(-5.0 + 1.0 * min(c.agitated_s, 6.0) + 1.0 * min(c.peak, 2.0))

    @staticmethod
    def drag_score(c: _Contact) -> float:
        return _sig(-4.5 + 1.5 * min(c.dragged_s, 5.0) + 0.1 * min(c.comove_s, 10.0))

    def step(self, people: People, ts: float) -> list[Finding]:
        out: list[Finding] = []
        seen: set[tuple[int, int]] = set()
        for a, b, d in _pairs(people.current, 0.85):
            key = (min(a.track_id, b.track_id), max(a.track_id, b.track_id))
            seen.add(key)
            self.touched[a.track_id] = self.touched[b.track_id] = ts
            c = self.pairs.get(key)
            if c is None:
                c = self.pairs[key] = _Contact(key[0], key[1], ts, ts)
            dt = min(ts - c.last_ts, 0.5)
            c.last_ts = ts
            jit = (a.jitter(ts) + b.jitter(ts)) / 2
            flips = min(a.reversals(ts), b.reversals(ts))
            touching = d <= self.touch
            # pushed and pulled: big velocity swings that keep reversing, while the bodies stay
            # against each other (children playing tag rarely stay this close; starting and
            # stopping to walk swings the velocity once, not back and forth)
            if touching and jit >= self.agitation and flips >= 2:
                c.agitated_s += dt
                c.peak = max(c.peak, jit)
            va, vb = a.velocity(), b.velocity()
            sa, sb = math.hypot(*va), math.hypot(*vb)
            together = (
                0.2 <= sa <= 1.2  # a body being hauled along cannot go faster than this
                and 0.2 <= sb <= 1.2
                and 0.6 <= sa / sb <= 1.67
                and (va[0] * vb[0] + va[1] * vb[1]) / (sa * sb) >= 0.8
            )
            if together:
                c.comove_s += dt
                held = (
                    a.posture != "upright"
                    or b.posture != "upright"
                    or (touching and jit >= self.agitation and flips >= 2)
                )
                if held:
                    c.dragged_s += dt
            fight = _clip(c.agitated_s / 3.0)
            drag = _clip(c.dragged_s / 2.0)
            for p in (a, b):
                self.resist[p.track_id] = (ts, max(fight, drag, self.resist.get(p.track_id, (0, 0.0))[1]))
            out.extend(self._findings(c, a, b, ts))
        for key, c in list(self.pairs.items()):
            if key not in seen and ts - c.last_ts > 1.5:
                unit = f"{key[0]}-{key[1]}-{c.since:.0f}"
                self.record(unit, c.best_struggle)
                if self.drag_log is not None and c.comove_s >= 1.0:
                    self.drag_log[unit] = max(c.best_drag, self.drag_log.get(unit, 0.0))
                del self.pairs[key]
        for pid in [p for p, (t, _) in self.resist.items() if ts - t > 15.0]:
            del self.resist[pid]
        return out

    def _findings(self, c: _Contact, a: Person, b: Person, ts: float) -> list[Finding]:
        out = []
        s1, s2 = self.struggle_score(c), self.drag_score(c)
        fight, drag = c.agitated_s >= 2.0, c.dragged_s >= 1.5
        c.best_struggle = max(c.best_struggle, s1 if fight else 0.0)
        c.best_drag = max(c.best_drag, s2 if drag else 0.0)
        ids = [c.a, c.b]
        if fight and s1 > c.emitted_struggle + 0.05:
            c.emitted_struggle = s1
            out.append(
                Finding(
                    "struggle",
                    f"struggle:{c.a}-{c.b}",
                    s1,
                    c.since,
                    ids,
                    c.a,
                    {"struggle_s": round(c.agitated_s, 1), "agitation": round(c.peak, 2)},
                )
            )
        if drag and s2 > c.emitted_drag + 0.05:
            c.emitted_drag = s2
            low = a if a.posture != "upright" else b
            out.append(
                Finding(
                    "dragged",
                    f"dragged:{c.a}-{c.b}",
                    s2,
                    c.since,
                    ids,
                    low.track_id,
                    {"dragged_s": round(c.dragged_s, 1), "moved_together_s": round(c.comove_s, 1)},
                )
            )
        return out


# ------------------------------------------------------------------ forced into a vehicle
@dataclass
class _Boarding:
    person: int
    vehicle: int
    ts: float
    spot: tuple[float, float]
    size: float
    resist: float
    escorted: bool = False
    departed: float | None = None
    top_speed: float = 0.0
    vehicle_gone: float | None = None


class Boarding(Pattern):
    """A person disappears into a car, van or rickshaw. Ordinary boardings are the calibration
    units; the score rises only if they were held or fought in the seconds before, went in
    together with the person holding them, and the vehicle drove off at once and fast."""

    name = "forced_into_vehicle"

    def __init__(self, contact: Contact) -> None:
        super().__init__()
        self.contact = contact
        self.open: list[_Boarding] = []

    @staticmethod
    def score(b: _Boarding) -> float:
        quick = b.departed is not None and b.departed - b.ts <= 8.0
        fast = _clip((b.top_speed - 1.0) / 1.5)
        return _sig(-5.0 + 3.5 * b.resist + 1.2 * b.escorted + 1.0 * fast + 0.8 * quick)

    def step(self, people: People, ts: float, tracks: list[Track], new_ids: frozenset[int]) -> list[Finding]:
        out: list[Finding] = []
        vehicles = {t.track_id: t for t in people.vehicles if t.cls not in TWO_WHEELERS}
        for p in people.gone:
            v = self._vehicle_at(p, vehicles.values())
            if v is None:
                continue
            t_r, r = self.contact.resist.get(p.track_id, (0.0, 0.0))
            resist = r if ts - t_r <= 12.0 else 0.0
            b = _Boarding(p.track_id, v.track_id, ts, p.pos, p.size, resist)
            for other in self.open:  # went in with the person who held them
                same = other.vehicle == v.track_id and abs(other.ts - ts) <= 3.0
                held = self.contact.touched.get(other.person, -1e9) >= ts - 5.0 and max(resist, other.resist) > 0
                if same and held:
                    b.escorted = other.escorted = True
            self.open.append(b)
        for b in list(self.open):
            if any(  # the same body came back out from behind the vehicle: it was only hidden
                (p.track_id == b.person or p.track_id in new_ids)
                and math.hypot(p.pos[0] - b.spot[0], p.pos[1] - b.spot[1]) <= 0.8 * b.size
                and ts - b.ts <= 3.0
                and ts > b.ts
                for p in people.current
            ):
                self.open.remove(b)
                continue
            v = vehicles.get(b.vehicle)
            if v is not None:
                speed = v.speed / max(v.width, 1e-3)  # vehicle widths per second
                if b.departed is None and speed >= 0.5:
                    b.departed = ts
                if b.departed is not None and ts - b.departed <= 5.0:
                    b.top_speed = max(b.top_speed, speed)
            elif b.vehicle_gone is None:
                b.vehicle_gone = ts
                if b.departed is None:
                    b.departed = ts
            done = (b.departed is not None and ts - b.departed >= 3.0) or ts - b.ts > 30.0
            if not done:
                continue
            self.open.remove(b)
            s = self.score(b)
            self.record(f"{b.person}-{b.vehicle}-{b.ts:.0f}", s if b.resist > 0 else 0.0)
            if b.resist > 0:
                out.append(
                    Finding(
                        self.name,
                        f"forced:{b.vehicle}",  # one alert per vehicle, however many went in
                        s,
                        b.ts - 5.0,
                        [b.person, b.vehicle],
                        b.person,
                        {
                            "vehicle": next((t.cls for t in tracks if t.track_id == b.vehicle), "car"),
                            "escorted": b.escorted,
                            "drove_off_s": round(b.departed - b.ts, 1) if b.departed else None,
                        },
                    )
                )
        return out

    @staticmethod
    def _vehicle_at(p: Person, vehicles: Iterable[Track]) -> Track | None:
        x, y = p.pos
        best, best_d = None, math.inf
        for v in vehicles:
            x1, y1, x2, y2 = v.bbox
            pad = 0.4 * p.size
            if x1 - pad <= x <= x2 + pad and y1 <= y <= y2 + 0.6 * p.size:
                d = abs(x - (x1 + x2) / 2)
                if d < best_d:
                    best, best_d = v, d
        return best


# ------------------------------------------------------------------ fall
@dataclass
class _Down:
    person: int
    since: float
    last_ts: float
    sudden: bool = False
    lying_s: float = 0.0
    after_contact: bool = False
    up_since: float | None = None
    best: float = 0.0
    emitted: float = 0.0


class Fall(Pattern):
    """A person goes down. Sitting, crouching, bending and lying down to sleep are the everyday
    units; a fall is going from upright to lying within a second and a half, then staying down
    (a new track that starts lying where an upright one just vanished counts: trackers often
    lose a falling body for a moment)."""

    name = "fall"

    def __init__(self, contact: Contact) -> None:
        super().__init__()
        self.contact = contact
        self.down: dict[int, _Down] = {}
        self._recent_up: list[tuple[float, float, float, float]] = []
        """(ts gone, x, y, size) of upright people who just vanished."""

    @staticmethod
    def score(d: _Down, ts: float) -> float:
        lying = d.lying_s >= 1.0
        return _sig(-5.5 + 3.0 * d.sudden + 0.15 * min(ts - d.since, 20.0) + 1.0 * lying + 1.0 * d.after_contact)

    def step(self, people: People, ts: float) -> list[Finding]:
        out: list[Finding] = []
        for p in people.gone:
            if p.posture == "upright":
                self._recent_up.append((ts, *p.pos, p.size))
        self._recent_up = [r for r in self._recent_up if ts - r[0] <= 1.5]
        for p in people.current:
            d = self.down.get(p.track_id)
            if p.posture == "upright":
                if d is not None:
                    d.up_since = d.up_since or ts
                    if ts - d.up_since >= 1.0:
                        self._close(d)
                continue
            if d is None:
                d = self.down[p.track_id] = _Down(p.track_id, p.posture_since, ts)
                d.after_contact = self.contact.touched.get(p.track_id, -1e9) >= p.posture_since - 3.0
            dt = min(ts - d.last_ts, 0.5)
            d.last_ts, d.up_since = ts, None
            if p.posture == "lying":
                if d.lying_s == 0.0:
                    fast = p.upright_ts is not None and p.posture_since - p.upright_ts <= 1.5
                    reborn = p.first_ts >= ts - 0.5 and any(
                        math.hypot(x - p.pos[0], y - p.pos[1]) <= 0.8 * s for _, x, y, s in self._recent_up
                    )
                    d.sudden = fast or reborn
                d.lying_s += dt
            s = self.score(d, ts)
            eligible = d.lying_s >= 1.0 and ts - d.since >= 4.0
            d.best = max(d.best, s if eligible else 0.0)
            if eligible and s > d.emitted + 0.05:
                d.emitted = s
                out.append(
                    Finding(
                        self.name,
                        f"fall:{p.track_id}",
                        s,
                        d.since,
                        [p.track_id],
                        p.track_id,
                        {"down_s": round(ts - d.since), "sudden": d.sudden, "after_contact": d.after_contact},
                    )
                )
        for d in list(self.down.values()):
            if ts - d.last_ts > 3.0:
                self._close(d)
        return out

    def _close(self, d: _Down) -> None:
        if d.last_ts - d.since >= 1.0:
            self.record(f"{d.person}-{d.since:.0f}", d.best)
        self.down.pop(d.person, None)
