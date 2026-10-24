from __future__ import annotations

from datetime import UTC, datetime

from jikimi_contracts.commands import CommandBundle
from jikimi_crypto import verify_json

from .conftest import Env


def test_admin_accepts_a_moved_cameras_view(env: Env) -> None:
    url = f"/v1/sites/{env.site_id}/cameras/cam-gate-01/accept-view"
    admin = env.login("admin")
    assert env.client.post(url, headers=env.login("sana")).status_code == 403  # admins only
    assert env.client.post(f"/v1/sites/{env.site_id}/cameras/cam-x/accept-view", headers=admin).status_code == 404
    cmd = env.client.post(url, headers=admin).json()
    assert cmd["kind"] == "accept_view" and cmd["camera_id"] == "cam-gate-01" and cmd["issued_by"] == "admin"

    bundle = CommandBundle.model_validate(env.client.get("/v1/edge/commands", headers=env.edge).json())
    assert [c.id for c in bundle.commands] == [cmd["id"]]
    assert verify_json(bundle.public_key, bundle.signing_payload(), bundle.signature)

    hb = {
        "device_id": "edge-demo-001",
        "site_id": env.site_id,
        "ts": datetime.now(UTC).isoformat(),
        "uptime_s": 10.0,
        "extra": {"commands_done": [cmd["id"]]},
    }
    assert env.client.post("/v1/edge/heartbeat", json=hb, headers=env.edge).status_code == 200
    assert env.client.get("/v1/edge/commands", headers=env.edge).json()["commands"] == []  # done, not resent
    actions = [e["action"] for e in env.client.get("/v1/audit", headers=admin).json()]
    assert "camera.accept_view" in actions
