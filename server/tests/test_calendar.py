from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from jikimi_contracts.modes import CalendarBundle, mode_on
from jikimi_crypto import verify_json
from jikimi_server.services.calendar import estimates

from .conftest import Env


def test_estimates_cover_the_pakistani_event_year() -> None:
    got = {(w.name, w.starts.isoformat(), w.ends.isoformat()) for w in estimates(date(2027, 1, 1), date(2027, 12, 31))}
    assert {
        ("Ramadan 1448", "2027-02-08", "2027-03-09"),
        ("Chand Raat 1448", "2027-03-09", "2027-03-09"),
        ("Eid ul Fitr 1448", "2027-03-10", "2027-03-12"),
        ("Eid ul Adha 1448", "2027-05-17", "2027-05-19"),
        ("Muharram 9-10, 1449", "2027-06-14", "2027-06-15"),
        ("14 August 2027", "2027-08-14", "2027-08-14"),
    } <= got
    windows = estimates(date(2027, 1, 1), date(2027, 12, 31))
    assert mode_on(windows, date(2027, 3, 9)) == "chand_raat"  # the shorter window wins inside Ramadan
    assert mode_on(windows, date(2027, 2, 20)) == "ramadan" and mode_on(windows, date(2027, 4, 1)) == "normal"


def test_admin_confirms_and_the_edge_gets_a_signed_calendar(env: Env) -> None:
    site = env.site_id
    url = f"/v1/sites/{site}/calendar"
    guard, sana, admin = env.login("akram"), env.login("sana"), env.login("admin")
    cal = env.client.get(url, headers=guard).json()
    assert cal["current_mode"] == "normal" and cal["windows"] == [] and cal["estimates"]
    assert env.client.get(url, headers=env.login("police")).status_code == 403

    chand = next(e for e in cal["estimates"] if e["mode"] == "chand_raat")
    sighted = date.fromisoformat(chand["starts"]) + timedelta(days=1)  # moon seen a day later
    body = {"name": chand["name"], "mode": "chand_raat", "starts": sighted.isoformat(), "ends": sighted.isoformat()}
    assert env.client.post(url, json=body, headers=sana).status_code == 403  # admins confirm
    r = env.client.post(url, json=body, headers=admin)
    assert r.status_code == 201 and r.json()["confirmed_by"] == "admin" and r.json()["source"] == "admin"
    cal = env.client.get(url, headers=guard).json()
    assert [w["starts"] for w in cal["windows"]] == [sighted.isoformat()]
    assert not any(e["mode"] == "chand_raat" and e["name"] == chand["name"] for e in cal["estimates"])

    today = datetime.now(ZoneInfo("Asia/Karachi")).date()
    market = {"name": "Itwaar bazaar", "mode": "bazaar_day", "starts": today.isoformat(), "ends": today.isoformat()}
    market_id = env.client.post(url, json=market, headers=admin).json()["id"]
    assert env.client.get(url, headers=guard).json()["current_mode"] == "bazaar_day"

    b1 = CalendarBundle.model_validate(env.client.get("/v1/edge/calendar", headers=env.edge).json())
    assert verify_json(b1.public_key, b1.signing_payload(), b1.signature)
    assert mode_on(b1.windows, sighted) == "chand_raat" and mode_on(b1.windows, today) == "bazaar_day"
    assert env.client.delete(f"{url}/{market_id}", headers=admin).status_code == 204
    b2 = env.client.get("/v1/edge/calendar", headers=env.edge).json()
    assert b2["version"] != b1.version and [w["mode"] for w in b2["windows"]] == ["chand_raat"]
    assert env.client.delete(f"{url}/{market_id}", headers=admin).status_code == 404
    actions = [e["action"] for e in env.client.get("/v1/audit", headers=admin).json()]
    assert actions.count("calendar.confirmed") == 2 and "calendar.removed" in actions


def test_mode_windows_are_validated(env: Env) -> None:
    url = f"/v1/sites/{env.site_id}/calendar"
    admin = env.login("admin")
    bad = [
        {"name": "x", "mode": "eid", "starts": "2027-03-12", "ends": "2027-03-10"},  # ends before starts
        {"name": "x", "mode": "normal", "starts": "2027-03-10", "ends": "2027-03-10"},  # normal is the default
        {"name": "x", "mode": "eid", "starts": "2027-01-01", "ends": "2027-03-01"},  # longer than 40 days
        {"name": "x", "mode": "wedding", "starts": "2027-03-10", "ends": "2027-03-10"},  # unknown mode
    ]
    for body in bad:
        assert env.client.post(url, json=body, headers=admin).status_code == 422, body
    assert env.client.get("/v1/sites/someone-elses-site/calendar", headers=admin).status_code == 404


def test_why_panel_names_the_mode_the_p_value_came_from(env: Env) -> None:
    feats = {"passes": 3, "window_min": 15, "riders": 2, "vehicle": "motorcycle", "calibration_mode": "chand_raat"}
    a = env.alert(mode="chand_raat", features=feats)
    assert env.post_alert(a).status_code == 202
    d = env.client.get(f"/v1/alerts/{a.alert_id}", headers=env.login("sana")).json()
    assert d["mode"] == "chand_raat"
    assert "چاند رات" in d["p_value_text_ur"] and "Chand Raat" in d["p_value_text_en"]


def test_rush_hint_from_edge_volume(env: Env) -> None:
    hb = {
        "device_id": "edge-demo-001",
        "site_id": env.site_id,
        "ts": datetime.now(ZoneInfo("UTC")).isoformat(),
        "uptime_s": 3600.0,
        "extra": {"volume": {"cam-gate-01": 2.4, "cam-street-02": 1.1}},
    }
    url = f"/v1/sites/{env.site_id}/calendar"
    assert env.client.get(url, headers=env.login("sana")).json()["rush_ratio"] is None
    assert env.client.post("/v1/edge/heartbeat", json=hb, headers=env.edge).status_code == 200
    assert env.client.get(url, headers=env.login("sana")).json()["rush_ratio"] == 2.4
