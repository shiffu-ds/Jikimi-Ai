"""Scripted personal-safety scenes: what the person-safety plugins must catch, and the everyday
look-alikes they must leave alone (the hard negatives, most of this file).

Speeds are in body heights per second of the person concerned (``size_at``), so a scene means
the same near and far from the camera: people walk at ~0.5-0.9 body heights per second and run at
2-3. Positions are normalized image coordinates like the rest of the simulator.

Caught: a phone snatched on foot, someone followed and waited for, a person surrounded by a group,
a struggle, someone dragged and pushed into a car, a sudden fall, a parked bike worked on and taken
away (ridden or pushed), a crowd running apart. Left alone: handshakes and hugs, a jogger passing
close, a hurried hand-over, children playing tag, friends and families walking together, strangers
walking the same way, a circle of friends, a vendor's customers, boarding a rickshaw, a parent and
child getting into a car, sitting down to rest, lying down to sleep, bending to pick something up,
an owner unlocking their bike (also with a stuck lock), parking a bike, people running for a ride.
"""

from __future__ import annotations

import math
import random
from typing import Any

from .scenarios import BIKE_COLORS, _Ids, jitter, person_look
from .world import Actor, Keyframe, PersonLook, VehicleLook, scale_at

DEPTH = 2.5
"""Ground distance towards the camera per image distance, in body sizes (pole-mounted view)."""
NEAR_CURB = 0.80  # where cars and rickshaws stop next to the near sidewalk
FAR_CURB = 0.50  # where bikes are parked next to the far sidewalk

Leg = tuple[float, float, float, float]
"""``(x, y, speed in body heights per second, pause after arriving in s)``."""


def size_at(y: float, look: PersonLook) -> float:
    return look.height * scale_at(y)


def route(t0: float, look: PersonLook, start: tuple[float, float], legs: list[Leg]) -> list[Keyframe]:
    """Keyframes from ``start`` through ``legs`` (walking speed per leg, pauses at waypoints)."""
    t, (x, y) = t0, start
    out = [Keyframe(t, x, y)]
    for nx, ny, speed, pause in legs:
        d = math.hypot(nx - x, ny - y)
        if d > 1e-9:
            t += d / max(speed * size_at((y + ny) / 2, look), 1e-6)
            out.append(Keyframe(t, nx, ny))
        if pause > 0:
            t += pause
            out.append(Keyframe(t, nx, ny))
        x, y = nx, ny
    return out


def arriving(t_at: float, look: PersonLook, start: tuple[float, float], at: tuple[float, float], speed: float) -> float:
    """Start time that brings a walker from ``start`` to ``at`` exactly at ``t_at``."""
    return t_at - math.hypot(at[0] - start[0], at[1] - start[1]) / (speed * size_at((start[1] + at[1]) / 2, look))


def ring(cx: float, cy: float, size: float, radius: float, angle_deg: float) -> tuple[float, float]:
    """Image point at ``radius`` body sizes and ``angle`` on the ground around (cx, cy)."""
    a = math.radians(angle_deg)
    return (cx + radius * size * math.cos(a), cy + radius * size * math.sin(a) / DEPTH)


def wobble(t0: float, t1: float, x: float, y: float, amp: float, hz: float, phase: float = 0.0) -> list[Keyframe]:
    """A body pushed and pulled around (x, y): ``amp`` image units at ``hz``."""
    n = max(4, int((t1 - t0) * hz * 4))
    return [
        Keyframe(
            t0 + i * (t1 - t0) / n,
            x + amp * math.sin(2 * math.pi * hz * i * (t1 - t0) / n + phase),
            y + 0.3 * amp * math.sin(2 * math.pi * 0.7 * hz * i * (t1 - t0) / n + phase) / DEPTH,
        )
        for i in range(n + 1)
    ]


def person(ids: _Ids, look: PersonLook, path: list[Keyframe], **kw: Any) -> Actor:
    return Actor(actor_id=ids(), kind="person", path=path, person=look, **kw)


def child_look(rng: random.Random) -> PersonLook:
    return person_look(rng, height=0.095)


def _side(rng: random.Random) -> int:
    return 1 if rng.random() < 0.5 else -1


def _edge(direction: int) -> float:
    """Off-screen x a walker enters from when moving in ``direction``."""
    return -0.08 if direction > 0 else 1.08


# ------------------------------------------------------------------ to be caught
def add_foot_snatch(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A pedestrian walks up to someone on the phone, grabs it and runs."""
    p = {
        "x": rng.uniform(0.35, 0.62),
        "y": rng.uniform(0.89, 0.95),
        "direction": _side(rng),
        "flee_back": rng.random() < 0.4,
        "run": rng.uniform(2.0, 2.8),
        "walk": rng.uniform(0.45, 0.7),
        "chase": rng.random() < 0.4,
        "phone": rng.random() < 0.85,
        **(params or {}),
    }
    d = int(p["direction"])
    vy = p["y"]
    vlook = person_look(rng)
    vs = size_at(vy, vlook)
    flee = -d if p["flee_back"] else d
    vpath = [Keyframe(t0 - 14, p["x"], vy), Keyframe(t0 + 0.8, p["x"], vy)]
    postures = [(t0 - 14, "stand")]
    if p["chase"]:  # the victim runs a few steps after them, then gives up
        vpath.append(Keyframe(t0 + 2.4, p["x"] + flee * 1.5 * vs * 1.6, vy))
        postures += [(t0 + 0.8, "walk"), (t0 + 2.4, "stand")]
    vpath.append(Keyframe(t0 + 12, vpath[-1].x, vy))
    victim = person(
        ids,
        vlook,
        vpath,
        postures=postures,
        phone_until=(t0 + 0.35) if p["phone"] else None,
        jerks=[(t0 + 0.1, t0 + 0.4, 0.22 * vs * flee, 0.0)],
        label="victim",
    )
    actors.append(victim)
    alook = person_look(rng)
    ay = min(0.975, vy + rng.uniform(-0.01, 0.01))
    asz = size_at(ay, alook)
    x_contact = p["x"] - d * 0.33 * asz
    start = (_edge(d), ay)
    t_start = arriving(t0 - 0.6, alook, start, (x_contact, ay), p["walk"])
    x_end = 1.1 if flee > 0 else -0.1
    y_end = min(0.99, ay + (0.025 if flee == d else 0.0))  # running past: in front of the victim
    t_flee = t0 + 0.35
    path = [
        Keyframe(t_start, *start),
        Keyframe(t0 - 0.6, x_contact, ay),
        Keyframe(t_flee, x_contact + d * 0.04 * asz, ay),
        Keyframe(t_flee + abs(x_end - x_contact) / (p["run"] * asz), x_end, y_end),
    ]
    actors.append(person(ids, alook, path, reach=[(t0 - 0.5, t0 + 0.3, victim.actor_id, 0)], label="foot_snatch"))
    return {"type": "snatch", "t_s": [t0 - 1, t0 + 6], "min_route": "VERIFY", "on_foot": True}


def add_following(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Someone keeps a few steps behind a walker, stops when they stop and speeds up with them."""
    p = {
        "y": rng.uniform(0.435, 0.455),
        "direction": _side(rng),
        "gap": rng.uniform(2.2, 3.4),
        "lag": rng.uniform(0.8, 1.5),
        "walk": rng.uniform(0.5, 0.7),
        **(params or {}),
    }
    d, y = int(p["direction"]), p["y"]
    lead = person_look(rng)
    size = size_at(y, lead)
    x0 = _edge(d)
    stop1, stop2 = 0.5 + d * rng.uniform(-0.1, -0.02), 0.5 + d * rng.uniform(0.18, 0.28)
    legs: list[Leg] = [
        (stop1, y, p["walk"], rng.uniform(3.0, 5.0)),
        (stop2, y, p["walk"], rng.uniform(2.5, 4.0)),
        (1.08 if d > 0 else -0.08, y, p["walk"] * 1.5, 0.0),  # hurries away; so does the follower
    ]
    lpath = route(t0, lead, (x0, y), legs)
    actors.append(person(ids, lead, lpath, label="followed"))
    follower = person_look(rng)
    gap = p["gap"] * size
    fpath = [Keyframe(k.t + p["lag"], k.x - d * gap, y + 0.004) for k in lpath]
    fpath.append(Keyframe(fpath[-1].t + gap / (p["walk"] * 1.5 * size), lpath[-1].x, y + 0.004))
    actors.append(person(ids, follower, fpath, label="follower"))
    return {
        "type": "person_in_danger",
        "pattern": "following",
        "t_s": [lpath[1].t, lpath[-1].t + p["lag"] + 6],
        "min_route": "VERIFY",
    }


def add_surrounded(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Three or four people close in on one person from different sides at once."""
    p = {"x": rng.uniform(0.35, 0.65), "y": rng.uniform(0.89, 0.93), "n": rng.choice([3, 3, 4]), **(params or {})}
    vx, vy = p["x"], p["y"]
    vlook = person_look(rng)
    size = size_at(vy, vlook)
    stay = rng.uniform(9.0, 13.0)
    d = _side(rng)
    vpath = route(arriving(t0 - 1, vlook, (_edge(d), vy), (vx, vy), 0.55), vlook, (_edge(d), vy), [(vx, vy, 0.55, 0)])
    vpath += [Keyframe(t0 + stay + 1.5, vx, vy)]
    vpath += route(t0 + stay + 1.5, vlook, (vx, vy), [(1.08 if d > 0 else -0.08, vy, 0.9, 0.0)])[1:]
    actors.append(person(ids, vlook, vpath, label="surrounded"))
    base = rng.uniform(0, 360)
    for k in range(int(p["n"])):
        look = person_look(rng)
        angle = base + k * 360.0 / p["n"] + rng.uniform(-18, 18)
        at = ring(vx, vy, size, rng.uniform(0.6, 0.85), angle)
        at = (at[0], min(0.985, at[1]))
        side = 1 if math.cos(math.radians(angle)) >= 0 else -1  # comes from its own side
        start = (_edge(-side), at[1])
        t_at = t0 + rng.uniform(0.0, 2.5)
        path = [Keyframe(arriving(t_at, look, start, at, 0.8), *start), Keyframe(t_at, *at)]
        path += wobble(t_at, t0 + stay, at[0], at[1], 0.05 * size, 0.4, rng.uniform(0, 6))[1:]
        path += route(t0 + stay, look, at, [(_edge(side), at[1], 0.8, 0.0)])[1:]
        actors.append(person(ids, look, path, label="group"))
    return {
        "type": "person_in_danger",
        "pattern": "surrounded",
        "t_s": [t0 + 2, t0 + stay + 3],
        "min_route": "VERIFY",
    }


def add_struggle(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Two people grapple: pushed and pulled back and forth, in contact, for a few seconds."""
    p = {"x": rng.uniform(0.35, 0.65), "y": rng.uniform(0.89, 0.95), "dur": rng.uniform(4.0, 6.5), **(params or {})}
    x, y, dur = p["x"], p["y"], p["dur"]
    a, b = person_look(rng), person_look(rng)
    size = size_at(y, a)
    d = _side(rng)
    hz, amp = rng.uniform(0.9, 1.4), rng.uniform(0.14, 0.22) * size
    xb, xa = x + d * 0.17 * size, x - d * 0.17 * size
    bpath = route(arriving(t0, b, (_edge(-d), y), (xb, y), 0.6), b, (_edge(-d), y), [(xb, y, 0.6, 0)])
    bpath += wobble(t0, t0 + dur, xb, y, amp, hz, 0.0)[1:]
    bpath += [Keyframe(t0 + dur + 4, xb, y)]
    bpath += route(t0 + dur + 4, b, (xb, y), [(_edge(-d) if rng.random() < 0.5 else _edge(d), y, 0.7, 0)])[1:]
    actors.append(person(ids, b, bpath, postures=[(t0 + dur, "stand"), (t0 + dur + 4, "walk")], label="struggle"))
    apath = route(arriving(t0, a, (_edge(d), y), (xa, y), 0.7), a, (_edge(d), y), [(xa, y, 0.7, 0)])
    apath += wobble(t0, t0 + dur, xa, y, amp, hz, math.pi * 0.8)[1:]
    apath += route(t0 + dur, a, (xa, y), [(_edge(d), y, rng.uniform(1.0, 2.2), 0)])[1:]
    actors.append(person(ids, a, apath, reach=[(t0, t0 + dur, actors[-1].actor_id, 0)], label="struggle"))
    return {
        "type": "person_in_danger",
        "pattern": "struggle",
        "t_s": [t0 + 1.5, t0 + dur + 3],
        "min_route": "VERIFY",
    }


def add_abduction(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A car waits; someone from it grabs a pedestrian, a struggle, the pedestrian is dragged,
    both disappear into the car and it drives off fast."""
    p = {"x": rng.uniform(0.35, 0.6), "helpers": rng.choice([0, 1]), **(params or {})}
    xc = p["x"]
    d = _side(rng)
    car = Actor(
        actor_id=ids(),
        kind="car",
        path=[
            Keyframe(t0 - 6 - (xc - _edge(d)) * d / 0.2, _edge(d), NEAR_CURB),
            Keyframe(t0 - 6, xc, NEAR_CURB),
            Keyframe(t0 + 7.0, xc, NEAR_CURB),
            Keyframe(t0 + 7.0 + abs(_edge(-d) - xc) / 0.36, _edge(-d), NEAR_CURB),
        ],
        vehicle=VehicleLook(body=rng.choice([(40, 40, 40), (200, 200, 200), (30, 30, 150)])),
        label="abduction_car",
    )
    actors.append(car)
    vy = rng.uniform(0.9, 0.94)
    vlook = person_look(rng)
    size = size_at(vy, vlook)
    xv = xc + d * rng.uniform(0.12, 0.2)  # a few metres from the door: hauled there, slowly
    door = (xc + d * 0.02, NEAR_CURB + 0.02)
    hz, amp = rng.uniform(0.9, 1.3), 0.15 * size
    vpath = route(arriving(t0, vlook, (_edge(-d), vy), (xv, vy), 0.55), vlook, (_edge(-d), vy), [(xv, vy, 0.55, 0)])
    vpath += wobble(t0, t0 + 3.0, xv, vy, amp, hz)[1:]
    vpath += route(t0 + 3.0, vlook, (xv, vy), [(door[0], door[1], rng.uniform(0.3, 0.45), 0)])[1:]
    victim = person(ids, vlook, vpath, postures=[(t0 + 3.0, "crouch")], label="abducted")
    actors.append(victim)
    t_in = vpath[-1].t
    for k in range(1 + int(p["helpers"])):
        look = person_look(rng)
        off = (0.3 + 0.25 * k) * size * d
        out = (door[0] + 0.04 * k, door[1] + 0.01)
        grab = (xv + off, vy - 0.01 * k)
        path = [Keyframe(t0 - 5.0 + k, *out)]
        path += route(t0 - 5.0 + k, look, out, [(grab[0], grab[1], 0.6, 0)])[1:]
        path[-1] = Keyframe(t0, *grab)
        path += wobble(t0, t0 + 3.0, grab[0], grab[1], amp, hz, math.pi)[1:]
        path += [Keyframe(t_in, door[0] + off * 0.3, door[1])]
        actors.append(person(ids, look, path, reach=[(t0, t_in, victim.actor_id, 0)], label="abductor"))
    return {
        "type": "person_in_danger",
        "pattern": "forced_into_vehicle",
        "t_s": [t_in - 1, t0 + 16],
        "min_route": "VERIFY",
        "also": [{"type": "person_in_danger", "pattern": "struggle", "t_s": [t0 + 1, t0 + 7], "min_route": "VERIFY"}],
    }


def add_fall(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A walker suddenly falls and stays down; after a while a passer-by comes to help."""
    p = {"x": rng.uniform(0.3, 0.7), "y": rng.uniform(0.89, 0.95), "down": rng.uniform(12, 20), **(params or {})}
    x, y = p["x"], p["y"]
    look = person_look(rng)
    d = _side(rng)
    path = route(arriving(t0, look, (_edge(d), y), (x, y), 0.6), look, (_edge(d), y), [(x, y, 0.6, 0)])
    path += [Keyframe(t0 + p["down"], x, y)]
    actors.append(person(ids, look, path, postures=[(t0, "lying"), (t0 + p["down"] - 2, "sit")], label="fallen"))
    helper = person_look(rng)
    hs = size_at(y, helper)
    at = (x - d * 0.5 * hs, min(0.985, y + 0.01))
    hpath = route(arriving(t0 + 8, helper, (_edge(-d), at[1]), at, 0.9), helper, (_edge(-d), at[1]), [(*at, 0.9, 0)])
    hpath += [Keyframe(t0 + p["down"] + 4, *at)]
    actors.append(person(ids, helper, hpath, postures=[(t0 + 8, "crouch")], label="helper"))
    return {"type": "person_in_danger", "pattern": "fall", "t_s": [t0 + 3, t0 + 14], "min_route": "VERIFY"}


def parked_bike(
    ids: _Ids,
    rng: random.Random,
    x: float,
    t_from: float,
    t_to: float,
    rider: PersonLook | None = None,
    away: list[Keyframe] | None = None,
) -> Actor:
    """A bike standing at the far curb from ``t_from``; ridden away along ``away`` by ``rider``."""
    color = rng.choice(list(BIKE_COLORS))
    path = [Keyframe(t_from, x, FAR_CURB), Keyframe(t_to, x, FAR_CURB)] + (away or [])
    return Actor(
        actor_id=ids(),
        kind="motorcycle",
        path=path,
        vehicle=VehicleLook(body=jitter(BIKE_COLORS[color], rng, 15), riders=(rider,) if rider else (), color=color),
        riders_from=t_to if rider else None,
        label="parked",
    )


def add_bike_theft(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Someone crouches at a parked bike for half a minute while another bike waits nearby, then
    rides it away (or pushes it, when the lock would not open)."""
    p = {
        "x": rng.uniform(0.2, 0.42),
        "tamper": rng.uniform(18.0, 32.0),
        "accomplice": rng.random() < 0.7,
        "pushed": rng.random() < 0.3,
        **(params or {}),
    }
    x, tamper = p["x"], p["tamper"]
    thief = person_look(rng)
    side = (x + 0.055, FAR_CURB)
    start = (1.08, 0.455)
    t_go = t0 + tamper + 1.5
    tpath = route(arriving(t0, thief, start, side, 0.6), thief, start, [(side[0], side[1], 0.6, 0)])
    if p["pushed"]:  # walks the bike away beside it
        speed = 0.55 * size_at(FAR_CURB, thief)
        away = [Keyframe(t_go + 0.5, x, FAR_CURB), Keyframe(t_go + 0.5 + (1.08 - x) / speed, 1.08, FAR_CURB)]
        bike = parked_bike(ids, rng, x, 0.0, t_go + 0.5, None, away)
        tpath += [Keyframe(t_go + 0.5, *side), Keyframe(away[-1].t, 1.08 + 0.055, FAR_CURB)]
        postures = [(t0, "crouch"), (t0 + tamper, "stand"), (t_go + 0.5, "walk")]
    else:  # gets on and rides off
        away = [Keyframe(t_go + 1.0, x, FAR_CURB), Keyframe(t_go + 1.0 + (1.08 - x) / 0.3, 1.08, FAR_CURB)]
        bike = parked_bike(ids, rng, x, 0.0, t_go, thief, away)
        tpath += [Keyframe(t_go, x + 0.01, FAR_CURB)]
        postures = [(t0, "crouch"), (t0 + tamper, "stand")]
    actors.append(bike)
    actors.append(person(ids, thief, tpath, postures=postures, label="bike_theft"))
    if p["accomplice"]:  # waits on a running bike a few metres away, leaves with them
        xa = min(0.9, x + rng.uniform(0.22, 0.32))
        look = VehicleLook(body=jitter(BIKE_COLORS[rng.choice(["black", "red"])], rng, 15), riders=(person_look(rng),))
        t_arr = t0 + rng.uniform(2.0, 6.0)
        actors.append(
            Actor(
                actor_id=ids(),
                kind="motorcycle",
                path=[
                    Keyframe(t_arr - (xa + 0.08) / 0.25, -0.08, FAR_CURB + 0.03),
                    Keyframe(t_arr, xa, FAR_CURB + 0.03),
                    Keyframe(t_go + 1.5, xa, FAR_CURB + 0.03),
                    Keyframe(t_go + 1.5 + (1.08 - xa) / 0.33, 1.08, FAR_CURB + 0.03),
                ],
                vehicle=look,
                label="accomplice",
            )
        )
    return {"type": "vehicle_theft", "t_s": [t_go - 1, t_go + 12], "min_route": "VERIFY"}


def add_crowd_panic(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A dozen people around a market spot suddenly run away from it in every direction."""
    p = {"x": rng.uniform(0.4, 0.6), "n": rng.randint(10, 14), **(params or {})}
    xc = p["x"]
    for _ in range(int(p["n"])):
        near = rng.random() < 0.65
        y = rng.uniform(0.88, 0.97) if near else rng.uniform(0.42, 0.465)
        x = min(0.95, max(0.05, xc + rng.uniform(-0.38, 0.38)))
        look = person_look(rng)
        drift = rng.uniform(-0.04, 0.04)
        out = 1 if x > xc else -1
        if abs(x - xc) < 0.03:
            out = _side(rng)
        start = (x - drift, y)
        t_run = t0 + 0.1 + 1.6 * abs(x - xc) + rng.uniform(0, 0.4)
        path = [Keyframe(t0 - 20, *start), Keyframe(t_run, x, y)]
        path += route(t_run, look, (x, y), [(1.1 if out > 0 else -0.1, y, rng.uniform(1.8, 2.6), 0)])[1:]
        actors.append(person(ids, look, path, postures=[(t0 - 20, "walk")], label="crowd"))
    return {"type": "crowd_panic", "t_s": [t0, t0 + 6], "min_route": "VERIFY"}


# ------------------------------------------------------------------ everyday look-alikes
def add_greeting(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """Two people meet, shake hands or hug for a few seconds, walk on (apart or together)."""
    y, xm = rng.uniform(0.89, 0.95), rng.uniform(0.3, 0.7)
    a, b = person_look(rng), person_look(rng)
    sa = size_at(y, a)
    meet = rng.uniform(2.0, 4.5)
    xa, xb = xm - 0.17 * sa, xm + 0.17 * sa
    va, vb = rng.uniform(0.4, 0.7), rng.uniform(0.4, 0.7)
    apath = route(arriving(t0, a, (-0.08, y), (xa, y), va), a, (-0.08, y), [(xa, y, va, meet)])
    bpath = route(arriving(t0, b, (1.08, y), (xb, y), vb), b, (1.08, y), [(xb, y, vb, meet)])
    if rng.random() < 0.5:  # walk on together
        apath += route(t0 + meet, a, (xa, y), [(1.08, y, 0.55, 0)])[1:]
        bpath += route(t0 + meet, b, (xb, y), [(1.08 + 0.34 * sa, y, 0.55, 0)])[1:]
    else:
        apath += route(t0 + meet, a, (xa, y), [(1.08, min(0.985, y + 0.02), va, 0)])[1:]
        bpath += route(t0 + meet, b, (xb, y), [(-0.08, y, vb, 0)])[1:]
    actors.append(person(ids, a, apath, label="greeting"))
    actors.append(person(ids, b, bpath, label="greeting"))
    actors[-2].reach = [(t0 + 0.2, t0 + min(meet, 1.8), actors[-1].actor_id, 0)]
    actors[-1].reach = [(t0 + 0.2, t0 + min(meet, 1.8), actors[-2].actor_id, 0)]


def add_jogger(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """A jogger, already running, passes close by someone standing (often on the phone)."""
    y, x = rng.uniform(0.89, 0.95), rng.uniform(0.3, 0.7)
    s = person_look(rng)
    actors.append(
        person(
            ids,
            s,
            [Keyframe(t0 - 10, x, y), Keyframe(t0 + 10, x, y)],
            postures=[(t0 - 10, "stand")],
            phone_until=t0 + 10 if rng.random() < 0.5 else None,
            label="standing",
        )
    )
    j = person_look(rng)
    d = _side(rng)
    jy = min(0.985, y + rng.uniform(0.004, 0.014))
    speed = rng.uniform(1.6, 2.3)
    start = (_edge(d), jy)
    t_start = arriving(t0, j, start, (x, jy), speed)
    actors.append(person(ids, j, route(t_start, j, start, [(_edge(-d), jy, speed, 0)]), label="jogger"))


def add_handover(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """Someone hands a thing to a person standing there and walks off briskly."""
    y, x = rng.uniform(0.89, 0.95), rng.uniform(0.3, 0.7)
    b = person_look(rng)
    actors.append(person(ids, b, [Keyframe(t0 - 8, x, y), Keyframe(t0 + 10, x, y)], postures=[(t0 - 8, "stand")]))
    a = person_look(rng)
    sa = size_at(y, a)
    d = _side(rng)
    at = (x - d * 0.33 * sa, y)
    path = route(arriving(t0, a, (_edge(d), y), at, 0.6), a, (_edge(d), y), [(at[0], at[1], 0.6, 1.6)])
    path += route(path[-1].t, a, at, [(_edge(d) if rng.random() < 0.5 else _edge(-d), y, rng.uniform(0.9, 1.15), 0)])[
        1:
    ]
    actors.append(person(ids, a, path, reach=[(t0 + 0.1, t0 + 1.5, actors[-1].actor_id, 0)], label="handover"))


def add_kids_tag(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, dur: float = 15.0) -> None:
    """Children chase each other around a spot on the pavement, sometimes touching."""
    xc, yc = rng.uniform(0.3, 0.7), rng.uniform(0.9, 0.95)
    for _ in range(rng.choice([2, 3])):
        look = child_look(rng)
        pts: list[Leg] = []
        t, x, y = 0.0, xc + rng.uniform(-0.1, 0.1), yc
        while t < dur:
            nx, ny = xc + rng.uniform(-0.14, 0.14), min(0.985, yc + rng.uniform(-0.03, 0.03))
            speed = rng.uniform(1.3, 2.2)
            t += math.hypot(nx - x, ny - y) / (speed * size_at(ny, look)) + 0.3
            pts.append((nx, ny, speed, rng.choice([0.0, 0.0, 0.5])))
            x, y = nx, ny
        d = _side(rng)
        pts.append((_edge(-d), y, 0.6, 0))
        start = (_edge(d), yc)
        path = route(t0 - 6, look, start, [(xc, yc, 0.6, 0.0), *pts])
        actors.append(person(ids, look, path, label="kids"))


def add_walking_together(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """Two friends side by side, stopping together at a shop."""
    y = rng.choice([rng.uniform(0.435, 0.455), rng.uniform(0.89, 0.94)])
    a = person_look(rng)
    size = size_at(y, a)
    d = _side(rng)
    speed = rng.uniform(0.45, 0.65)
    stop = 0.5 + rng.uniform(-0.2, 0.2)
    legs: list[Leg] = [(stop, y, speed, rng.uniform(3, 7)), (_edge(-d), y, speed, 0)]
    apath = route(t0, a, (_edge(d), y), legs)
    actors.append(person(ids, a, apath, label="together"))
    off, dy = d * rng.uniform(-0.3, 0.3) * size, rng.uniform(0.006, 0.014)
    actors.append(person(ids, person_look(rng), [Keyframe(k.t, k.x + off, k.y + dy) for k in apath], label="together"))


def add_family_line(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """One family member walks a little behind the other; at stops they come up beside them."""
    y = rng.uniform(0.435, 0.455)
    lead = person_look(rng)
    size = size_at(y, lead)
    d = _side(rng)
    speed = rng.uniform(0.45, 0.6)
    s1, s2 = 0.5 + d * rng.uniform(-0.12, 0.0), 0.5 + d * rng.uniform(0.15, 0.25)
    p1, p2 = rng.uniform(3.0, 5.0), rng.uniform(3.0, 5.0)
    lpath = route(t0, lead, (_edge(d), y), [(s1, y, speed, p1), (s2, y, speed, p2), (_edge(-d), y, speed, 0)])
    actors.append(person(ids, lead, lpath, label="family"))
    gap, lag = rng.uniform(1.2, 1.8) * size, 0.8
    side = d * 0.3 * size
    fpath = [Keyframe(lpath[0].t + lag, lpath[0].x - d * gap, y + 0.005)]
    for i in range(1, len(lpath)):
        k = lpath[i]
        if i in (1, 3):  # the leader stopped: walk up beside them
            fpath.append(Keyframe(k.t + lag, k.x - d * gap, y + 0.005))
            fpath.append(Keyframe(k.t + lag + 1.6, k.x - side, y + 0.008))
        elif i in (2, 4):  # moving on again
            fpath.append(Keyframe(k.t + 0.2, k.x - side, y + 0.008))
        else:
            fpath.append(Keyframe(k.t + lag, k.x - d * gap, y + 0.005))
    actors.append(person(ids, person_look(rng), fpath, label="family"))


def add_same_way(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """Two strangers walk the same way at different speeds; the faster one overtakes."""
    y = rng.uniform(0.435, 0.455)
    d = _side(rng)
    a, b = person_look(rng), person_look(rng)
    actors.append(person(ids, a, route(t0, a, (_edge(d), y), [(_edge(-d), y, rng.uniform(0.35, 0.45), 0)])))
    by = y + rng.uniform(0.004, 0.01)
    actors.append(person(ids, b, route(t0 + 3, b, (_edge(d), by), [(_edge(-d), by, rng.uniform(0.75, 0.9), 0)])))


def add_friends_circle(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """Friends arrive one by one, stand in a circle talking for a minute, leave together."""
    xc, yc = rng.uniform(0.3, 0.7), rng.uniform(0.9, 0.94)
    n = rng.choice([3, 4, 4, 5])
    end = t0 + rng.uniform(60, 90)
    base = rng.uniform(0, 360)
    for k in range(n):
        look = person_look(rng)
        size = size_at(yc, look)
        at = ring(xc, yc, size, rng.uniform(0.5, 0.7), base + k * 360.0 / n + rng.uniform(-10, 10))
        at = (at[0], min(0.985, at[1]))
        side = _side(rng)
        t_at = t0 + k * rng.uniform(6.0, 14.0)
        path = route(arriving(t_at, look, (_edge(side), at[1]), at, 0.55), look, (_edge(side), at[1]), [(*at, 0.55, 0)])
        path += wobble(t_at, end, at[0], at[1], 0.03 * size, 0.3, rng.uniform(0, 6))[1:]
        path += route(end, look, at, [(_edge(1), at[1], 0.55, 0)])[1:]
        actors.append(person(ids, look, path, label="friends"))


def add_vendor(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, dur: float = 120.0) -> None:
    """A vendor stands at a stall; customers come and go, sometimes three at once."""
    xv, yv = rng.uniform(0.25, 0.75), rng.uniform(0.89, 0.93)
    vendor = person_look(rng)
    actors.append(
        person(
            ids, vendor, [Keyframe(t0, xv, yv), Keyframe(t0 + dur, xv, yv)], postures=[(t0, "stand")], label="vendor"
        )
    )
    t = t0 + rng.uniform(2, 8)
    front = rng.uniform(0, 360)  # the cart blocks one side; a family or friends stand together
    while t < t0 + dur - 15:
        group = rng.uniform(front - 120, front + 120)
        for _ in range(rng.choice([1, 1, 2, 3])):
            look = person_look(rng)
            at = ring(xv, yv, size_at(yv, look), rng.uniform(0.55, 0.85), group + rng.uniform(-35, 35))
            at = (at[0], min(0.985, at[1]))
            side = _side(rng)
            arrive = t + rng.uniform(0, 4)
            stay = rng.uniform(10, 35)
            path = route(
                arriving(arrive, look, (_edge(side), at[1]), at, 0.55), look, (_edge(side), at[1]), [(*at, 0.55, stay)]
            )
            path += route(path[-1].t, look, at, [(_edge(-side), at[1], 0.55, 0)])[1:]
            actors.append(person(ids, look, path, label="customer"))
        t += rng.uniform(12, 30)


def add_hug(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """Two people meet and hug, standing still in contact, then walk together."""
    y, xm = rng.uniform(0.89, 0.95), rng.uniform(0.3, 0.7)
    a, b = person_look(rng), person_look(rng)
    sa = size_at(y, a)
    hold = rng.uniform(2.5, 4.5)
    xa, xb = xm - 0.12 * sa, xm + 0.12 * sa
    apath = route(arriving(t0, a, (-0.08, y), (xa, y), 0.6), a, (-0.08, y), [(xa, y, 0.6, hold), (1.08, y, 0.5, 0)])
    bpath = route(arriving(t0, b, (1.08, y), (xb, y), 0.6), b, (1.08, y), [(xb, y, 0.6, hold), (1.12, y, 0.5, 0)])
    actors.append(person(ids, a, apath, label="hug"))
    actors.append(person(ids, b, bpath, label="hug"))
    actors[-2].reach = [(t0, t0 + hold, actors[-1].actor_id, 0)]
    actors[-1].reach = [(t0, t0 + hold, actors[-2].actor_id, 0)]


def _stopping_vehicle(
    ids: _Ids, rng: random.Random, kind: str, x: float, t_stop: float, t_go: float, speed: float
) -> Actor:
    d = _side(rng)
    body = rng.choice([(200, 200, 200), (40, 40, 40), (150, 40, 30), (30, 30, 150), (60, 170, 60)])
    return Actor(
        actor_id=ids(),
        kind=kind,
        path=[
            Keyframe(t_stop - abs(x - _edge(d)) / 0.2, _edge(d), NEAR_CURB),
            Keyframe(t_stop, x, NEAR_CURB),
            Keyframe(t_go, x, NEAR_CURB),
            Keyframe(t_go + abs(_edge(-d) - x) / speed, _edge(-d), NEAR_CURB),
        ],
        vehicle=VehicleLook(body=body),
        label=f"stopping_{kind}",
    )


def add_normal_boarding(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """A rickshaw stops; one or two waiting people get in on their own; it drives off."""
    x = rng.uniform(0.3, 0.7)
    actors.append(_stopping_vehicle(ids, rng, rng.choice(["rickshaw", "car"]), x, t0 - 2, t0 + 5, 0.2))
    for k in range(rng.choice([1, 1, 2])):
        look = person_look(rng)
        y = rng.uniform(0.88, 0.93)
        sx = x + rng.uniform(-0.15, 0.15)
        door = (x + rng.uniform(-0.03, 0.03), NEAR_CURB + 0.02)
        path = [Keyframe(t0 - 15, sx, y), Keyframe(t0 + 0.5 * k, sx, y)]
        path += route(t0 + 0.5 * k, look, (sx, y), [(door[0], door[1], 0.6, 0)])[1:]
        actors.append(person(ids, look, path, postures=[(t0 - 15, "stand"), (t0 + 0.5 * k, "walk")], label="boarding"))


def add_family_boarding(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """A car stops; a parent and a child walk to it hand in hand and get in."""
    x = rng.uniform(0.3, 0.7)
    d = _side(rng)
    actors.append(_stopping_vehicle(ids, rng, "car", x, t0 - 3, t0 + 7, 0.2))
    y = rng.uniform(0.9, 0.94)
    parent, child = person_look(rng), child_look(rng)
    ps = size_at(y, parent)
    door = (x, NEAR_CURB + 0.02)
    ppath = route(t0 - 8, parent, (_edge(d), y), [(x + d * 0.1, y, 0.5, 0), (door[0], door[1], 0.5, 0)])
    shift = t0 + 2 - ppath[-1].t
    ppath = [Keyframe(k.t + shift, k.x, k.y) for k in ppath]
    cpath = [Keyframe(k.t, k.x - d * 0.22 * ps, min(0.985, k.y + 0.006)) for k in ppath]
    actors.append(person(ids, parent, ppath, label="family_boarding"))
    actors.append(person(ids, child, cpath, label="family_boarding"))
    actors[-2].reach = [(ppath[0].t, ppath[-1].t, actors[-1].actor_id, 0)]


def add_sit_rest(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """Someone sits down on the kerb, rests, gets up and walks on."""
    y, x = rng.uniform(0.89, 0.95), rng.uniform(0.2, 0.8)
    look = person_look(rng)
    d = _side(rng)
    rest = rng.uniform(15, 40)
    path = route(
        arriving(t0, look, (_edge(d), y), (x, y), 0.5), look, (_edge(d), y), [(x, y, 0.5, rest), (_edge(-d), y, 0.5, 0)]
    )
    actors.append(person(ids, look, path, postures=[(t0, "sit"), (t0 + rest, "walk")], label="sit_rest"))


def add_lie_down(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, dur: float = 80.0) -> None:
    """Someone sits down, then slowly lies down to sleep on the pavement."""
    y, x = rng.uniform(0.89, 0.95), rng.uniform(0.2, 0.8)
    look = person_look(rng)
    d = _side(rng)
    path = route(arriving(t0, look, (_edge(d), y), (x, y), 0.45), look, (_edge(d), y), [(x, y, 0.45, dur)])
    actors.append(person(ids, look, path, postures=[(t0, "sit"), (t0 + rng.uniform(5, 9), "lying")], label="sleeping"))


def add_bend_pick(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """Someone bends down for a moment to pick something up, then walks on."""
    y, x = rng.uniform(0.89, 0.95), rng.uniform(0.2, 0.8)
    look = person_look(rng)
    d = _side(rng)
    bend = rng.uniform(1.5, 3.0)
    path = route(
        arriving(t0, look, (_edge(d), y), (x, y), 0.6), look, (_edge(d), y), [(x, y, 0.6, bend), (_edge(-d), y, 0.6, 0)]
    )
    actors.append(person(ids, look, path, postures=[(t0, "crouch"), (t0 + bend, "walk")], label="bend"))


def add_owner_return(
    actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, x: float | None = None, lock_s: float | None = None
) -> None:
    """The owner of a parked bike comes back, opens the disc lock (a few seconds, crouching) and
    rides off. ``lock_s`` up to ~15 s: a stuck lock (the honest worst case for the detector)."""
    x = rng.uniform(0.15, 0.85) if x is None else x
    lock = rng.uniform(2.0, 6.0) if lock_s is None else lock_s
    owner = person_look(rng)
    side = (x + 0.05, FAR_CURB)
    start = (rng.choice([-0.08, 1.08]), 0.445)
    path = route(arriving(t0, owner, start, side, 0.6), owner, start, [(side[0], side[1], 0.6, 0)])
    t_go = t0 + lock + 1.2
    path += [Keyframe(t_go, x + 0.01, FAR_CURB)]
    d = _side(rng)
    away = [Keyframe(t_go + 1.0, x, FAR_CURB), Keyframe(t_go + 1.0 + abs(_edge(-d) - x) / 0.24, _edge(-d), FAR_CURB)]
    actors.append(parked_bike(ids, rng, x, 0.0, t_go, owner, away))
    actors.append(person(ids, owner, path, postures=[(t0, "crouch"), (t0 + lock, "stand")], label="owner"))


def add_parking(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float, until: float) -> None:
    """A rider parks at the kerb, gets off and walks away; the bike stays until ``until``."""
    x = rng.uniform(0.15, 0.85)
    rider = person_look(rng, helmet=rng.random() < 0.4)
    d = _side(rng)
    color = rng.choice(list(BIKE_COLORS))
    actors.append(
        Actor(
            actor_id=ids(),
            kind="motorcycle",
            path=[
                Keyframe(t0 - abs(x - _edge(d)) / 0.22, _edge(d), FAR_CURB),
                Keyframe(t0, x, FAR_CURB),
                Keyframe(until, x, FAR_CURB),
            ],
            vehicle=VehicleLook(body=jitter(BIKE_COLORS[color], rng, 15), riders=(rider,), color=color),
            riders_until=t0 + 1.0,
            label="parking",
        )
    )
    start = (x + 0.05, FAR_CURB)
    actors.append(
        person(ids, rider, route(t0 + 1.0, rider, start, [(x + 0.06, 0.445, 0.5, 0), (_edge(-d), 0.445, 0.55, 0)]))
    )


def add_bus_rush(actors: list[Actor], ids: _Ids, rng: random.Random, t0: float) -> None:
    """A rickshaw stops and waiting people run to it from along the pavement and get in."""
    x = rng.uniform(0.3, 0.7)
    actors.append(_stopping_vehicle(ids, rng, "rickshaw", x, t0, t0 + 7, 0.2))
    for _ in range(rng.randint(4, 6)):
        look = person_look(rng)
        y = rng.uniform(0.88, 0.96)
        sx = min(0.97, max(0.03, x + rng.uniform(-0.4, 0.4)))
        door = (x + rng.uniform(-0.03, 0.03), NEAR_CURB + 0.02)
        t_run = t0 + rng.uniform(0.0, 1.5)
        path = [Keyframe(t0 - 20, sx, y), Keyframe(t_run, sx, y)]
        path += route(t_run, look, (sx, y), [(door[0], door[1], rng.uniform(1.5, 2.1), 0)])[1:]
        actors.append(person(ids, look, path, postures=[(t0 - 20, "stand"), (t_run, "walk")], label="rush"))


EVERYDAY = (
    ("greeting", add_greeting, 2),
    ("jogger", add_jogger, 1),
    ("handover", add_handover, 1),
    ("kids_tag", add_kids_tag, 1),
    ("walking_together", add_walking_together, 2),
    ("family_line", add_family_line, 1),
    ("same_way", add_same_way, 1),
    ("friends_circle", add_friends_circle, 1),
    ("vendor", add_vendor, 1),
    ("hug", add_hug, 1),
    ("normal_boarding", add_normal_boarding, 1),
    ("family_boarding", add_family_boarding, 1),
    ("sit_rest", add_sit_rest, 1),
    ("lie_down", add_lie_down, 1),
    ("bend_pick", add_bend_pick, 1),
    ("bus_rush", add_bus_rush, 1),
)


def street_life(actors: list[Actor], ids: _Ids, rng: random.Random, duration: float) -> None:
    """Ten minutes of ordinary pavement life: every everyday look-alike at least once, plus
    parked bikes whose owners come back (one in two with a stuck lock)."""
    for _name, fn, n in EVERYDAY:
        for _ in range(n):
            fn(actors, ids, rng, rng.uniform(20.0, duration - 40.0))
    spots = rng.sample([0.12, 0.22, 0.32, 0.62, 0.72, 0.82], 4)
    for x in spots[:2]:  # parked all along
        actors.append(parked_bike(ids, rng, x, 0.0, duration + 1))
    add_owner_return(actors, ids, rng, rng.uniform(30, duration - 60), x=spots[2])
    stuck = rng.uniform(9.0, 16.0) if rng.random() < 0.5 else None
    add_owner_return(actors, ids, rng, rng.uniform(30, duration - 60), x=spots[3], lock_s=stuck)
    add_parking(actors, ids, rng, rng.uniform(30, duration - 100), duration + 1)


EVENTS = {  # scenario -> the event it shows (at half time)
    "foot_snatch": add_foot_snatch,
    "foot_snatch_night": add_foot_snatch,
    "following_night": add_following,
    "surrounded": add_surrounded,
    "struggle": add_struggle,
    "abduction": add_abduction,
    "fall": add_fall,
    "bike_theft": lambda a, i, r, t: add_bike_theft(a, i, r, t, {"pushed": False}),
    "bike_theft_pushed": lambda a, i, r, t: add_bike_theft(a, i, r, t, {"pushed": True}),
    "crowd_panic": add_crowd_panic,
}
NEGATIVES = {  # scenario -> the look-alikes it shows
    "greeting": (add_greeting, add_jogger, add_handover),
    "walking_together": (add_walking_together, add_family_line, add_same_way),
    "friends_circle": (add_friends_circle, add_vendor),
    "boarding": (add_normal_boarding, add_family_boarding, add_hug),
    "resting": (add_sit_rest, add_lie_down, add_bend_pick),
    "owner_returns": (add_owner_return, lambda a, i, r, t: add_parking(a, i, r, t, t + 60)),
    "bus_rush": (add_bus_rush,),
    "kids_playing": (add_kids_tag,),
}
