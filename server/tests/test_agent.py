from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jikimi_contracts import AlertType, ObjectSummary, Route, TrackSummary

from .conftest import Env

PK = ZoneInfo("Asia/Karachi")


def _bike(env: Env, cam: str, entity: str, at: datetime, color: str, riders: int) -> None:
    t = TrackSummary(
        site_id=env.site_id,
        camera_id=cam,
        entity_id=entity,
        track_ids=[int(at.timestamp()) % 100000],
        object=ObjectSummary(type="motorcycle", color=color, riders=riders),
        zones=["gate-2"] if cam == "cam-gate-01" else ["market-front"],
        ts_start=at.astimezone(UTC),
        ts_end=at.astimezone(UTC) + timedelta(seconds=20),
    )
    assert env.client.post("/v1/edge/tracks", json=t.model_dump(mode="json"), headers=env.edge).status_code == 201


def _ask(env: Env, msg: str, ctx: dict[str, Any] | None, who: str = "sana") -> dict[str, Any]:
    r = env.client.post(
        "/v1/agent", json={"site_id": env.site_id, "message": msg, "context": ctx}, headers=env.login(who)
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_multi_turn_investigation_cites_clips_and_stays_read_only(env: Env) -> None:
    night = (datetime.now(PK) - timedelta(days=1)).replace(hour=22, minute=10, second=0, microsecond=0)
    _bike(env, "cam-gate-01", "cam-gate-01:mot:7", night, "black", 2)
    _bike(env, "cam-gate-01", "cam-gate-01:mot:7", night + timedelta(minutes=6), "black", 2)  # back again
    _bike(env, "cam-street-02", "cam-street-02:mot:3", night + timedelta(minutes=2), "black", 2)  # next camera
    _bike(env, "cam-street-02", "cam-street-02:mot:4", night + timedelta(minutes=3), "red", 1)
    a = env.alert(
        AlertType.LOITERING,
        Route.ALERT_NOW,
        ts_start=night.astimezone(UTC),
        ts_end=night.astimezone(UTC) + timedelta(minutes=7),
    )
    assert env.post_alert(a).status_code == 202

    found = _ask(env, "kal raat kaali bike 2 sawar gate pe", None)
    assert found["intent"] == "find" and found["citations"] and "clip mile" in found["answer_roman"]
    assert all(c["objects"][0].get("color") in ("black", None) for c in found["citations"])
    track_first = {**found["context"], "clip_ids": [c for c in found["context"]["clip_ids"] if c.startswith("track:")]}
    where = _ask(env, "ye bike aur kahan dekhi gayi?", track_first)
    assert where["intent"] == "trajectory" and [t["name"] for t in where["tools"]] == ["get_trajectory"]
    cams = {c["camera_id"] for c in where["citations"]}
    assert cams == {"cam-gate-01", "cam-street-02"} and "milti julti" in where["answer_roman"]
    clip = _ask(env, "pehla clip dikhao", found["context"])
    assert clip["intent"] == "clip" and clip["citations"][0]["clip_id"] == found["context"]["clip_ids"][0]
    report = _ask(env, "is ki report banao", found["context"])
    assert report["intent"] == "report" and report["draft_report"].startswith("DRAFT")
    assert "Evidence page" in report["answer_en"]
    cams_turn = _ask(env, "kaun se cameras hain?", None)
    assert cams_turn["intent"] == "camera_map" and "Gate" in cams_turn["answer_en"]
    nothing = _ask(env, "neeli car parson subah", None)
    assert nothing["citations"] == [] and "Kuch nahi mila" in nothing["answer_roman"]  # no claim without a clip
    actions = [e["action"] for e in env.client.get("/v1/audit", headers=env.login("admin")).json()]
    assert actions.count("agent.turn") == 6


def test_agent_ignores_clips_of_other_sites_in_the_context(env: Env) -> None:
    forged = {"clip_ids": ["track:other-site-cam:1:123"], "last_query": "x"}
    r = _ask(env, "pehla clip dikhao", forged)
    assert r["citations"] == [] and r["intent"] != "clip"
    assert (
        env.client.post(
            "/v1/agent", json={"site_id": env.site_id, "message": "x"}, headers=env.login("akram")
        ).status_code
        == 403
    )
