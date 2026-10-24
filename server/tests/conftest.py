from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from jikimi_common.ids import uuid7
from jikimi_contracts import (
    AlertCandidate,
    AlertType,
    ClipAttestation,
    EdgeAlertEnvelope,
    KeyframeRef,
    ObjectSummary,
    Route,
    Severity,
)
from jikimi_crypto import Signer, generate_private_key, sha256_hex
from jikimi_server.db.session import Database
from jikimi_server.main import create_app
from jikimi_server.seed import seed_site
from jikimi_server.settings import ServerSettings

REPO = Path(__file__).resolve().parents[2]
PASSWORD = "test-" + secrets.token_urlsafe(12)


@dataclass
class Env:
    client: TestClient
    app: Any
    device: Signer
    token: str
    site_id: str
    tmp: Path

    def login(self, username: str) -> dict[str, str]:
        r = self.client.post("/v1/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    @property
    def edge(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def alert(
        self, type_: AlertType = AlertType.LOITERING, route: Route = Route.ALERT_NOW, **kw: Any
    ) -> AlertCandidate:
        now = datetime.now(UTC)
        base: dict[str, Any] = dict(
            alert_id=uuid7(),
            site_id=self.site_id,
            camera_id="cam-gate-01",
            type=type_,
            severity=Severity.HIGH if route == Route.ALERT_NOW else Severity.MEDIUM,
            ts_start=now - timedelta(seconds=90),
            ts_end=now,
            raw_score=0.9,
            p_value=0.004,
            route=route,
            zone_id="gate-2",
            entity_id="cam-gate-01:mot:7",
            objects=[ObjectSummary(type="motorcycle", color="black", riders=2)],
            features={
                "passes": 4,
                "window_min": 15,
                "riders": 2,
                "slowdowns_near_ped": 2,
                "vehicle": "motorcycle",
                "color": "black",
            },
        )
        base.update(kw)
        a = AlertCandidate.model_validate(base)
        unsigned = a.model_copy(update={"device_key_id": self.device.key_id})
        return unsigned.model_copy(update={"signature": self.device.sign(unsigned.signing_payload())})

    def post_alert(self, a: AlertCandidate, sms: bool = False, sms_at: datetime | None = None) -> Any:
        env = EdgeAlertEnvelope(alert=a)
        if sms or sms_at:
            env.delivery.sms_sent_at = sms_at or datetime.now(UTC)
            env.delivery.sms_recipients = 1
        return self.client.post(
            "/v1/edge/alerts",
            json=env.model_dump(mode="json"),
            headers={**self.edge, "Idempotency-Key": str(a.alert_id)},
        )

    def post_clip(
        self, alert_id: UUID, clip: bytes = b"\x00\x00\x00\x18ftypmp42fake-mp4-bytes" * 50, kf: bytes | None = None
    ) -> Any:
        kf = kf or b"\xff\xd8\xff\xe0fake-jpeg" * 20
        now = datetime.now(UTC)
        att = ClipAttestation(
            alert_id=alert_id,
            clip_id=f"CL-{now:%Y-%m-%d}-{alert_id.hex[-8:].upper()}",
            site_id=self.site_id,
            camera_id="cam-gate-01",
            ts_start=now - timedelta(seconds=30),
            ts_end=now,
            clip_sha256=sha256_hex(clip),
            keyframes=[KeyframeRef(name="k0.jpg", sha256=sha256_hex(kf), ts=now)],
            frames=150,
            fps=5.0,
        )
        att = att.model_copy(update={"device_key_id": self.device.key_id})
        att = att.model_copy(update={"signature": self.device.sign(att.signing_payload())})
        return self.client.post(
            "/v1/edge/clips",
            data={"attestation": att.model_dump_json()},
            files=[("clip", ("c.mp4", clip, "video/mp4")), ("keyframes", ("k0.jpg", kf, "image/jpeg"))],
            headers=self.edge,
        )


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    pg = os.environ.get("JIKIMI_TEST_DATABASE_URL")  # e.g. postgresql+psycopg://... (CI matrix)
    settings = ServerSettings(
        database_url=pg or f"sqlite:///{tmp_path / 'db.sqlite'}",
        data_dir=tmp_path / "server",
        jwt_secret=secrets.token_urlsafe(40),
        public_base_url="http://testserver",
        dashboard_dir=tmp_path / "no-dashboard",
        workers_inprocess=False,
    )
    device = Signer.from_key(generate_private_key(), prefix="edge")
    db = Database(settings.database_url)
    if pg:
        from jikimi_server.db.models import Base

        Base.metadata.drop_all(db.engine)
    db.create_all()
    token_file = tmp_path / "device.token"
    res = seed_site(db, REPO / "edge/config/site.demo.yaml", PASSWORD, device.public_key, device.key_id, token_file)
    app = create_app(settings)
    with TestClient(app) as client:
        yield Env(
            client=client, app=app, device=device, token=token_file.read_text(), site_id=res.site_id, tmp=tmp_path
        )
