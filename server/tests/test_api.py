from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jikimi_contracts import AlertType, Route
from jikimi_server.db.models import Alert, Site, User
from jikimi_server.workers import Workers

from .conftest import Env


def test_health_is_public(env: Env) -> None:
    assert env.client.get("/v1/health").json()["status"] == "ok"
    assert env.client.get("/v1/alerts").status_code == 401
    r = env.client.get("/v1/alerts")
    assert r.headers["content-type"].startswith("application/problem+json")


def test_edge_alert_lifecycle(env: Env) -> None:
    a = env.alert()
    r = env.post_alert(a)
    assert r.status_code == 202 and r.json() == {"alert_id": str(a.alert_id), "status": "queued"}
    assert env.post_alert(a).status_code == 200  # idempotent: same alert, no duplicate

    guard = env.login("akram")
    items = env.client.get("/v1/alerts", headers=guard).json()["items"]
    assert len(items) == 1 and items[0]["status"] == "open" and items[0]["severity"] == "high"
    d = env.client.get(f"/v1/alerts/{a.alert_id}", headers=guard).json()
    assert d["explanation_ur"].startswith("گیٹ کیمرہ 1 پر")
    assert d["signature_valid"] is True and d["p_value_text_en"].startswith("A pattern like this")
    kinds = [e["kind"] for e in d["events"]]
    assert kinds[:3] == ["ingested", "opened", "notified"]

    r = env.client.post(f"/v1/alerts/{a.alert_id}/ack", json={"note": "dekh liya"}, headers=guard)
    assert r.status_code == 200 and r.json()["status"] == "acked"
    r = env.client.post(f"/v1/alerts/{a.alert_id}/review", json={"verdict": "false"}, headers=guard)
    assert r.json()["status"] == "false_alarm"
    assert env.client.post(f"/v1/alerts/{a.alert_id}/ack", json={}, headers=guard).status_code == 409

    stats = env.client.get("/v1/stats", headers=env.login("sana")).json()
    assert stats["false_alarms"] == 1 and stats["false_alarm_rate"] == 1.0 and stats["mtta_median_s"] is not None


def test_signatures_are_enforced(env: Env) -> None:
    a = env.alert()
    forged = a.model_copy(update={"raw_score": 0.99})  # changed after signing
    r = env.post_alert(forged)
    assert r.status_code == 422 and r.json()["title"] == "Invalid signature"
    bad_cam = env.alert(camera_id="cam-unknown")
    assert env.post_alert(bad_cam).status_code == 422
    assert env.client.post("/v1/edge/alerts", json={}, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_rbac_and_site_isolation(env: Env) -> None:
    a = env.alert()
    env.post_alert(a)
    guard = env.login("akram")
    assert (
        env.client.post("/v1/search", json={"site_id": env.site_id, "query": "kaali bike"}, headers=guard).status_code
        == 403
    )
    police = env.login("police")
    assert env.client.get("/v1/alerts", headers=police).status_code == 403
    # a guard restricted to another site cannot see this site's alert (404, not 403)
    with env.app.state.ctx.db.session() as db:
        other = Site(
            id="other-site", tenant_id=db.query(User).filter_by(username="akram").one().tenant_id, name="Other"
        )
        db.add(other)
        db.query(User).filter_by(username="akram").one().site_ids = ["other-site"]
    assert env.client.get(f"/v1/alerts/{a.alert_id}", headers=env.login("akram")).status_code == 404


def test_cookie_writes_need_client_header(env: Env) -> None:
    r = env.client.post("/v1/auth/login", json={"username": "akram", "password": "wrong"})
    assert r.status_code == 401
    from .conftest import PASSWORD

    env.client.post("/v1/auth/login", json={"username": "akram", "password": PASSWORD})  # sets the cookie
    a = env.alert()
    env.post_alert(a)
    assert env.client.post(f"/v1/alerts/{a.alert_id}/ack", json={}).status_code == 403
    assert (
        env.client.post(f"/v1/alerts/{a.alert_id}/ack", json={}, headers={"X-Jikimi-Client": "web"}).status_code == 200
    )


def test_verify_route_without_vlm_opens_unverified_and_supersede(env: Env) -> None:
    first = env.alert(route=Route.VERIFY, p_value=0.03)
    env.post_alert(first)
    sana = env.login("sana")
    d = env.client.get(f"/v1/alerts/{first.alert_id}", headers=sana).json()
    assert d["status"] == "open" and d["verified"] is None
    assert "verify_skipped" in [e["kind"] for e in d["events"]]
    upgrade = env.alert(route=Route.ALERT_NOW, supersedes=first.alert_id)
    env.post_alert(upgrade)
    old = env.client.get(f"/v1/alerts/{first.alert_id}", headers=sana).json()
    assert old["status"] == "resolved" and "superseded" in [e["kind"] for e in old["events"]]
    listed = [i["id"] for i in env.client.get("/v1/alerts", headers=sana).json()["items"]]
    assert listed == [str(upgrade.alert_id)]


def test_escalation_chain_and_sms_ack(env: Env) -> None:
    a = env.alert()
    env.post_alert(a, sms=True)
    ctx = env.app.state.ctx
    workers = Workers(ctx)
    with ctx.db.session() as db:
        opened = db.get(Alert, a.alert_id).opened_at
    workers.tick(opened + timedelta(seconds=61))
    workers.tick(opened + timedelta(seconds=121))
    d = env.client.get(f"/v1/alerts/{a.alert_id}", headers=env.login("sana")).json()
    assert d["status"] == "escalated" and d["escalation_step"] == 2 and d["sms_sent"] is True
    escalations = [e for e in d["events"] if e["kind"] == "escalated"]
    assert {e["payload"]["roles"][0] for e in escalations} == {"guard", "supervisor"}
    # guard replied "1 <code>" by SMS while offline; the edge syncs the ack later
    r = env.client.post(
        "/v1/edge/acks",
        json={
            "alert_id": str(a.alert_id),
            "action": "ack",
            "actor": "+923001234567",
            "channel": "sms",
            "at": datetime.now(UTC).isoformat(),
        },
        headers=env.edge,
    )
    assert r.json() == {"result": "applied"}
    d = env.client.get(f"/v1/alerts/{a.alert_id}", headers=env.login("sana")).json()
    assert d["status"] == "acked" and d["acked_by"] == "sms:+923001234567"


def test_offline_sms_ack_keeps_real_times(env: Env) -> None:
    # internet down: SMS at t-100 s, guard replied "1 CODE" at t-20 s, everything synced at t
    now = datetime.now(UTC)
    a = env.alert(ts_start=now - timedelta(seconds=150), ts_end=now - timedelta(seconds=105))
    env.post_alert(a, sms_at=now - timedelta(seconds=100))
    ack = {"alert_id": str(a.alert_id), "action": "ack", "actor": "+923001234567", "channel": "sms"}
    r = env.client.post(
        "/v1/edge/acks", json={**ack, "at": (now - timedelta(seconds=20)).isoformat()}, headers=env.edge
    )
    assert r.json() == {"result": "applied"}
    d = env.client.get(f"/v1/alerts/{a.alert_id}", headers=env.login("sana")).json()
    acked = next(e for e in d["events"] if e["kind"] == "acked")
    assert 79 <= acked["payload"]["mtta_s"] <= 81  # from the SMS, not from the late server "opened"
    kinds = [e["kind"] for e in d["events"]]
    assert kinds.index("sms_sent") < kinds.index("acked") < kinds.index("ingested")


def test_sos_creates_open_high_alert(env: Env) -> None:
    guard = env.login("akram")
    r = env.client.post("/v1/sos", json={"site_id": env.site_id, "note": "madad"}, headers=guard)
    assert r.status_code == 201 and r.json()["type"] == "sos" and r.json()["status"] == "open"
    assert r.json()["explanation_roman"].startswith("Jikimi Homes")


def test_search_finds_alert_by_roman_urdu(env: Env) -> None:
    a = env.alert()
    env.post_alert(a)
    sana = env.login("sana")
    r = env.client.post(
        "/v1/search", json={"site_id": env.site_id, "query": "kaali bike 2 sawar gate pe"}, headers=sana
    )
    body = r.json()
    assert r.status_code == 200 and body["parsed"]["parser_path"] == "lexicon"
    assert body["results"][0]["alert_id"] == str(a.alert_id)
    assert "color:black" in body["results"][0]["matched"] and "riders:2" in body["results"][0]["matched"]
    miss = env.client.post("/v1/search", json={"site_id": env.site_id, "query": "laal gaari"}, headers=sana).json()
    assert miss["results"] == []


def test_evidence_pack_verify_and_tamper(env: Env) -> None:
    a = env.alert()
    env.post_alert(a)
    r = env.post_clip(a.alert_id)
    assert r.status_code == 201, r.text
    sana = env.login("sana")
    ev = env.client.post(
        "/v1/evidence", json={"alert_ids": [str(a.alert_id)], "case_reference": "FIR 123/2026"}, headers=sana
    )
    assert ev.status_code == 201, ev.text
    ev_id = ev.json()["id"]
    assert ev_id.startswith("EV-") and ev.json()["merkle_status"] == "pending"

    report = env.client.get(f"/v1/verify/{ev_id}").json()  # public, no login
    statuses = {c["name"]: c["status"] for c in report["checks"]}
    assert report["verified"] is True
    assert statuses == {
        "manifest_hash": "pass",
        "server_signature": "pass",
        "edge_signatures": "pass",
        "clip_files": "pass",
        "pdf": "pass",
        "merkle_proof": "pending",
        "timestamp": "pending",
    }

    pdf = env.client.get(f"/v1/evidence/{ev_id}/pdf", headers=sana)
    assert pdf.content.startswith(b"%PDF")
    from hashlib import sha256

    good = sha256(pdf.content).hexdigest()
    assert env.client.get(f"/v1/verify/{ev_id}/match", params={"sha256": good}).json()["matched"] is True
    tampered = bytearray(pdf.content)
    tampered[len(tampered) // 2] ^= 0x01  # flip one bit
    bad = sha256(bytes(tampered)).hexdigest()
    assert env.client.get(f"/v1/verify/{ev_id}/match", params={"sha256": bad}).json()["matched"] is False

    admin = env.login("admin")
    closed = env.client.post("/v1/admin/merkle/close", headers={**admin}).json()
    assert closed["closed"] is True and closed["size"] == 1
    report = env.client.get(f"/v1/verify/{ev_id}").json()
    assert {c["name"]: c["status"] for c in report["checks"]}["merkle_proof"] == "pass"

    # tamper with the stored clip on disk -> verification fails
    ctx = env.app.state.ctx
    with ctx.db.session() as db:
        clip_path = ctx.store.path(db.get(Alert, a.alert_id).clip_uri)
    data = bytearray(clip_path.read_bytes())
    data[10] ^= 0xFF
    clip_path.write_bytes(bytes(data))
    report = env.client.get(f"/v1/verify/{ev_id}").json()
    assert report["verified"] is False
    assert {c["name"]: c["status"] for c in report["checks"]}["clip_files"] == "fail"

    custody = env.client.get(f"/v1/evidence/{ev_id}", headers=sana).json()["custody"]
    assert [c["action"] for c in custody][:2] == ["evidence.create", "evidence.download"]
    assert env.client.get("/v1/audit/verify", headers=admin).json()["ok"] is True


def test_evidence_stays_verifiable_after_server_key_rotation(env: Env) -> None:
    from jikimi_crypto import Signer, generate_private_key

    a = env.alert()
    env.post_alert(a)
    env.post_clip(a.alert_id)
    ev_id = env.client.post("/v1/evidence", json={"alert_ids": [str(a.alert_id)]}, headers=env.login("sana")).json()[
        "id"
    ]
    service = env.app.state.ctx.evidence
    old = service.signer

    def server_signature() -> str:
        checks = env.client.get(f"/v1/verify/{ev_id}").json()["checks"]
        return next(c["status"] for c in checks if c["name"] == "server_signature")

    service.signer = Signer.from_key(generate_private_key(), prefix="server")  # rotated, old key forgotten
    assert server_signature() == "fail"
    service.retired_keys = {old.key_id: old.public_key}  # `python -m jikimi_server retire-key` keeps this
    assert server_signature() == "pass"


def test_qr_redirect_and_unknown_evidence(env: Env) -> None:
    r = env.client.get("/verify/EV-2026-10-22-0007", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/verify/?id=EV-2026-10-22-0007"
    assert env.client.get("/v1/verify/EV-2026-10-22-0007").status_code == 404
    assert env.client.get("/v1/verify/not-an-id").status_code == 404


def test_websocket_receives_new_alerts(env: Env) -> None:
    token = env.login("sana")["Authorization"].split()[1]
    with env.client.websocket_connect(f"/v1/ws?token={token}") as ws:
        assert ws.receive_json()["event"] == "hello"
        a = env.alert(type_=AlertType.SNATCH)
        env.post_alert(a)
        msg = ws.receive_json()  # supervisors get alert.created; the step-0 sound goes to guards
        assert msg["event"] == "alert.created" and msg["data"]["alert"]["id"] == str(a.alert_id)
    guard_token = env.login("akram")["Authorization"].split()[1]
    with env.client.websocket_connect(f"/v1/ws?token={guard_token}") as ws:
        ws.receive_json()
        env.post_alert(env.alert(type_=AlertType.SNATCH))
        first = ws.receive_json()
        assert first["event"] == "alert.notify" and first["data"]["sound"] is True


def test_retire_key_command_keeps_the_public_key(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from jikimi_crypto import Signer
    from jikimi_server.__main__ import main
    from jikimi_server.evidence.service import load_retired_keys

    keys = tmp_path / "keys"
    old = Signer.from_file(keys / "evidence.key", prefix="server")
    monkeypatch.setenv("JIKIMI_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # main() loads ./.env: keep the repo's out of this test
    assert main(["retire-key"]) == 0
    assert not (keys / "evidence.key").exists()  # out of service; the operator moves it offline
    assert len(list(keys.glob("evidence.key.retired-*"))) == 1
    assert load_retired_keys(keys / "retired") == {old.key_id: old.public_key}
    assert main(["retire-key"]) == 1  # nothing left to retire
