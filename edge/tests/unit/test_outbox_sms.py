import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from jikimi_common.ids import short_code
from jikimi_common.timeutil import PK_TZ
from jikimi_contracts import AlertCandidate, AlertType, EdgeAlertEnvelope, Route, Severity
from jikimi_edge.outbox.db import Outbox
from jikimi_edge.outbox.formatter import MAX_LEN, format_alert_sms, is_gsm7, parse_reply, to_gsm7
from jikimi_edge.outbox.server_client import SendResult
from jikimi_edge.outbox.sms_gateway import FileSmsGateway
from jikimi_edge.outbox.sync_agent import SyncAgent, SyncConfig


def _alert(sev: Severity = Severity.HIGH) -> AlertCandidate:
    now = datetime(2026, 10, 23, 18, 41, tzinfo=UTC)
    return AlertCandidate(
        alert_id=uuid4(),
        site_id="s",
        camera_id="cam-gate-01",
        type=AlertType.LOITERING,
        severity=sev,
        ts_start=now,
        ts_end=now,
        raw_score=0.9,
        route=Route.ALERT_NOW,
        zone_id="gate-2",
        features={"passes": 4, "riders": 2, "vehicle": "motorcycle"},
    )


class TestFormatter:
    def test_plan_example_shape(self) -> None:
        a = _alert()
        text = format_alert_sms(a, "Gate-2", a.ts_end.astimezone(PK_TZ), "A7F2")
        assert text.startswith("JIKIMI: Gate-2 par mashkook bike (2 sawar) 4 chakkar, 23:41.")
        assert "Code A7F2" in text and len(text) <= MAX_LEN and is_gsm7(text)

    def test_long_text_is_truncated_and_gsm7(self) -> None:
        a = _alert()
        text = format_alert_sms(a, "گیٹ" + "X" * 200, a.ts_end, "B1C2")
        assert len(text) <= MAX_LEN and is_gsm7(text) and "Code B1C2" in text

    def test_to_gsm7_drops_unsupported(self) -> None:
        assert to_gsm7("Gate–2 “ok” کالی") == 'Gate-2 "ok"'

    @pytest.mark.parametrize(
        ("text", "action", "code"),
        [
            ("1", "ack", None),
            ("1 a7f2", "ack", "A7F2"),
            ("Dekh liya", "ack", None),
            ("haan dekh liya A7F2", "ack", "A7F2"),
            ("2", "false_alarm", None),
            ("ghalat alarm", "false_alarm", None),
            ("3 madad", "need_help", None),
            ("kya hua?", None, None),
            ("bhai main ne dekh liya", "ack", None),
            ("A7F2 یہ غلط الارم ہے", "false_alarm", "A7F2"),
            ("madad nahi chahiye, sab theek hai", "false_alarm", None),
        ],
    )
    def test_parse_reply(self, text: str, action: str | None, code: str | None) -> None:
        assert parse_reply(text) == (action, code)


class TestOutbox:
    def test_idempotent_and_ordered(self, tmp_path) -> None:
        ob = Outbox(tmp_path / "o.db")
        assert ob.enqueue("alert", {"x": 1}, dedupe_key="a1", priority=0)
        assert not ob.enqueue("alert", {"x": 2}, dedupe_key="a1", priority=0)  # duplicate ignored
        ob.enqueue("heartbeat", {"n": 1}, dedupe_key="hb", priority=8, replace=True)
        ob.enqueue("heartbeat", {"n": 2}, dedupe_key="hb", priority=8, replace=True)  # upsert
        items = ob.due()
        assert [i.kind for i in items] == ["alert", "heartbeat"]
        assert items[1].payload == {"n": 2}
        assert ob.counts()["pending"] == 2

    def test_backoff_and_dead(self, tmp_path) -> None:
        ob = Outbox(tmp_path / "o.db")
        ob.enqueue("alert", {}, dedupe_key="a", now=100.0)
        item = ob.due(now=100.0)[0]
        delay = ob.backoff(item.id, item.attempts, "timeout", now=100.0)
        assert 0.8 <= delay <= 1.2 and ob.due(now=100.5) == []
        ob.mark_dead(item.id, "400 bad")
        assert ob.counts()["dead"] == 1 and ob.backlog() == 0

    def test_survives_reopen(self, tmp_path) -> None:
        ob = Outbox(tmp_path / "o.db")
        ob.enqueue("alert", {"k": "v"}, dedupe_key="a")
        ob.close()
        assert Outbox(tmp_path / "o.db").due()[0].payload == {"k": "v"}


class FakeClient:
    def __init__(self, online: bool) -> None:
        self.online = online
        self.sent: list[str] = []

    async def healthy(self) -> bool:
        return self.online

    async def send(self, item):  # type: ignore[no-untyped-def]
        if not self.online:
            return SendResult(ok=False, error="down")
        self.sent.append(item.kind)
        return SendResult(ok=True, status=202)


def _agent(tmp_path, client: FakeClient, numbers: list[str]) -> tuple[SyncAgent, Outbox, FileSmsGateway]:
    ob = Outbox(tmp_path / "o.db")
    gw = FileSmsGateway(tmp_path / "sms")
    agent = SyncAgent(
        ob,
        client,  # type: ignore[arg-type]
        gw,
        SyncConfig(sms_numbers=numbers, sms_grace_s=5.0, health_cache_s=0.0, receive_interval_s=0.0),
        where=lambda a: "Gate-2",
        local_time=lambda dt: dt.astimezone(PK_TZ),
    )
    return agent, ob, gw


def _enqueue(ob: Outbox, a: AlertCandidate, now: float) -> None:
    ob.enqueue(
        "alert",
        EdgeAlertEnvelope(alert=a).model_dump(mode="json"),
        severity=a.severity.value,
        priority=0,
        dedupe_key=str(a.alert_id),
        now=now,
    )


def test_offline_high_alert_goes_by_sms_then_syncs(tmp_path) -> None:
    client = FakeClient(online=False)
    agent, ob, _ = _agent(tmp_path, client, ["+923001234567"])
    a = _alert()
    _enqueue(ob, a, now=1000.0)
    asyncio.run(agent.step(now=1002.0))
    assert not (tmp_path / "sms" / "outbox.jsonl").exists()  # still inside the grace period
    asyncio.run(agent.step(now=1006.0))
    sms = (tmp_path / "sms" / "outbox.jsonl").read_text()
    assert short_code(a.alert_id) in sms
    assert ob.counts()["sms_sent"] == 1
    # guard replies "1 <code>" -> local ack queued for the server
    (tmp_path / "sms" / "inbox.jsonl").write_text(
        f'{{"from": "+923001234567", "text": "1 {short_code(a.alert_id)}"}}\n'
    )
    asyncio.run(agent.step(now=1010.0))
    assert ob.pending_acks()[0]["action"] == "ack"
    # internet back: alert (marked as SMS-delivered) and ack are both synced
    client.online = True
    asyncio.run(agent.step(now=1020.0))
    assert sorted(client.sent) == ["ack", "alert"]
    assert ob.counts()["sent"] == 2


def test_online_alert_needs_no_sms(tmp_path) -> None:
    client = FakeClient(online=True)
    agent, ob, _ = _agent(tmp_path, client, ["+923001234567"])
    _enqueue(ob, _alert(), now=1000.0)
    asyncio.run(agent.step(now=1001.0))
    asyncio.run(agent.step(now=1010.0))
    assert client.sent == ["alert"] and not (tmp_path / "sms" / "outbox.jsonl").exists()


def test_medium_alert_never_sms(tmp_path) -> None:
    agent, ob, _ = _agent(tmp_path, FakeClient(online=False), ["+923001234567"])
    _enqueue(ob, _alert(Severity.MEDIUM), now=1000.0)
    asyncio.run(agent.step(now=1100.0))
    assert ob.counts()["sms_sent"] == 0


def test_unknown_number_cannot_ack(tmp_path) -> None:
    agent, ob, _ = _agent(tmp_path, FakeClient(online=False), ["+923001234567"])
    a = _alert()
    _enqueue(ob, a, now=1000.0)
    asyncio.run(agent.step(now=1010.0))
    (tmp_path / "sms" / "inbox.jsonl").write_text(
        f'{{"from": "+920000000000", "text": "1 {short_code(a.alert_id)}"}}\n'
    )
    asyncio.run(agent.step(now=1012.0))
    assert ob.pending_acks() == []
