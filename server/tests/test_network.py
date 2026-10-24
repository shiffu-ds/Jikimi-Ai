from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import numpy as np
import yaml
from jikimi_contracts import AlertType, Route
from jikimi_contracts.network import NetworkBundle
from jikimi_crypto import Signer, generate_private_key, verify_json
from jikimi_server.seed import seed_site
from jikimi_server.services import network

from .conftest import PASSWORD, REPO, Env

LAHORE_A = {"lat": 31.5204, "lon": 74.3587}
LAHORE_B = {"lat": 31.5250, "lon": 74.3632}  # ~0.65 km away
AGREEMENT = "Signed by both site owners, 2026-10-24"


def _site_b(env: Env) -> dict[str, str]:
    cfg = yaml.safe_load((REPO / "edge/config/site.demo.yaml").read_text(encoding="utf-8"))
    cfg.update(site_id="market-south", site_name="Market South", device_id="edge-market-001")
    for c in cfg["cameras"]:
        c["id"] = c["id"].replace("cam-", "cam-ms-")
    path = env.tmp / "site_b.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    dev = Signer.from_key(generate_private_key(), prefix="edge")
    seed_site(env.app.state.ctx.db, path, PASSWORD, dev.public_key, dev.key_id, env.tmp / "b.token")
    return {"Authorization": f"Bearer {(env.tmp / 'b.token').read_text()}"}


def _desc() -> str:
    v = np.random.default_rng(3).random(64).astype(np.float16)
    return base64.b64encode(v.tobytes()).decode()


def test_confirmed_incidents_reach_opted_in_neighbours_only_as_embeddings(env: Env) -> None:
    edge_b = _site_b(env)
    admin = env.login("admin")
    a_url, b_url = f"/v1/sites/{env.site_id}/network", "/v1/sites/market-south/network"
    no_agreement = {"opted_in": True, "radius_km": 1.5, **LAHORE_A}
    assert env.client.put(a_url, json=no_agreement, headers=admin).status_code == 422  # written agreement first
    assert env.client.put(a_url, json={**no_agreement, "agreement": AGREEMENT}, headers=admin).status_code == 200
    a = env.alert(AlertType.SNATCH, Route.ALERT_NOW)
    assert env.post_alert(a).status_code == 202
    emb = {
        "alert_id": str(a.alert_id),
        "site_id": env.site_id,
        "descriptor_b64": _desc(),
        "riders": 2,
        "color": "black",
    }
    assert env.client.post("/v1/edge/embeddings", json=emb, headers=env.edge).json() == {"kept": True}

    b_on = {"opted_in": True, "radius_km": 1.0, "agreement": AGREEMENT, **LAHORE_B}
    assert env.client.put(b_url, json=b_on, headers=admin).json()["neighbors"] == 1
    assert env.client.get("/v1/edge/network", headers=edge_b).json()["shares"] == []  # not confirmed yet
    review = env.client.post(f"/v1/alerts/{a.alert_id}/review", json={"verdict": "true"}, headers=env.login("sana"))
    assert review.status_code == 200
    bundle = NetworkBundle.model_validate(env.client.get("/v1/edge/network", headers=edge_b).json())
    assert verify_json(bundle.public_key, bundle.signing_payload(), bundle.signature)
    (share,) = bundle.shares
    assert share.riders == 2 and share.color == "black" and 0.3 < share.distance_km < 1.0
    assert timedelta(hours=1.9) < share.expires_at - datetime.now(UTC) <= timedelta(hours=2)
    assert not {"image", "thumbnail", "jpeg", "clip"} & set(share.model_dump())  # never a picture
    assert env.client.get("/v1/edge/network", headers=env.edge).json()["shares"] == []  # not back to itself
    actions = [e["action"] for e in env.client.get("/v1/audit", headers=admin).json()]
    assert "network.share" in actions and "network.settings" in actions

    with env.app.state.ctx.db.session() as db:  # 2 h later the share is gone (deleted)
        assert network.purge(db, datetime.now(UTC) + timedelta(hours=2, minutes=1)) == 1
    assert env.client.get("/v1/edge/network", headers=edge_b).json()["shares"] == []


def test_no_sharing_without_opt_in_and_opting_out_withdraws(env: Env) -> None:
    edge_b = _site_b(env)
    admin = env.login("admin")
    a = env.alert(AlertType.SNATCH, Route.ALERT_NOW)
    env.post_alert(a)
    emb = {"alert_id": str(a.alert_id), "site_id": env.site_id, "descriptor_b64": _desc(), "riders": 2}
    assert env.client.post("/v1/edge/embeddings", json=emb, headers=env.edge).json() == {"kept": False}  # not opted in
    a_on = {"opted_in": True, "radius_km": 1.5, "agreement": AGREEMENT, **LAHORE_A}
    env.client.put(f"/v1/sites/{env.site_id}/network", json=a_on, headers=admin)
    env.client.put("/v1/sites/market-south/network", json={**a_on, **LAHORE_B}, headers=admin)
    a2 = env.alert(AlertType.SNATCH, Route.ALERT_NOW)
    env.post_alert(a2)
    env.client.post("/v1/edge/embeddings", json={**emb, "alert_id": str(a2.alert_id)}, headers=env.edge)
    env.client.post(f"/v1/alerts/{a2.alert_id}/review", json={"verdict": "true"}, headers=env.login("sana"))
    assert len(env.client.get("/v1/edge/network", headers=edge_b).json()["shares"]) == 1
    env.client.put(f"/v1/sites/{env.site_id}/network", json={**a_on, "opted_in": False}, headers=admin)
    assert env.client.get("/v1/edge/network", headers=edge_b).json()["shares"] == []  # withdrawn at once
