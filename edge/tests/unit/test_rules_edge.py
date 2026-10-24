from __future__ import annotations

import asyncio
import dataclasses
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from jikimi_contracts import AlertType, Severity
from jikimi_contracts.modes import CalendarBundle, ModeWindow
from jikimi_contracts.rules_dsl import Rule, RuleBundle
from jikimi_crypto import Signer, generate_private_key
from jikimi_edge.analytics.rules.sync import RuleSync
from jikimi_edge.config_sync import CalendarSync
from jikimi_edge.outbox.db import Outbox
from jikimi_edge.outbox.server_client import SendResult
from jikimi_edge.outbox.sms_gateway import FileSmsGateway
from jikimi_edge.outbox.sync_agent import SyncAgent, SyncConfig
from jikimi_edge.runner import build_pipeline, replay
from jikimi_edge.settings import load_settings

REPO = Path(__file__).resolve().parents[3]
SITE = "society-gate-north"


def _rule(rule_id: str = "r-gate-2-person-dwell60-test", approved: str | None = "admin", **cond: Any) -> Rule:
    return Rule.model_validate(
        {
            "rule_id": rule_id,
            "name_ur": "گیٹ 2 پر کوئی شخص 1 منٹ سے زیادہ رکے",
            "site_id": SITE,
            "when": {
                "camera_ids": ["cam-gate-01"],
                "zone": "gate-2",
                "object": {"type": "person"},
                "condition": cond or {"dwell_seconds_gt": 60},
            },
            "then": {"alert": {"severity": "high", "notify": ["guard", "supervisor"]}},
            "created_by": "sana",
            "approved_by": approved,
        }
    )


def _bundle(server: Signer, rules: list[Rule], site: str = SITE, version: str = "v1") -> RuleBundle:
    b = RuleBundle(
        site_id=site,
        version=version,
        rules=rules,
        key_id=server.key_id,
        public_key=server.public_key,
        signed_at=datetime.now(UTC),
        signature="",
    )
    return b.model_copy(update={"signature": server.sign(b.signing_payload())})


@pytest.fixture
def server() -> Signer:
    return Signer.from_key(generate_private_key(), prefix="server")


def test_bundle_is_verified_pinned_persisted_and_reloaded(tmp_path: Path, server: Signer) -> None:
    applied: list[list[str]] = []
    sync = RuleSync(
        tmp_path / "rules", tmp_path / "server.pub", SITE, lambda rs: applied.append([r.rule_id for r in rs])
    )
    b = _bundle(server, [_rule()])
    assert sync.accept(b) and applied == [["r-gate-2-person-dwell60-test"]]
    assert (tmp_path / "server.pub").read_text().strip() == server.public_key
    assert sync.accept(b) and len(applied) == 1  # same version: nothing to do

    restarted = RuleSync(tmp_path / "rules", tmp_path / "server.pub", SITE, lambda rs: applied.append(["reload"]))
    restarted.load()  # rules survive a reboot with the internet down
    assert applied[-1] == ["reload"] and restarted.version == "v1"


def test_bad_bundles_are_refused(tmp_path: Path, server: Signer) -> None:
    applied: list[Any] = []
    sync = RuleSync(tmp_path / "rules", tmp_path / "server.pub", SITE, applied.append)
    assert sync.accept(_bundle(server, [_rule()]))
    good = _bundle(server, [_rule()], version="v2")
    tampered = good.model_copy(update={"rules": [_rule(dwell_seconds_gt=11)]})
    assert sync.refusal(tampered) == "bad signature"
    other_key = Signer.from_key(generate_private_key(), prefix="server")
    assert "pinned" in (sync.refusal(_bundle(other_key, [_rule()], version="v3")) or "")
    assert "site" in (sync.refusal(_bundle(server, [_rule()], site="elsewhere", version="v4")) or "")
    assert "unapproved" in (sync.refusal(_bundle(server, [_rule(approved=None)], version="v5")) or "")
    assert not sync.accept(tampered)
    assert len(applied) == 1 and sync.version == "v1"
    # a newer bundle replaces it; replaying the older signed one must not roll the rules back
    first = _bundle(server, [_rule()], version="v1")
    newer = _bundle(server, [_rule(), _rule("r-gate-2-person-dwell90-test", dwell_seconds_gt=90)], version="v6")
    assert sync.accept(newer)
    stale = first.model_copy(update={"signed_at": datetime(2026, 1, 1, tzinfo=UTC)})
    stale = stale.model_copy(update={"signature": server.sign(stale.signing_payload())})
    assert "replayed" in (sync.refusal(stale) or "") and not sync.accept(stale) and sync.version == "v6"


def test_server_rule_fires_on_the_live_pipeline(tmp_path: Path, server: Signer) -> None:
    settings = dataclasses.replace(
        load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO), data_dir=tmp_path
    )
    pipeline, _, _ = build_pipeline(settings, with_outbox=False, record_clips=False)
    sync = RuleSync(tmp_path / "rules", tmp_path / "server.pub", SITE, pipeline.set_rules)
    # a person waits ~3.5 min at the gate in this scenario; nothing else stays a minute there
    assert sync.accept(
        _bundle(server, [_rule(), _rule("r-gate-2-person-count2-dwell30-test", count_gt=2, dwell_seconds_gt=30)])
    )
    res = replay(settings, "cam-gate-01", "loiter_basic", seed=1, pipeline=pipeline)
    fired = [a for a in res.alerts if a.type == AlertType.RULE]
    assert [a.features["rule_id"] for a in fired] == ["r-gate-2-person-dwell60-test"]
    a = fired[0]
    assert a.severity == Severity.HIGH and a.features["dwell_s"] > 60 and a.zone_id == "gate-2"
    assert a.features["notify"] == ["guard", "supervisor"] and a.model_versions["rules"].endswith("@v1")

    pipeline.set_rules([])  # disabled on the server -> gone on the next bundle
    again = replay(settings, "cam-gate-01", "loiter_basic", seed=1, pipeline=pipeline, start_ts=1_793_100_000.0)
    assert not [x for x in again.alerts if x.type == AlertType.RULE]


class _Server:
    def __init__(self, bundles: dict[str, dict[str, Any]]) -> None:
        self.bundles = bundles
        self.gets: list[str] = []

    async def healthy(self) -> bool:
        return True

    async def send(self, item: Any) -> SendResult:
        return SendResult(ok=True, status=202)

    async def get_json(self, path: str) -> dict[str, Any]:
        self.gets.append(path)
        return self.bundles[path]


def _calendar(server: Signer, windows: list[ModeWindow], version: str = "c1") -> CalendarBundle:
    b = CalendarBundle(
        site_id=SITE,
        version=version,
        windows=windows,
        key_id=server.key_id,
        public_key=server.public_key,
        signed_at=datetime.now(UTC),
        signature="",
    )
    return b.model_copy(update={"signature": server.sign(b.signing_payload())})


def test_sync_agent_pulls_rules_and_calendar_only_while_online(tmp_path: Path, server: Signer) -> None:
    got: dict[str, list[str]] = {}
    rules = RuleSync(
        tmp_path / "rules", tmp_path / "server.pub", SITE, lambda rs: got.update(rules=[r.rule_id for r in rs])
    )
    calendar = CalendarSync(
        tmp_path / "cal", tmp_path / "server.pub", SITE, lambda ws: got.update(cal=[w.mode for w in ws])
    )
    chand = ModeWindow(name="Chand Raat 1448", mode="chand_raat", starts=date(2027, 3, 9), ends=date(2027, 3, 9))
    fake = _Server(
        {
            "/v1/edge/rules": _bundle(server, [_rule()]).model_dump(mode="json", by_alias=True),
            "/v1/edge/calendar": _calendar(server, [chand]).model_dump(mode="json"),
        }
    )
    offline = tmp_path / "OFFLINE"
    agent = SyncAgent(
        Outbox(tmp_path / "o.db"),
        fake,  # type: ignore[arg-type]
        FileSmsGateway(tmp_path / "sms"),
        SyncConfig(health_cache_s=0.0, config_interval_s=60.0, offline_flag=offline),
        where=lambda a: "-",
        local_time=lambda dt: dt,
        bundles=(rules, calendar),
    )
    offline.touch()
    asyncio.run(agent.step())
    assert fake.gets == [] and got == {}
    offline.unlink()
    asyncio.run(agent.step())
    asyncio.run(agent.step())  # inside the 60 s interval: no second fetch
    assert fake.gets == ["/v1/edge/rules", "/v1/edge/calendar"]
    assert got == {"rules": ["r-gate-2-person-dwell60-test"], "cal": ["chand_raat"]}
    # both bundles share the pinned server key: a calendar from another key is refused
    other = Signer.from_key(generate_private_key(), prefix="server")
    assert "pinned" in (calendar.refusal(_calendar(other, [], version="c2")) or "")


def test_calendar_switches_mode_and_calibration_set(tmp_path: Path, server: Signer) -> None:
    base = load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO)
    cal_dir = tmp_path / "calibration"
    shutil.copytree(base.calibration_dir, cal_dir)
    for f in cal_dir.rglob("*.chand_raat.json"):
        f.unlink()  # start like a site that has not calibrated Chand Raat yet
    settings = dataclasses.replace(base, data_dir=tmp_path / "edge", calibration_dir=cal_dir)
    start = 1_793_000_000.0
    day = datetime.fromtimestamp(start, UTC).astimezone(settings.tz).date()
    pipeline, _, _ = build_pipeline(settings, with_outbox=False, record_clips=False)
    assert pipeline.mode(start) == "normal"
    pipeline.set_calendar([ModeWindow(name="Chand Raat", mode="chand_raat", starts=day, ends=day)])
    assert pipeline.mode(start) == "chand_raat" and pipeline.mode(start + 86_400 * 2) == "normal"

    res = replay(settings, "cam-street-02", "snatch_basic", seed=1, start_ts=start, pipeline=pipeline)
    snatch = next(a for a in res.alerts if a.type == AlertType.SNATCH)
    # no Chand Raat calibration yet: the p-value honestly compares against ordinary days
    assert snatch.mode == "chand_raat" and snatch.features["calibration_mode"] == "normal"

    site_dir = cal_dir / settings.site_id
    (site_dir / "snatch.chand_raat.json").write_text(
        (site_dir / "snatch.normal.json").read_text().replace('"normal"', '"chand_raat"')
    )
    pipeline2, _, _ = build_pipeline(settings, with_outbox=False, record_clips=False)
    pipeline2.set_calendar([ModeWindow(name="Chand Raat", mode="chand_raat", starts=day, ends=day)])
    res2 = replay(settings, "cam-street-02", "snatch_basic", seed=1, start_ts=start, pipeline=pipeline2)
    snatch2 = next(a for a in res2.alerts if a.type == AlertType.SNATCH)
    assert snatch2.features["calibration_mode"] == "chand_raat" and snatch2.p_value is not None


def test_heartbeat_reports_bundles_and_mode(tmp_path: Path, server: Signer) -> None:
    from jikimi_edge.runner import LiveRunner

    settings = dataclasses.replace(
        load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO), data_dir=tmp_path
    )
    pipeline, outbox, _ = build_pipeline(settings, with_outbox=True, record_clips=False)
    assert outbox is not None
    runner = LiveRunner(settings, pipeline, outbox, sources={})
    hb = runner.heartbeat()
    assert (hb.versions["rules_bundle"], hb.versions["calendar_bundle"], hb.versions["event_mode"]) == (
        "none",
        "none",
        "normal",
    )
    today = datetime.now(settings.tz).date()
    assert runner.rules.accept(_bundle(server, [_rule()]))
    assert runner.calendar.accept(
        _calendar(server, [ModeWindow(name="Bazaar", mode="bazaar_day", starts=today, ends=today)])
    )
    hb = runner.heartbeat()
    assert (hb.versions["rules_bundle"], hb.versions["calendar_bundle"], hb.versions["event_mode"]) == (
        "v1",
        "c1",
        "bazaar_day",
    )


def test_volume_is_reported_against_the_calibration_rate(tmp_path: Path) -> None:
    from collections import deque

    settings = dataclasses.replace(
        load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO), data_dir=tmp_path
    )
    pipeline, _, _ = build_pipeline(settings, with_outbox=False, record_clips=False)
    base = pipeline.calibration.units_per_hour("loitering")
    assert base is not None and base > 100
    now = 1_800_000_000.0
    gate, street = pipeline.cameras["cam-gate-01"], pipeline.cameras["cam-street-02"]
    gate.first_frame_ts = street.first_frame_ts = now - 1800  # half an hour of video
    gate.bike_ends = deque(now - 1800 + i * 1800 / base for i in range(int(base)))  # a full hour's bikes in 30 min
    street.bike_ends = deque([now - 7200, now - 10])  # the 2 h old bike falls out of the window
    vol = pipeline.volume(now)
    assert 1.9 <= vol["cam-gate-01"] <= 2.1 and vol["cam-street-02"] < 0.1 and len(street.bike_ends) == 1
    gate.first_frame_ts = now - 300  # too little video to say anything
    assert "cam-gate-01" not in pipeline.volume(now)


def test_commands_run_once_even_after_a_restart(tmp_path: Path, server: Signer) -> None:
    from jikimi_contracts.commands import CommandBundle, EdgeCommand
    from jikimi_edge.config_sync import CommandSync

    ran: list[str] = []
    cmd = EdgeCommand(
        id="c1", kind="accept_view", camera_id="cam-gate-01", issued_by="admin", issued_at=datetime.now(UTC)
    )

    def bundle(version: str, commands: list[EdgeCommand]) -> CommandBundle:
        b = CommandBundle(
            site_id=SITE,
            version=version,
            commands=commands,
            key_id=server.key_id,
            public_key=server.public_key,
            signed_at=datetime.now(UTC),
            signature="",
        )
        return b.model_copy(update={"signature": server.sign(b.signing_payload())})

    sync = CommandSync(tmp_path / "cmd", tmp_path / "server.pub", SITE, lambda c: ran.append(c.id) or True)
    assert sync.accept(bundle("v1", [cmd])) and ran == ["c1"] and sync.done == ["c1"]
    again = CommandSync(tmp_path / "cmd", tmp_path / "server.pub", SITE, lambda c: ran.append(c.id) or True)
    again.load()  # restart: the stored bundle is applied again, the command is not
    assert ran == ["c1"]

    settings = dataclasses.replace(
        load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO), data_dir=tmp_path / "e"
    )
    pipeline, _, _ = build_pipeline(settings, with_outbox=False, record_clips=False)
    assert pipeline.reanchor("cam-gate-01", by="admin:admin") and not pipeline.reanchor("cam-nope")
    assert pipeline.cameras["cam-gate-01"].health_plugin._reanchor_by == "admin:admin"  # type: ignore[union-attr]
