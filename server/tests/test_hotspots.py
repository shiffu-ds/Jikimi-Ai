from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jikimi_contracts import AlertType, Route

from .conftest import Env


def test_hotspots_rank_zones_by_recent_incidents_and_plan_a_patrol(env: Env) -> None:
    now = datetime.now(UTC)
    for i in range(4):  # a cluster of recent incidents at Gate 2, one old one on the street
        a = env.alert(
            AlertType.LOITERING,
            Route.ALERT_NOW,
            ts_start=now - timedelta(hours=i + 1, minutes=2),
            ts_end=now - timedelta(hours=i + 1),
        )
        assert env.post_alert(a).status_code in (200, 201, 202)
    old = env.alert(
        AlertType.SNATCH,
        Route.ALERT_NOW,
        camera_id="cam-street-02",
        zone_id="market-front",
        ts_start=now - timedelta(days=20, minutes=1),
        ts_end=now - timedelta(days=20),
    )
    assert env.post_alert(old).status_code in (200, 201, 202)
    url = f"/v1/sites/{env.site_id}/hotspots?hours=4"
    assert env.client.get(url, headers=env.login("akram")).status_code == 403  # guards do not see statistics
    h = env.client.get(url, headers=env.login("sana")).json()
    assert h["events_used"] == 5 and h["zones"][0]["zone_key"] == "cam-gate-01:gate-2"
    assert h["zones"][0]["expected_events"] > h["zones"][1]["expected_events"] > 0
    assert h["patrol"] and h["patrol"][0]["arrive_min"] >= 0 and all(s["arrive_min"] <= 30 for s in h["patrol"])
