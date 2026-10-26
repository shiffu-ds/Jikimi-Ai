"""Scenario library: background traffic + scripted events (PakSnatch categories, Section 9.3).

Used by the live demo, the golden replay suite (``eval/golden``) and simulator calibration.
Hard negatives (delivery drop, asking directions) are first-class: the golden suite keeps them
at >= 40 % of cases, as the plan requires.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .world import Actor, Keyframe, PersonLook, VehicleLook

BIKE_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (28, 28, 30),
    "red": (40, 40, 195),
    "blue": (170, 85, 30),
    "white": (228, 228, 228),
    "silver": (172, 172, 168),
    "green": (50, 150, 50),
    "yellow": (30, 195, 225),
}
SHIRTS = [
    (200, 200, 205), (60, 60, 160), (150, 110, 60), (40, 120, 40), (220, 220, 230), (120, 60, 120), (30, 100, 170),
    (90, 90, 90), (40, 160, 200), (170, 70, 40), (110, 160, 90), (60, 40, 90), (200, 150, 120), (20, 80, 60),
]  # fmt: skip
PANTS = [(60, 60, 60), (110, 100, 80), (130, 130, 120), (90, 70, 50), (40, 40, 70)]
SKINS = [(110, 150, 200), (95, 135, 185), (125, 165, 210), (80, 120, 170)]
HELMETS = [(20, 20, 20), (200, 200, 200), (30, 30, 170), (160, 90, 20)]

FAR_LANE, NEAR_LANE = 0.56, 0.75
FAR_WALK, NEAR_WALK = 0.445, 0.93


@dataclass
class Scenario:
    name: str
    camera_id: str
    layout: str
    duration_s: float
    actors: list[Actor]
    covered: list[tuple[float, float]] = field(default_factory=list)
    night: bool = False
    expected: list[dict[str, Any]] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)
    note: str = ""

    def is_covered(self, t: float) -> bool:
        return any(a <= t <= b for a, b in self.covered)


class _Ids:
    def __init__(self, start: int = 1) -> None:
        self.n = start

    def __call__(self) -> int:
        self.n += 1
        return self.n


def jitter(c: tuple[int, int, int], rng: random.Random, amount: int = 28) -> tuple[int, int, int]:
    """Real clothes and paint vary continuously; a 7-colour palette makes everyone look alike."""
    return tuple(max(0, min(255, v + rng.randint(-amount, amount))) for v in c)  # type: ignore[return-value]


def person_look(rng: random.Random, helmet: bool = False, height: float = 0.15) -> PersonLook:
    return PersonLook(
        shirt=jitter(rng.choice(SHIRTS), rng),
        pants=jitter(rng.choice(PANTS), rng, 18),
        skin=rng.choice(SKINS),
        helmet=rng.choice(HELMETS) if helmet else None,
        height=height * rng.uniform(0.93, 1.07),
    )


def crossing(actor_id: int, kind: str, t0: float, y: float, speed: float, direction: int, **kw: Any) -> Actor:
    x0, x1 = (-0.08, 1.08) if direction > 0 else (1.08, -0.08)
    dur = abs(x1 - x0) / speed
    return Actor(actor_id=actor_id, kind=kind, path=[Keyframe(t0, x0, y), Keyframe(t0 + dur, x1, y)], **kw)


def slowed_crossing(
    actor_id: int,
    t0: float,
    y: float,
    speed: float,
    direction: int,
    at_x: float,
    slow_s: float,
    slow_speed: float = 0.02,
    **kw: Any,
) -> Actor:
    """Cross the frame but crawl for ``slow_s`` seconds around ``at_x``."""
    x0, x1 = (-0.08, 1.08) if direction > 0 else (1.08, -0.08)
    span = slow_speed * slow_s
    a = at_x - direction * span / 2
    b = at_x + direction * span / 2
    t_a = t0 + abs(a - x0) / speed
    t_b = t_a + slow_s
    t_end = t_b + abs(x1 - b) / speed
    return Actor(
        actor_id=actor_id,
        kind="motorcycle",
        path=[Keyframe(t0, x0, y), Keyframe(t_a, a, y), Keyframe(t_b, b, y), Keyframe(t_end, x1, y)],
        **kw,
    )


def background_traffic(
    duration_s: float, rng: random.Random, ids: _Ids, t0: float = 0.0, density: float = 1.0, slow_p: float = 0.05
) -> list[Actor]:
    actors: list[Actor] = []

    def arrivals(rate: float) -> list[float]:
        out, t = [], t0
        while True:
            t += rng.expovariate(rate * density)
            if t >= t0 + duration_s:
                return out
            out.append(t)

    for t in arrivals(1 / 11):
        far = rng.random() < 0.5
        y = (FAR_LANE if far else NEAR_LANE) + rng.uniform(-0.02, 0.02)
        direction = -1 if far else 1
        riders = [person_look(rng, helmet=rng.random() < 0.4)]
        if rng.random() < 0.35:
            riders.append(person_look(rng))
        color = rng.choice(list(BIKE_COLORS))
        look = VehicleLook(
            body=jitter(BIKE_COLORS[color], rng, 20),
            riders=tuple(riders),
            delivery_box=(30, 30, 200) if rng.random() < 0.08 else None,
            color=color,
        )
        speed = rng.uniform(0.17, 0.32)
        if rng.random() < slow_p:
            actors.append(
                slowed_crossing(
                    ids(), t, y, speed, direction, rng.uniform(0.3, 0.7), rng.uniform(1.0, 2.5), vehicle=look
                )
            )
        else:
            actors.append(crossing(ids(), "motorcycle", t, y, speed, direction, vehicle=look))
    for t in arrivals(1 / 26):
        far = rng.random() < 0.5
        kind = "car" if rng.random() < 0.75 else "rickshaw"
        body = rng.choice([(200, 200, 200), (40, 40, 40), (150, 40, 30), (30, 30, 150), (60, 170, 60)])
        actors.append(
            crossing(
                ids(),
                kind,
                t,
                (0.6 if far else 0.79) + rng.uniform(-0.01, 0.01),
                rng.uniform(0.14, 0.24),
                -1 if far else 1,
                vehicle=VehicleLook(body=body),
            )
        )
    for t in arrivals(1 / 13):
        far = rng.random() < 0.6
        y = (FAR_WALK if far else NEAR_WALK) + rng.uniform(-0.012, 0.012)
        actors.append(
            crossing(ids(), "person", t, y, rng.uniform(0.03, 0.06), rng.choice((-1, 1)), person=person_look(rng))
        )
    return actors


def standing_person(
    actor_id: int, t0: float, t1: float, x: float, y: float, look: PersonLook, phone_until: float | None = None
) -> Actor:
    return Actor(
        actor_id=actor_id,
        kind="person",
        path=[Keyframe(t0, x, y), Keyframe(t1, x, y)],
        person=look,
        postures=[(t0, "stand")],
        phone_until=phone_until,
    )


# ------------------------------------------------------------------ scripted events
def add_loitering(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, gap_s: float = 45.0) -> dict[str, Any]:
    look = VehicleLook(
        body=BIKE_COLORS["black"],
        riders=(
            PersonLook(shirt=(225, 225, 230), pants=(120, 120, 110), skin=(110, 150, 200)),
            PersonLook(shirt=(40, 110, 170), pants=(130, 130, 120), skin=(95, 135, 185)),
        ),
    )
    waiting = standing_person(ids(), t0 - 5, t0 + 4 * gap_s + 25, 0.66, 0.455, person_look(rng))
    actors.append(waiting)
    for i in range(4):
        t = t0 + i * gap_s
        far = i % 2 == 1  # slow passes use the lane next to the gate, where the person waits
        y = FAR_LANE if far else NEAR_LANE - 0.06
        direction = -1 if far else 1
        if i in (1, 3):
            actors.append(slowed_crossing(ids(), t, y, 0.24, direction, 0.66, 3.0, 0.015, vehicle=look, label="loiter"))
        else:
            actors.append(crossing(ids(), "motorcycle", t, y, 0.24, direction, vehicle=look, label="loiter"))
    return {"type": "loitering", "t_s": [t0 + gap_s, t0 + 3 * gap_s + 10], "min_route": "VERIFY"}


def add_snatch(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Bike slows next to a pedestrian, a rider's hand reaches the phone, the bike speeds away.

    ``params`` randomise the encounter for synthetic training data (direction, speeds, lane,
    meeting point, reach timing, which rider reaches, jerk size).
    """
    p = {
        "direction": 1,
        "speed": 0.26,
        "depart_speed": 0.55,
        "x_meet": 0.41,
        "y": 0.535,
        "reach_rider": 1,
        "reach_lead": 0.25,
        "reach_len": 0.9,
        "jerk": (-0.035, 0.03),
        "victim_y": 0.47,
        "phone": True,
        **(params or {}),
    }
    d = int(p["direction"])
    victim_id = ids()
    victim_x = p["x_meet"] + 0.02 * d
    victim = Actor(
        actor_id=victim_id,
        kind="person",
        path=[Keyframe(t0 - 12, victim_x, p["victim_y"]), Keyframe(t0 + 14, victim_x, p["victim_y"])],
        person=PersonLook(shirt=jitter((150, 200, 230), rng), pants=(70, 60, 50), skin=rng.choice(SKINS)),
        postures=[(t0 - 12, "stand")],
        phone_until=(t0 + 0.6) if p["phone"] else None,
        jerks=[(t0 + 0.45, t0 + 0.75, p["jerk"][0] * d, p["jerk"][1])],
        label="victim",
    )
    actors.append(victim)
    speed, x_meet, y = p["speed"], p["x_meet"], p["y"]
    x0 = -0.08 if d > 0 else 1.08
    x_end = 1.08 if d > 0 else -0.08
    slow_start = x_meet - 0.04 * d
    t_start = t0 - 1.6 - abs(slow_start - x0) / speed
    look = VehicleLook(
        body=jitter(BIKE_COLORS[rng.choice(["red", "black", "blue", "silver"])], rng, 15),
        riders=(person_look(rng, helmet=rng.random() < 0.3), person_look(rng)),
    )
    bike = Actor(
        actor_id=ids(),
        kind="motorcycle",
        path=[
            Keyframe(t_start, x0, y),
            Keyframe(t0 - 1.6, slow_start, y),
            Keyframe(t0 + 0.5, x_meet + 0.005 * d, y),
            Keyframe(t0 + 1.2, x_meet + 0.08 * d, y),
            Keyframe(t0 + 1.2 + abs(x_end - x_meet - 0.08 * d) / p["depart_speed"], x_end, y),
        ],
        vehicle=look,
        reach=[(t0 - p["reach_lead"], t0 - p["reach_lead"] + p["reach_len"], victim_id, int(p["reach_rider"]))],
        label="snatch",
    )
    actors.append(bike)
    return {
        "type": "snatch",
        "t_s": [t0 - 1, t0 + 6],
        "min_route": "VERIFY",
        "bike_actor": bike.actor_id,
        "victim_actor": victim_id,
    }


def add_delivery(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> dict[str, Any]:
    resident_id = ids()
    gx, gy = 0.66, 0.445
    actors.append(
        Actor(
            actor_id=resident_id,
            kind="person",
            path=[
                Keyframe(t0 + 2, gx, gy),
                Keyframe(t0 + 5, 0.6, 0.47),
                Keyframe(t0 + 9, 0.6, 0.47),
                Keyframe(t0 + 12.5, gx, gy),
            ],
            person=person_look(rng),
            label="resident",
        )
    )
    look = VehicleLook(body=BIKE_COLORS["blue"], riders=(person_look(rng, helmet=True),), delivery_box=(30, 30, 200))
    y, speed = 0.535, 0.22
    t_arrive = t0 + 1.0
    actors.append(
        Actor(
            actor_id=ids(),
            kind="motorcycle",
            path=[
                Keyframe(t_arrive - (0.62 - -0.08) / speed, -0.08, y),
                Keyframe(t_arrive, 0.6, y),
                Keyframe(t0 + 13, 0.605, y),
                Keyframe(t0 + 15, 0.66, y),
                Keyframe(t0 + 15 + (1.08 - 0.66) / speed, 1.08, y),
            ],
            vehicle=look,
            reach=[(t0 + 5.5, t0 + 8.0, resident_id, 0)],
            label="delivery",
        )
    )
    return {"forbid": ["snatch"], "t_s": [t0, t0 + 20]}


def add_asking_directions(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> dict[str, Any]:
    ped = standing_person(ids(), t0 - 8, t0 + 14, 0.36, 0.47, person_look(rng))
    actors.append(ped)
    look = VehicleLook(body=BIKE_COLORS["silver"], riders=(person_look(rng, helmet=True),))
    actors.append(
        slowed_crossing(
            ids(), t0 - (0.36 + 0.08) / 0.22, 0.535, 0.22, 1, 0.37, 7.0, 0.004, vehicle=look, label="asking_directions"
        )
    )
    return {"forbid": ["snatch"], "t_s": [t0 - 3, t0 + 12]}


# ------------------------------------------------------------------ catalogue
def build(name: str, seed: int = 1, camera_id: str = "cam-gate-01", t_offset: float = 0.0) -> Scenario:
    rng = random.Random(seed)
    ids = _Ids(seed * 10_000)
    actors: list[Actor] = []
    expected: list[dict[str, Any]] = []
    forbid: list[str] = []
    covered: list[tuple[float, float]] = []
    layout = "gate" if "gate" in camera_id else "street"
    night = False
    duration = 120.0

    def bg(d: float, density: float = 1.0) -> None:
        actors.extend(background_traffic(d, rng, ids, density=density))

    if name == "normal_traffic":
        # "normal" includes the hard negatives that happen every day (calibration population)
        duration = 600.0
        bg(duration)
        add_delivery(actors, ids, rng, rng.uniform(60, 250))
        add_asking_directions(actors, ids, rng, rng.uniform(300, 540))
        forbid += ["snatch"]
    elif name == "festival_traffic":
        # F16: a Chand Raat / Eid shopping rush is "normal" too: twice the traffic, bikes slowing
        # in the crowd three times as often, more deliveries and people asking the way
        duration = 600.0
        actors.extend(background_traffic(duration, rng, ids, density=2.2, slow_p=0.15))
        for _ in range(2):
            add_delivery(actors, ids, rng, rng.uniform(40, 560))
            add_asking_directions(actors, ids, rng, rng.uniform(40, 560))
        forbid += ["snatch"]
    elif name == "loiter_basic":
        duration = 210.0
        bg(duration, density=0.6)
        expected.append(add_loitering(actors, ids, rng, 20.0))
    elif name == "snatch_basic":
        duration = 60.0
        layout = "street"
        bg(duration, density=0.5)
        expected.append(add_snatch(actors, ids, rng, 30.0))
    elif name == "snatch_night":
        duration = 60.0
        layout = "street"
        night = True
        bg(duration, density=0.4)
        expected.append(add_snatch(actors, ids, rng, 30.0))
    elif name == "delivery_drop":
        duration = 60.0
        bg(duration, density=0.5)
        info = add_delivery(actors, ids, rng, 20.0)
        forbid += info["forbid"]
    elif name == "asking_directions":
        duration = 60.0
        layout = "street"
        bg(duration, density=0.5)
        info = add_asking_directions(actors, ids, rng, 25.0)
        forbid += info["forbid"]
    elif name == "camera_cover":
        duration = 90.0
        bg(duration)
        covered.append((40.0, 75.0))
        expected.append({"type": "camera_tamper", "t_s": [45.0, 60.0], "check": "covered"})
    elif name == "demo_gate":
        duration = 420.0
        bg(duration, density=0.8)
        expected.append(add_loitering(actors, ids, rng, 25.0))
        add_delivery(actors, ids, rng, 250.0)
        covered.append((330.0, 372.0))
        expected.append({"type": "camera_tamper", "t_s": [335.0, 350.0]})
    elif name == "demo_street":
        from . import safety

        duration = 420.0
        layout = "street"
        bg(duration, density=0.8)
        expected.append(add_snatch(actors, ids, rng, 75.0))
        expected.append(safety.add_foot_snatch(actors, ids, rng, 130.0))
        add_asking_directions(actors, ids, rng, 180.0)
        expected.append(safety.add_following(actors, ids, rng, 215.0))
        expected.append(add_snatch(actors, ids, rng, 300.0))
        expected.append(safety.add_fall(actors, ids, rng, 360.0))
    elif name in SAFETY_SCENES:
        from . import safety

        duration, layout, night = SAFETY_SCENES[name]
        if name == "street_life":
            # the calibration population of the person-safety plugins: ordinary traffic plus
            # every everyday look-alike (and the bike hard negatives of normal_traffic)
            bg(duration)
            add_delivery(actors, ids, rng, rng.uniform(40, 250))
            add_asking_directions(actors, ids, rng, rng.uniform(300, 540))
            safety.street_life(actors, ids, rng, duration)
            forbid += ["snatch"]
        elif name in safety.EVENTS:
            bg(duration, density=0.5)
            info = safety.EVENTS[name](actors, ids, rng, duration / 2)
            expected.append(info)
            expected.extend(info.pop("also", []))
        else:
            bg(duration, density=0.5)
            for _ in range(2 if name in ("greeting", "walking_together") else 1):
                for fn in safety.NEGATIVES[name]:
                    fn(actors, ids, rng, rng.uniform(12.0, duration - 30.0))
    else:
        raise KeyError(f"unknown scenario '{name}' (have: {', '.join(SCENARIOS)})")
    if t_offset:
        for a in actors:
            a.path = [Keyframe(k.t + t_offset, k.x, k.y) for k in a.path]
    return Scenario(name, camera_id, layout, duration, actors, covered, night, expected, forbid)


SAFETY_SCENES: dict[str, tuple[float, str, bool]] = {  # name -> (duration s, layout, night)
    "foot_snatch": (60.0, "street", False),
    "foot_snatch_night": (60.0, "street", True),
    "following_night": (90.0, "street", True),
    "surrounded": (80.0, "street", False),
    "struggle": (60.0, "street", False),
    "abduction": (70.0, "street", False),
    "fall": (70.0, "street", False),
    "bike_theft": (140.0, "gate", False),
    "bike_theft_pushed": (140.0, "gate", False),
    "crowd_panic": (60.0, "street", False),
    "greeting": (80.0, "street", False),
    "walking_together": (110.0, "street", False),
    "friends_circle": (150.0, "street", False),
    "boarding": (80.0, "street", False),
    "resting": (120.0, "street", False),
    "owner_returns": (100.0, "gate", False),
    "bus_rush": (60.0, "street", False),
    "kids_playing": (60.0, "street", False),
    "street_life": (600.0, "street", False),
}

SCENARIOS: tuple[str, ...] = (
    "normal_traffic",
    "festival_traffic",
    "loiter_basic",
    "snatch_basic",
    "snatch_night",
    "delivery_drop",
    "asking_directions",
    "camera_cover",
    "demo_gate",
    "demo_street",
    *SAFETY_SCENES,
)

ScenarioFactory = Callable[[str, int], Scenario]
