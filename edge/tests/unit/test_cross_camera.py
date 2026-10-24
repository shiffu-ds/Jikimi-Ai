from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from jikimi_contracts import AlertType
from jikimi_edge.analytics.cross_camera import CrossCameraLinker, Segment, TrajectoryScorer, turns_of
from jikimi_edge.tracking.track_store import TrackHistory

REPO = Path(__file__).resolve().parents[3]
MODEL = REPO / "models/trajectory_tf.onnx"
GRAPH = [{"from": "cam-gate-01", "to": "cam-street-02", "mean_s": 25, "std_s": 10}]
CAMS = ["cam-gate-01", "cam-street-02", "cam-back-03"]


def _desc(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).random(64).astype(np.float32)
    return v / np.linalg.norm(v)


def _seg(
    cam: str, start: float, dwell: float = 20.0, speed: float = 0.08, turns: int = 1, tod: float = 21.5
) -> Segment:
    return Segment(cam, start, start + dwell, speed, turns, tod)


def test_routes_are_linked_across_cameras_only_when_plausible() -> None:
    linker = CrossCameraLinker(GRAPH, threshold=0.9)
    bike, other = _desc(1), _desc(2)
    a = linker.add("cam-gate-01", _seg("cam-gate-01", 0), bike, riders=2)
    assert linker.add("cam-street-02", _seg("cam-street-02", 60), bike, riders=2) is a  # 40 s later, same look
    assert len(a.segments) == 2
    assert linker.add("cam-gate-01", _seg("cam-gate-01", 81), other, riders=2) is not a  # another bike
    assert linker.add("cam-gate-01", _seg("cam-gate-01", 82), bike, riders=1) is not a  # rider count changed
    fast = CrossCameraLinker(GRAPH, threshold=0.9)
    b = fast.add("cam-gate-01", _seg("cam-gate-01", 0, dwell=5), bike, riders=2)
    gap = {"from": "cam-gate-01", "to": "cam-street-02", "mean_s": 120, "std_s": 10}
    fast.travel[("cam-gate-01", "cam-street-02")] = (gap["mean_s"], gap["std_s"])
    assert fast.add("cam-street-02", _seg("cam-street-02", 10), bike, riders=2) is not b  # faster than the road allows


def test_turns_count_back_and_forth() -> None:
    assert turns_of([0.1, 0.2, 0.3, 0.4]) == 0
    assert turns_of([0.1, 0.3, 0.5, 0.3, 0.1, 0.3]) == 2
    assert turns_of([0.5, 0.505, 0.5, 0.505]) == 0  # jitter is not a u-turn


@pytest.mark.skipif(
    not MODEL.exists(), reason="trajectory model not trained (python -m jikimi_ml.train.train_trajectory)"
)
def test_a_scout_circling_two_cameras_scores_above_a_delivery() -> None:
    score = TrajectoryScorer(str(MODEL), CAMS)
    scout = [_seg(CAMS[k % 2], k * 150.0, dwell=25, speed=0.07, turns=2, tod=22.0) for k in range(4)]
    delivery = [
        _seg("cam-gate-01", 0, dwell=8, speed=0.2, turns=0, tod=13.0),
        _seg("cam-street-02", 35, dwell=180, speed=0.05, turns=1, tod=13.0),
        _seg("cam-gate-01", 245, dwell=8, speed=0.2, turns=0, tod=13.1),
    ]
    assert score(scout) > score(delivery) + 1.0


@pytest.mark.skipif(
    not MODEL.exists(), reason="trajectory model not trained (python -m jikimi_ml.train.train_trajectory)"
)
def test_pipeline_raises_one_cross_camera_alert_for_a_circling_bike(tmp_path: Path) -> None:
    from jikimi_edge.runner import build_pipeline
    from jikimi_edge.settings import load_settings

    s = dataclasses.replace(load_settings(REPO / "edge/config/site.demo.yaml", repo_root=REPO), data_dir=tmp_path)
    pipe, _, _ = build_pipeline(s, with_outbox=False, record_clips=False)
    assert pipe.xcam is not None
    desc = _desc(7)
    alerts = []
    t0 = 1_761_330_000.0  # 21:20 local
    for k in range(5):
        cam = ("cam-gate-01", "cam-street-02")[k % 2]
        h = TrackHistory(track_id=k + 1, cls="motorcycle", first_seen=t0 + k * 150, last_seen=t0 + k * 150 + 25)
        for i in range(26):
            h.points.append((t0 + k * 150 + i, 0.3 + 0.02 * (i % 10 if i < 10 else 20 - i), 0.6))
            h.speeds.append(0.06)
        h.desc, h.rider_counts = desc, [2, 2, 2]
        a = pipe._cross_camera_step(pipe.cameras[cam], h, h.last_seen + 1)
        if a is not None:
            alerts.append(a)
    assert len(alerts) == 1  # one route, one alert (later segments are not new alerts)
    a = alerts[0]
    assert a.type == AlertType.LOITERING and a.features["cross_camera"] and a.features["calibrated"]
    assert (
        a.p_value is not None and a.p_value <= 0.05 and set(a.features["cameras"]) == {"cam-gate-01", "cam-street-02"}
    )
    assert "cameras ke darmiyan" in (a.explanation_roman or "")
