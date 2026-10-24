"""Investigation agent (F1 Tier 2): 50 scripted tasks, success rate and tool calls (plan 8.6).

    uv run python -m eval.agent_check

An in-process server with the demo site gets three nights of synthetic bike sightings on the
gate and street cameras (colours, rider counts, re-entries; every bike has a known identity) and
a few loitering alerts. Fifty scripted tasks of five kinds then talk to ``/v1/agent`` exactly as
the dashboard does, passing the context back between turns:

* find   - "kal raat kaali bike 2 sawar": every cited clip matches, the expected bike is cited
* follow - find, then "ye bike aur kahan dekhi gayi?": the bike's sighting on the other camera
* clip   - find, then "doosra clip dikhao": exactly the clip it points at
* count  - "kal raat kitni laal bike": the right number
* report - find on an alert, then "report banao": the alert is in the draft, nothing exported

A task passes only with valid citations (clips of this site) and at most 8 tool calls. The tasks
are written for this agent: they test its plumbing and guardrails, not open questions.
"""

from __future__ import annotations

import argparse
import json
import random
import secrets
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PK = ZoneInfo("Asia/Karachi")
COLORS = {"black": "kaali", "red": "laal", "white": "safed", "blue": "neeli"}


def build(tmp: Path) -> tuple[Any, dict[str, str], dict[str, str], Any]:
    from fastapi.testclient import TestClient
    from jikimi_crypto import Signer, generate_private_key
    from jikimi_server.db.session import Database
    from jikimi_server.main import create_app
    from jikimi_server.seed import seed_site
    from jikimi_server.settings import ServerSettings

    password = "eval-" + secrets.token_urlsafe(10)
    settings = ServerSettings(
        database_url=f"sqlite:///{tmp / 'db.sqlite'}",
        data_dir=tmp / "server",
        jwt_secret=secrets.token_urlsafe(40),
        public_base_url="http://testserver",
        dashboard_dir=tmp / "none",
        workers_inprocess=False,
    )
    device = Signer.from_key(generate_private_key(), prefix="edge")
    db = Database(settings.database_url)
    db.create_all()
    seed_site(db, ROOT / "edge/config/site.demo.yaml", password, device.public_key, device.key_id, tmp / "token")
    client = TestClient(create_app(settings))
    client.__enter__()
    edge = {"Authorization": f"Bearer {(tmp / 'token').read_text()}"}
    r = client.post("/v1/auth/login", json={"username": "sana", "password": password})
    user = {"Authorization": f"Bearer {r.json()['token']}"}
    return client, edge, user, device


def sightings(rng: random.Random) -> list[dict[str, Any]]:
    """Three nights; each bike passes the gate, often the street 1-4 minutes later, sometimes back."""
    out = []
    today = datetime.now(PK).replace(hour=0, minute=0, second=0, microsecond=0)
    bike = 0
    for night in (1, 2, 3):
        base = today - timedelta(days=night) + timedelta(hours=21)
        for _ in range(12):
            bike += 1
            color = rng.choice(list(COLORS))
            riders = rng.choice([1, 1, 2])
            t = base + timedelta(minutes=rng.uniform(0, 140))  # 21:00-23:20, still "that night"
            out.append(
                {
                    "bike": bike,
                    "cam": "cam-gate-01",
                    "entity": f"cam-gate-01:mot:{bike}",
                    "t": t,
                    "color": color,
                    "riders": riders,
                }
            )
            if rng.random() < 0.6:
                out.append(
                    {
                        "bike": bike,
                        "cam": "cam-street-02",
                        "entity": f"cam-street-02:mot:{bike}",
                        "t": t + timedelta(minutes=rng.uniform(1, 4)),
                        "color": color,
                        "riders": riders,
                    }
                )
            if rng.random() < 0.25:
                out.append(
                    {
                        "bike": bike,
                        "cam": "cam-gate-01",
                        "entity": f"cam-gate-01:mot:{bike}",
                        "t": t + timedelta(minutes=rng.uniform(6, 12)),
                        "color": color,
                        "riders": riders,
                    }
                )
    return out


def main() -> None:
    from jikimi_common.ids import uuid7
    from jikimi_contracts import (
        AlertCandidate,
        AlertType,
        EdgeAlertEnvelope,
        ObjectSummary,
        Route,
        Severity,
        TrackSummary,
    )

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", default="eval/reports/agent_check.json")
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    with tempfile.TemporaryDirectory() as td:
        client, edge, user, device = build(Path(td))
        rows = sightings(rng)
        entity_of: dict[str, str] = {}
        for i, s in enumerate(rows):
            t = TrackSummary(
                site_id="society-gate-north",
                camera_id=s["cam"],
                entity_id=s["entity"],
                track_ids=[i + 1],
                object=ObjectSummary(type="motorcycle", color=s["color"], riders=s["riders"]),
                zones=["gate-2"] if s["cam"] == "cam-gate-01" else ["market-front"],
                ts_start=s["t"].astimezone(UTC),
                ts_end=s["t"].astimezone(UTC) + timedelta(seconds=20),
            )
            assert client.post("/v1/edge/tracks", json=t.model_dump(mode="json"), headers=edge).status_code == 201
            entity_of[f"track:{s['cam']}:{i + 1}:{int(t.ts_start.timestamp())}"] = s["entity"]
        alerts = []
        for s in [r for r in rows if r["cam"] == "cam-gate-01"][:5]:
            a = AlertCandidate(
                alert_id=uuid7(),
                site_id="society-gate-north",
                camera_id="cam-gate-01",
                type=AlertType.LOITERING,
                severity=Severity.HIGH,
                route=Route.ALERT_NOW,
                ts_start=s["t"].astimezone(UTC),
                ts_end=s["t"].astimezone(UTC) + timedelta(minutes=2),
                raw_score=0.9,
                p_value=0.004,
                zone_id="gate-2",
                entity_id=s["entity"],
                objects=[ObjectSummary(type="motorcycle", color=s["color"], riders=s["riders"])],
                features={
                    "passes": 3,
                    "window_min": 15,
                    "riders": s["riders"],
                    "vehicle": "motorcycle",
                    "color": s["color"],
                },
            )
            a = a.model_copy(update={"device_key_id": device.key_id})
            a = a.model_copy(update={"signature": device.sign(a.signing_payload())})
            env = EdgeAlertEnvelope(alert=a)
            client.post(
                "/v1/edge/alerts",
                json=env.model_dump(mode="json"),
                headers={**edge, "Idempotency-Key": str(a.alert_id)},
            )
            alerts.append((a, s))

        def ask(msg: str, ctx: dict[str, Any] | None) -> dict[str, Any]:
            r = client.post(
                "/v1/agent", json={"site_id": "society-gate-north", "message": msg, "context": ctx}, headers=user
            )
            assert r.status_code == 200, r.text
            return r.json()

        def ok_common(reply: dict[str, Any]) -> bool:
            return len(reply["tools"]) <= 8 and all(c["clip_id"] for c in reply["citations"])

        when = {1: "kal raat", 2: "parson raat"}
        results: dict[str, list[bool]] = {k: [] for k in ("find", "follow", "clip", "count", "report")}
        tools: list[int] = []
        groups = Counter(
            (s["color"], s["riders"], night) for s in rows if s["cam"] == "cam-gate-01" for night in [_night(s["t"])]
        )
        cases = [k for k in groups if k[2] in when]
        rng.shuffle(cases)
        for color, riders, night in cases[:15]:  # find
            msg = f"{when[night]} {COLORS[color]} bike {riders} sawar gate pe"
            rep = ask(msg, None)
            tools.append(len(rep["tools"]))
            want = {
                s["entity"]
                for s in rows
                if s["cam"] == "cam-gate-01"
                and _night(s["t"]) == night
                and s["color"] == color
                and s["riders"] == riders
            }
            cites = rep["citations"]
            top = cites[0] if cites else None
            top_ok = (  # the best match: a gate sighting (track or alert) of that colour and rider count
                top is not None
                and top["camera_id"] == "cam-gate-01"
                and top["objects"][0].get("color") == color
                and top["objects"][0].get("riders") == riders
            )
            hit = any(entity_of.get(c["clip_id"]) in want for c in cites)
            results["find"].append(ok_common(rep) and top_ok and hit and bool(want))
        for color, riders, night in cases[:10]:  # follow: the same bike on the street
            rep = ask(f"{when[night]} {COLORS[color]} bike {riders} sawar gate pe", None)
            ctx = {
                **rep["context"],
                "clip_ids": [c for c in rep["context"]["clip_ids"] if c.startswith("track:cam-gate-01")],
            }
            fol = ask("ye bike aur kahan dekhi gayi?", ctx)
            tools.append(len(fol["tools"]))
            first = next(
                (
                    r
                    for r in rows
                    if r["cam"] == "cam-gate-01"
                    and ctx["clip_ids"]
                    and ctx["clip_ids"][0].startswith(f"track:cam-gate-01:{rows.index(r) + 1}:")
                ),
                None,
            )
            street = [r for r in rows if first and r["bike"] == first["bike"] and r["cam"] == "cam-street-02"]
            cited_street = any(c["camera_id"] == "cam-street-02" for c in fol["citations"])
            results["follow"].append(
                ok_common(fol) and fol["intent"] == "trajectory" and (cited_street if street else True)
            )
        for color, _riders, night in cases[:10]:  # clip: the second one
            rep = ask(f"{when[night]} {COLORS[color]} bike gate pe", None)
            clip = ask("doosra clip dikhao", rep["context"])
            tools.append(len(clip["tools"]))
            want = rep["context"]["clip_ids"][1] if len(rep["context"]["clip_ids"]) > 1 else None
            results["clip"].append(
                ok_common(clip) and (want is None or [c["clip_id"] for c in clip["citations"]] == [want])
            )
        colours = list(COLORS)
        for k in range(10):  # count
            color, night = colours[k % 4], 1 + k % 2
            n = len(
                {
                    s["bike"]
                    for s in rows
                    if s["cam"] == "cam-gate-01" and _night(s["t"]) == night and s["color"] == color
                }
            )
            rep = ask(f"{when[night]} gate pe kitni {COLORS[color]} bike", None)
            tools.append(len(rep["tools"]))
            results["count"].append(ok_common(rep) and rep["intent"] == "count" and (rep["count"] or 0) == n)
        for a, s in alerts:  # report
            rep = ask(
                f"{when.get(_night(s['t']), 'pichle hafte')} {COLORS[s['color']]} bike {s['riders']} sawar gate pe loitering",
                None,
            )
            draft = ask("is ki report banao", rep["context"])
            tools.append(len(draft["tools"]))
            results["report"].append(
                ok_common(draft)
                and draft["intent"] == "report"
                and str(a.alert_id) in json.dumps(draft["citations"])
                and (draft["draft_report"] or "").startswith("DRAFT")
            )
        client.__exit__(None, None, None)
    total = [x for v in results.values() for x in v]
    report = {
        "tasks": len(total),
        "success": round(sum(total) / max(len(total), 1), 3),
        "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in results.items()},
        "mean_tool_calls": round(sum(tools) / max(len(tools), 1), 2),
        "max_tool_calls": max(tools, default=0),
        "sightings": len(rows),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def _night(t: datetime) -> int:
    today = datetime.now(PK).date()
    return (today - t.date()).days


if __name__ == "__main__":
    main()
