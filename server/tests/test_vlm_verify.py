from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import cv2
import numpy as np
from jikimi_contracts import AlertType, Route
from jikimi_server.services.vlm import VlmAnswer, verdict_of
from jikimi_server.workers import Workers

from .conftest import Env


class _FakeVlm:
    available = True
    name = "fake-vlm"

    def types(self) -> list[str]:
        return ["snatch"]

    def __init__(self, p_yes: float) -> None:
        self.p_yes = p_yes
        self.seen: list[int] = []

    def verify(self, alert_type: str, images: list[Any]) -> VlmAnswer:
        self.seen.append(len(images))
        verdict, conf = verdict_of(self.p_yes)
        return VlmAnswer(self.p_yes, verdict, conf, len(images), 5)


def _jpeg() -> bytes:
    return cv2.imencode(".jpg", np.full((90, 160, 3), 120, np.uint8))[1].tobytes()


def _verify(env: Env, p_yes: float, gate: bool) -> dict[str, Any]:
    ctx = env.app.state.ctx
    ctx.verifier = _FakeVlm(p_yes)
    ctx.alerts.vlm_enabled, ctx.alerts.vlm_advisory = gate, not gate
    a = env.alert(AlertType.SNATCH, Route.VERIFY)
    assert env.post_alert(a).status_code in (200, 201, 202)
    assert env.post_clip(a.alert_id, kf=_jpeg()).status_code in (200, 201, 202)
    workers = Workers(ctx)
    with ctx.db.session() as db:
        job = workers._next_vlm_job(db, datetime.now(UTC))
    assert job is not None
    job.result(timeout=10)
    assert ctx.verifier.seen == [1]  # the keyframe was decoded and passed on
    return env.client.get(f"/v1/alerts/{a.alert_id}", headers=env.login("sana")).json()


def test_advisory_vlm_attaches_its_opinion_without_holding_the_alert(env: Env) -> None:
    d = _verify(env, p_yes=0.1, gate=False)
    assert d["status"] == "open" and d["vlm_verdict"] == "normal" and d["verified"] is None  # still reaches the guard
    kinds = [e["kind"] for e in d["events"]]
    assert "verify_requested" in kinds and "verified" in kinds and kinds.index("opened") < kinds.index("verified")


def test_gate_mode_logs_a_normal_verdict_and_opens_an_unclear_one(env: Env) -> None:
    assert _verify(env, p_yes=0.1, gate=True)["status"] == "logged_only"
    unclear = _verify(env, p_yes=0.55, gate=True)
    assert unclear["status"] == "open" and unclear["vlm_verdict"] == "unclear"  # never suppressed on doubt
    confirmed = _verify(env, p_yes=0.9, gate=True)
    assert confirmed["status"] == "open" and confirmed["verified"] is True and confirmed["vlm_verdict"] == "snatch"
