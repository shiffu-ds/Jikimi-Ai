from __future__ import annotations

import base64
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from jikimi_contracts import AlertType, Route, Severity
from jikimi_contracts.network import NetworkShare
from jikimi_edge.runner import build_pipeline
from jikimi_edge.settings import load_settings
from jikimi_edge.tracking.track_store import TrackHistory

REPO = Path(__file__).resolve().parents[3]


def _desc(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).random(64).astype(np.float32)
    return v / np.linalg.norm(v)


def _share(desc: np.ndarray, riders: int = 2, expires_in_h: float = 2.0) -> NetworkShare:
    now = datetime.now(UTC)
    return NetworkShare(
        id=f"s{riders}{expires_in_h}",
        alert_type="snatch",
        riders=riders,
        color="black",
        descriptor_b64=base64.b64encode(desc.astype(np.float16).tobytes()).decode(),
        seen_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(hours=expires_in_h),
        distance_km=0.7,
    )


def _bike(desc: np.ndarray, riders: int = 2) -> TrackHistory:
    t = datetime.now(UTC).timestamp()
    h = TrackHistory(track_id=41, cls="motorcycle", first_seen=t - 8, last_seen=t)
    h.desc, h.rider_counts = desc, [riders] * 3
    return h


def test_a_neighbours_bike_is_reported_once_to_this_guard_only(tmp_path: Path) -> None:
    s = dataclasses.replace(load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO), data_dir=tmp_path)
    pipe, outbox, _ = build_pipeline(s, with_outbox=True, record_clips=False)
    rt = pipe.cameras["cam-gate-01"]
    bike = _desc(5)
    pipe.set_network([_share(bike, expires_in_h=-0.1), _share(bike, riders=1), _share(bike)])
    now = datetime.now(UTC).timestamp()
    assert pipe._network_match(rt, _bike(_desc(6)), now) is None  # another bike
    a = pipe._network_match(rt, _bike(bike), now)
    assert (
        a is not None and a.type == AlertType.NETWORK and a.route == Route.ALERT_NOW and a.severity == Severity.MEDIUM
    )
    assert a.features["share_id"] == "s22.0" and "khud karwai na karein" in (a.explanation_roman or "")
    assert pipe._network_match(rt, _bike(bike), now + 5) is None  # one alert per shared incident
    assert outbox is not None
    kinds = [i.kind for i in outbox.due(now=1e12, limit=100)]
    assert kinds.count("alert") == 1 and "embedding" not in kinds  # a neighbour alert shares nothing onwards


def test_bike_alerts_send_their_embedding_outside_the_signed_alert(tmp_path: Path) -> None:
    s = dataclasses.replace(load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO), data_dir=tmp_path)
    pipe, outbox, _ = build_pipeline(s, with_outbox=True, record_clips=False)
    rt = pipe.cameras["cam-gate-01"]
    h = _bike(_desc(9))
    rt.store.histories[h.track_id] = h
    from jikimi_edge.analytics.base import FrameContext

    ctx = FrameContext(site_id=s.site_id, camera_id="cam-gate-01", ts=h.last_seen, frame=None)
    cand = ctx.make_alert(AlertType.SNATCH, 0.99, h.first_seen, track_ids=[h.track_id], features={"riders": 2})
    alert = pipe._finalize(rt, cand, h.last_seen)
    assert alert is not None and alert.route != Route.LOG_ONLY
    assert outbox is not None
    items = {i.kind: i for i in outbox.due(now=1e12, limit=100)}
    emb = items["embedding"].payload
    assert emb["alert_id"] == str(alert.alert_id) and emb["riders"] == 2
    assert "descriptor" not in str(items["alert"].payload)  # the year-long signed record stays free of it
