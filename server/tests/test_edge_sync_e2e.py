"""End to end, no fakes: the real API signs rules and the event calendar, the real edge sync agent
pulls them over HTTP (ASGI transport), checks them against the pinned server key and applies them
to a running pipeline."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from pathlib import Path

import httpx
from jikimi_edge.analytics.rules.plugin import RulesPlugin
from jikimi_edge.analytics.rules.sync import RuleSync
from jikimi_edge.config_sync import CalendarSync
from jikimi_edge.outbox.db import Outbox
from jikimi_edge.outbox.server_client import ServerClient
from jikimi_edge.outbox.sms_gateway import FileSmsGateway
from jikimi_edge.outbox.sync_agent import SyncAgent, SyncConfig
from jikimi_edge.runner import build_pipeline
from jikimi_edge.settings import load_settings

from .conftest import REPO, Env

PLAN_EXAMPLE = "raat 11 ke baad gate 2 par koi 5 min se zyada ruke to batao"


def test_edge_applies_rules_and_calendar_signed_by_the_real_server(env: Env, tmp_path: Path) -> None:
    sana, admin = env.login("sana"), env.login("admin")
    draft = env.client.post("/v1/rules/draft", json={"site_id": env.site_id, "text": PLAN_EXAMPLE}, headers=sana).json()
    rule_id = env.client.post("/v1/rules", json={"rule": draft["rule"]}, headers=sana).json()["rule_id"]
    assert env.client.post(f"/v1/rules/{rule_id}/approve", headers=admin).status_code == 200
    settings = dataclasses.replace(
        load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO), data_dir=tmp_path
    )
    today = datetime.now(settings.tz).date().isoformat()
    window = {"name": "Chand Raat", "mode": "chand_raat", "starts": today, "ends": today}
    assert env.client.post(f"/v1/sites/{env.site_id}/calendar", json=window, headers=admin).status_code == 201

    pipeline, _, _ = build_pipeline(settings, with_outbox=False, record_clips=False)
    rules = RuleSync(tmp_path / "rules", tmp_path / "server.pub", env.site_id, pipeline.set_rules)
    calendar = CalendarSync(tmp_path / "cal", tmp_path / "server.pub", env.site_id, pipeline.set_calendar)
    client = ServerClient("http://testserver", env.token)
    client._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {env.token}"},
    )
    agent = SyncAgent(
        Outbox(tmp_path / "o.db"),
        client,
        FileSmsGateway(tmp_path / "sms"),
        SyncConfig(health_cache_s=0.0),
        where=lambda a: "-",
        local_time=lambda dt: dt,
        bundles=(rules, calendar),
    )

    async def sync_once() -> None:
        await agent.step()
        await client.aclose()

    asyncio.run(sync_once())
    gate_rules = next(p for p in pipeline.cameras["cam-gate-01"].plugins if isinstance(p, RulesPlugin))
    street_rules = next(p for p in pipeline.cameras["cam-street-02"].plugins if isinstance(p, RulesPlugin))
    assert [r.rule_id for r in gate_rules.rules] == [rule_id] and street_rules.rules == []  # only its camera
    assert gate_rules.rules[0].approved_by == "admin"
    assert pipeline.mode(datetime.now(settings.tz).timestamp()) == "chand_raat"
    assert (tmp_path / "server.pub").read_text().strip() == env.app.state.ctx.evidence.signer.public_key
    assert rules.version and calendar.version  # both pinned to the same server key
