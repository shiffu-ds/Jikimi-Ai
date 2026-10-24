from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from jikimi_contracts import ObjectSummary, TrackSummary
from jikimi_contracts.rules_dsl import RuleBundle
from jikimi_crypto import verify_json
from jikimi_server.rules.parser import parse_rule
from jikimi_server.search.parser import SiteVocab

from .conftest import Env

REPO = Path(__file__).resolve().parents[2]
PK = ZoneInfo("Asia/Karachi")
PLAN_EXAMPLE = "raat 11 ke baad gate 2 par koi 5 min se zyada ruke to batao"


@pytest.fixture(scope="module")
def vocab() -> SiteVocab:
    cfg = yaml.safe_load((REPO / "edge/config/site.demo.yaml").read_text(encoding="utf-8"))
    return SiteVocab.build(cfg["cameras"])


def _when(text: str, vocab: SiteVocab) -> dict[str, Any]:
    d = parse_rule(text, "society-gate-north", vocab, "sana")
    assert d.valid and d.rule is not None, (d.questions, d.errors)
    return d.rule.when.model_dump(mode="json", by_alias=True, exclude_none=True)


@pytest.mark.parametrize(
    ("text", "window", "zone", "obj", "cond"),
    [
        (PLAN_EXAMPLE, ("23:00", "05:00"), "gate-2", {"type": "person"}, {"dwell_seconds_gt": 300}),
        ("رات 11 بجے کے بعد گیٹ 2 پر کوئی 5 منٹ سے زیادہ رکے", ("23:00", "05:00"), "gate-2", {"type": "person"}, {"dwell_seconds_gt": 300}),
        ("bazaar mein 3 se zyada bikes khari hon", None, "market-front", {"type": "motorcycle"}, {"count_gt": 3}),
        ("gate 2 par raat ko kaali bike 2 minute se zyada ruke", ("18:00", "06:00"), "gate-2", {"type": "motorcycle", "color": "black"}, {"dwell_seconds_gt": 120}),
        ("subah 9 se shaam 5 tak bazaar mein 10 se zyada log", ("09:00", "17:00"), "market-front", {"type": "person"}, {"count_gt": 10}),
        ("subah 9 se 5 tak bazaar mein 10 se zyada log", ("09:00", "17:00"), "market-front", {"type": "person"}, {"count_gt": 10}),
        ("raat 11 se 5 tak gate number 2 par 4 ya zyada log 3 min tak khare rahein", ("23:00", "05:00"), "gate-2", {"type": "person"}, {"dwell_seconds_gt": 180, "count_gt": 3}),
        ("gate par aadha ghanta koi ruke", None, "gate-2", {"type": "person"}, {"dwell_seconds_gt": 1800}),
    ],
)  # fmt: skip
def test_parser_understands_roman_and_urdu(
    vocab: SiteVocab,
    text: str,
    window: tuple[str, str] | None,
    zone: str,
    obj: dict[str, str],
    cond: dict[str, int],
) -> None:
    w = _when(text, vocab)
    if window:
        assert (w["schedule"]["from"], w["schedule"]["to"]) == window
    else:
        assert "schedule" not in w
    assert w["zone"] == zone and w["object"] == obj and w["condition"] == cond
    assert w["camera_ids"] == (["cam-gate-01"] if zone == "gate-2" else ["cam-street-02"])


def test_parser_severity_notify_days_and_stable_ids(vocab: SiteVocab) -> None:
    d = parse_rule("jumma ki raat 10 baje ke baad gate 2 par koi 5 min ruke to foran sab ko batao", "s", vocab, "sana")
    assert d.rule is not None
    assert d.rule.when.schedule is not None and d.rule.when.schedule.days == ["fri"]
    assert d.rule.then.alert.severity.value == "high" and d.rule.then.alert.notify == ["guard", "supervisor", "owner"]
    again = parse_rule("Raat 11 ke baad Gate 2 par koi 5 minute se zyada ruke", "s", vocab, "admin")
    first = parse_rule(PLAN_EXAMPLE, "s", vocab, "sana")
    assert again.rule is not None and first.rule is not None and again.rule.rule_id == first.rule.rule_id


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("koi ruke to batao", ["Kis jagah", "Kitni der"]),
        ("11 baje ke baad gate par 5 min", ["subah ya raat"]),
        ("gate 5 par 5 min", ["nahi mila"]),
        ("gate 2 par koi ho", ["Shart kya hai"]),
    ],
)
def test_parser_asks_instead_of_guessing(vocab: SiteVocab, text: str, expect: list[str]) -> None:
    d = parse_rule(text, "s", vocab, "sana")
    assert not d.valid and d.rule is None
    for e in expect:
        assert any(e in q for q in d.questions), d.questions


def test_parser_rejects_out_of_range_and_unsupported(vocab: SiteVocab) -> None:
    assert parse_rule("gate 2 par 5 sec ruke", "s", vocab, "sana").errors
    assert parse_rule("bazaar mein 3 se kam log", "s", vocab, "sana").errors


def _track(env: Env, local: datetime, seconds: float, cls: str = "person", zone: str = "gate-2") -> None:
    start = local.astimezone(UTC)
    t = TrackSummary(
        site_id=env.site_id,
        camera_id="cam-gate-01" if zone == "gate-2" else "cam-street-02",
        entity_id=f"e-{int(start.timestamp())}",
        track_ids=[int(start.timestamp()) % 100000],
        object=ObjectSummary(type=cls),
        zones=[zone],
        ts_start=start,
        ts_end=start + timedelta(seconds=seconds),
    )
    r = env.client.post("/v1/edge/tracks", json=t.model_dump(mode="json"), headers=env.edge)
    assert r.status_code == 201, r.text


def test_rule_lifecycle_backtest_approval_and_signed_bundle(env: Env) -> None:
    yesterday = (datetime.now(PK) - timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    _track(env, yesterday.replace(hour=23, minute=30), 400)  # in the window, stays > 5 min: match
    _track(env, yesterday.replace(hour=23, minute=40), 100)  # too short
    _track(env, yesterday.replace(hour=14), 900)  # outside the window
    _track(env, yesterday.replace(hour=23, minute=50), 900, cls="motorcycle")  # other object

    sana, admin = env.login("sana"), env.login("admin")
    assert (
        env.client.post(
            "/v1/rules/draft", json={"site_id": env.site_id, "text": PLAN_EXAMPLE}, headers=env.login("akram")
        ).status_code
        == 403
    )
    d = env.client.post("/v1/rules/draft", json={"site_id": env.site_id, "text": PLAN_EXAMPLE}, headers=sana).json()
    assert d["valid"] and d["backtest"]["matches"] == 1 and d["backtest"]["tracks_checked"] == 4
    assert d["rule"]["name_ur"].startswith("23:00 سے 05:00 تک: گیٹ 2 پر")

    r = env.client.post("/v1/rules", json={"rule": d["rule"]}, headers=sana)
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["created_by"] == "sana"
    rule_id = r.json()["rule_id"]
    assert env.client.post(f"/v1/rules/{rule_id}/approve", headers=sana).status_code == 403  # supervisors propose only
    assert env.client.get("/v1/edge/rules", headers=env.edge).json()["rules"] == []  # nothing unapproved deploys

    r = env.client.post(f"/v1/rules/{rule_id}/approve", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["rule"]["approved_by"] == "admin"
    assert env.client.post(f"/v1/rules/{rule_id}/approve", headers=admin).status_code == 409

    b1 = env.client.get("/v1/edge/rules", headers=env.edge).json()
    bundle = RuleBundle.model_validate(b1)
    assert [x.rule_id for x in bundle.rules] == [rule_id] and bundle.rules[0].approved_by == "admin"
    assert verify_json(bundle.public_key, bundle.signing_payload(), bundle.signature)
    tampered = bundle.model_copy(update={"site_id": "other-site"})
    assert not verify_json(bundle.public_key, tampered.signing_payload(), bundle.signature)
    assert env.client.get("/v1/edge/rules", headers=env.edge).json()["version"] == b1["version"]

    assert env.client.post(f"/v1/rules/{rule_id}/disable", headers=admin).json()["status"] == "disabled"
    b2 = env.client.get("/v1/edge/rules", headers=env.edge).json()
    assert b2["rules"] == [] and b2["version"] != b1["version"]
    listed = env.client.get(f"/v1/rules?site_id={env.site_id}", headers=sana).json()
    assert [(x["rule_id"], x["status"]) for x in listed] == [(rule_id, "disabled")]
    actions = [
        e["action"] for e in env.client.get("/v1/audit", headers=admin).json() if e["action"].startswith("rule.")
    ]
    assert {"rule.proposed", "rule.approved", "rule.disabled"} <= set(actions)


def test_rules_are_validated_against_the_site(env: Env) -> None:
    sana = env.login("sana")
    d = env.client.post("/v1/rules/draft", json={"site_id": env.site_id, "text": PLAN_EXAMPLE}, headers=sana).json()
    bad = {**d["rule"], "when": {**d["rule"]["when"], "camera_ids": ["cam-elsewhere"]}}
    r = env.client.post("/v1/rules", json={"rule": bad}, headers=sana)
    assert r.status_code == 422 and "cam-elsewhere" in r.json()["detail"]
    wrong_zone = {**d["rule"], "when": {**d["rule"]["when"], "zone": "market-front"}}
    assert env.client.post("/v1/rules", json={"rule": wrong_zone}, headers=sana).status_code == 422
    other = {**d["rule"], "site_id": "someone-elses-site"}
    assert env.client.post("/v1/rules", json={"rule": other}, headers=sana).status_code == 404
    assert env.client.get("/v1/rules", headers=env.login("police")).status_code == 403


def _heartbeat(env: Env, **versions: str) -> None:
    hb = {
        "device_id": "edge-demo-001",
        "site_id": env.site_id,
        "ts": datetime.now(UTC).isoformat(),
        "uptime_s": 60.0,
        "versions": versions,
    }
    assert env.client.post("/v1/edge/heartbeat", json=hb, headers=env.edge).status_code == 200


def test_dashboard_sees_when_rules_and_calendar_reach_the_edge(env: Env) -> None:
    sana, admin = env.login("sana"), env.login("admin")
    d = env.client.post("/v1/rules/draft", json={"site_id": env.site_id, "text": PLAN_EXAMPLE}, headers=sana).json()
    rule_id = env.client.post("/v1/rules", json={"rule": d["rule"]}, headers=sana).json()["rule_id"]
    env.client.post(f"/v1/rules/{rule_id}/approve", headers=admin)

    def on_edge() -> bool | None:
        return env.client.get("/v1/rules", headers=sana).json()[0]["on_edge"]

    def cal_synced() -> bool | None:
        return env.client.get(f"/v1/sites/{env.site_id}/calendar", headers=sana).json()["edge_synced"]

    assert on_edge() is None and cal_synced() is None  # no edge has reported yet
    _heartbeat(env, rules_bundle="none", calendar_bundle="none")
    assert on_edge() is False and cal_synced() is False  # the edge has not pulled the bundles yet
    rules_v = env.client.get("/v1/edge/rules", headers=env.edge).json()["version"]
    cal_v = env.client.get("/v1/edge/calendar", headers=env.edge).json()["version"]
    _heartbeat(env, rules_bundle=rules_v, calendar_bundle=cal_v)
    assert on_edge() is True and cal_synced() is True
    env.client.post(f"/v1/rules/{rule_id}/disable", headers=admin)
    assert env.client.get("/v1/rules", headers=sana).json()[0]["on_edge"] is None  # only active rules
