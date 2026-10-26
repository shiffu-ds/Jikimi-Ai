"""Personal-safety plugins on scripted simulator scenes (ground-truth tracks, no rendering)."""

from __future__ import annotations

import math

import pytest
from jikimi_contracts import AlertCandidate, AlertType, Route, Severity, Track
from jikimi_edge.analytics.base import CameraConfig, FrameContext
from jikimi_edge.analytics.crowd.plugin import CrowdPlugin
from jikimi_edge.analytics.foot_snatch.plugin import FootSnatchPlugin
from jikimi_edge.analytics.people import People
from jikimi_edge.analytics.person_safety.patterns import coverage
from jikimi_edge.analytics.person_safety.plugin import PersonSafetyPlugin
from jikimi_edge.analytics.vehicle_theft.plugin import VehicleTheftPlugin
from jikimi_edge.routing.router import severity_for
from jikimi_edge.sim.scenarios import build
from jikimi_edge.sim.world import World
from jikimi_edge.tracking.riders import RiderMemory, associate_riders
from jikimi_edge.tracking.track_store import TrackStore

T0 = 1_793_000_000.0


def run(plugin, scenario: str, seed: int = 1, camera: str = "cam-street-02") -> list[AlertCandidate]:
    """What the pipeline does around a plugin: riders, track store (velocities), 5 fps."""
    plugin.configure({}, CameraConfig(id=camera))
    sc = build(scenario, seed, camera)
    world, store, memory = World(sc.actors, seed=seed), TrackStore(CameraConfig(id=camera)), RiderMemory()
    out: list[AlertCandidate] = []
    for i in range(int(sc.duration_s * 5)):
        ts = T0 + i / 5
        state = world.state(i / 5, ts)
        riders_of = associate_riders(state.tracks)
        rider_ids = memory.update(
            [t.track_id for t in state.tracks if t.cls == "person"], [p for v in riders_of.values() for p in v], ts
        )
        tracks, events, new = store.update(state.tracks, ts, None, riders_of)
        ctx = FrameContext(
            site_id="s",
            camera_id=camera,
            ts=ts,
            frame=None,
            tracks=tracks,
            poses=state.poses,
            riders_of=riders_of,
            rider_ids=rider_ids,
            histories=store.histories,
            zone_events=events,
            new_track_ids=new,
        )
        out += plugin.on_step(ctx)
        store.pop_finished(ts)
    return out


def patterns(cands: list[AlertCandidate]) -> set[str]:
    return {str(c.features.get("pattern")) for c in cands}


def box(x: float, y: float, h: float, w: float) -> Track:
    return Track(track_id=1, cls="person", conf=0.9, bbox=(x - w / 2, y - h, x + w / 2, y), first_seen=0, last_seen=0)


def test_coverage_tells_the_middle_of_a_ring_from_a_member() -> None:
    assert coverage([0.0, 2.1, 4.2]) == pytest.approx(1 - 2.08 / (2 * math.pi), abs=0.01)  # in the middle
    on_ring = [math.radians(a) for a in (100, 135, 170)]  # the others are all on one side
    assert coverage(on_ring) < 0.5


def test_a_fallen_body_keeps_its_standing_size() -> None:
    people = People()
    for k in range(5):
        people.update([box(0.5, 0.8, 0.2, 0.07)], [], float(k))
    p = people.update([box(0.5, 0.8, 0.05, 0.18)], [], 5.0)[0]
    assert p.posture == "lying" and p.size == pytest.approx(0.2, abs=0.01)


def test_foot_snatch_caught_and_greetings_left_alone() -> None:
    cands = run(FootSnatchPlugin(), "foot_snatch")
    assert cands and all(c.type == AlertType.SNATCH and c.features["on_foot"] for c in cands)
    assert cands[0].features["item"] == "phone" and cands[0].features["calibration_key"] == "snatch_on_foot"
    assert run(FootSnatchPlugin(), "greeting") == []


@pytest.mark.parametrize(
    ("scene", "pattern"),
    [
        ("following_night", "following"),
        ("surrounded", "surrounded"),
        ("struggle", "struggle"),
        ("abduction", "forced_into_vehicle"),
        ("fall", "fall"),
    ],
)
def test_person_in_danger_patterns(scene: str, pattern: str) -> None:
    cands = run(PersonSafetyPlugin(), scene)
    assert pattern in patterns(cands)
    c = next(c for c in cands if c.features["pattern"] == pattern)
    assert c.type == AlertType.PERSON_DANGER and c.features["calibration_key"] == f"person_in_danger_{pattern}"


@pytest.mark.parametrize("scene", ["walking_together", "boarding", "resting"])
def test_everyday_life_is_not_danger(scene: str) -> None:
    assert run(PersonSafetyPlugin(), scene) == []


def test_parked_bike_taken_after_tampering_but_not_by_its_owner() -> None:
    cands = run(VehicleTheftPlugin(), "bike_theft", camera="cam-gate-01")
    assert len(cands) == 1 and cands[0].features["tamper_s"] >= 15
    pushed = run(VehicleTheftPlugin(), "bike_theft_pushed", camera="cam-gate-01")
    assert pushed and pushed[0].features["pushed"]
    assert run(VehicleTheftPlugin(), "owner_returns", camera="cam-gate-01") == []


def test_crowd_scattering_is_panic_running_for_a_ride_is_not() -> None:
    cands = run(CrowdPlugin(), "crowd_panic")
    assert cands and cands[0].features["divergence"] > 0.3
    assert run(CrowdPlugin(), "bus_rush") == []


def test_severity_of_danger_patterns() -> None:
    t = AlertType.PERSON_DANGER
    assert severity_for(t, Route.VERIFY, pattern="forced_into_vehicle") == Severity.HIGH
    assert severity_for(t, Route.VERIFY, pattern="following") == Severity.MEDIUM
    assert severity_for(t, Route.VERIFY, pattern="following", risky=True) == Severity.HIGH  # night, nobody around
    assert severity_for(t, Route.LOG_ONLY, pattern="struggle") == Severity.LOW
