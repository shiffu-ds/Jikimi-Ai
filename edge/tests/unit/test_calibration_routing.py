import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from jikimi_contracts import AlertCandidate, AlertType, Route, Severity
from jikimi_edge.calibration.conformal import SplitConformal
from jikimi_edge.calibration.drift import ks_2samp
from jikimi_edge.calibration.store import CalibrationStore
from jikimi_edge.routing.router import AlertGate, RoutingConfig, route, severity_for


class TestConformal:
    def test_p_value_formula(self) -> None:
        cal = SplitConformal([0.1, 0.2, 0.3, 0.4])
        assert cal.p_value(0.35) == pytest.approx((1 + 1) / 5)
        assert cal.p_value(0.05) == pytest.approx(1.0)
        assert cal.p_value(0.9) == pytest.approx(1 / 5) == cal.min_p

    def test_ties_are_conservative(self) -> None:
        cal = SplitConformal([0.5] * 9)
        assert cal.p_value(0.5) == pytest.approx(1.0)

    @pytest.mark.parametrize("alpha", [0.01, 0.05, 0.1])
    def test_false_alarm_rate_is_at_most_alpha(self, alpha: float) -> None:
        # exchangeable normal scores: the empirical false-alarm rate must stay <= alpha (+ noise)
        rng = random.Random(7)
        cal = SplitConformal(rng.gauss(0, 1) for _ in range(2000))
        test = [rng.gauss(0, 1) for _ in range(20000)]
        fa = sum(cal.p_value(s) <= alpha for s in test) / len(test)
        assert fa <= alpha * 1.15

    def test_threshold_matches_p_values(self) -> None:
        rng = random.Random(1)
        cal = SplitConformal(rng.random() for _ in range(999))
        thr = cal.threshold(0.01)
        assert cal.p_value(thr) <= 0.01
        assert cal.p_value(thr - 1e-3) > 0.01 or thr == float("inf")
        assert SplitConformal([1.0] * 10).threshold(0.01) == float("inf")  # n too small for alpha


def test_ks_drift() -> None:
    rng = random.Random(3)
    a = [rng.gauss(0, 1) for _ in range(800)]
    assert not ks_2samp(a, [rng.gauss(0, 1) for _ in range(800)]).drift
    shifted = ks_2samp(a, [rng.gauss(0.5, 1) for _ in range(800)])
    assert shifted.drift and shifted.p_value < 1e-6


def test_calibration_store_roundtrip(tmp_path) -> None:
    store = CalibrationStore(tmp_path, "site-a")
    assert store.p_value("loitering", "normal", 0.5) is None
    store.save("loitering", "normal", [0.1, 0.2, 0.3], source="test")
    assert store.p_value("loitering", "normal", 0.25) == pytest.approx(0.5)
    # event mode falls back to the normal set until it has its own
    assert store.p_value("loitering", "chand_raat", 0.25) == pytest.approx(0.5)


class TestRouting:
    cfg = RoutingConfig(alpha_alert=0.01, alpha_verify=0.05)

    @pytest.mark.parametrize(
        ("p", "expected"),
        [(0.005, Route.ALERT_NOW), (0.01, Route.ALERT_NOW), (0.03, Route.VERIFY), (0.2, Route.LOG_ONLY)],
    )
    def test_conformal_bands(self, p: float, expected: Route) -> None:
        assert route(AlertType.SNATCH, 0.5, p, self.cfg) == expected

    def test_deterministic_types_bypass_calibration(self) -> None:
        assert route(AlertType.TAMPER, 0.0, None, self.cfg) == Route.ALERT_NOW
        assert severity_for(AlertType.TAMPER, Route.ALERT_NOW) == Severity.HIGH
        assert severity_for(AlertType.RULE, Route.ALERT_NOW, "low") == Severity.LOW

    def test_uncalibrated_falls_back_to_raw_thresholds(self) -> None:
        assert route(AlertType.LOITERING, 0.9, None, self.cfg) == Route.ALERT_NOW
        assert route(AlertType.LOITERING, 0.6, None, self.cfg) == Route.VERIFY
        assert route(AlertType.LOITERING, 0.2, None, self.cfg) == Route.LOG_ONLY


def _alert(r: Route, entity: str = "cam:mot:1") -> AlertCandidate:
    now = datetime(2026, 10, 23, tzinfo=UTC)
    return AlertCandidate(
        alert_id=uuid4(),
        site_id="s",
        camera_id="cam",
        type=AlertType.LOITERING,
        ts_start=now,
        ts_end=now,
        raw_score=0.5,
        route=r,
        entity_id=entity,
    )


def test_gate_dedupes_and_upgrades() -> None:
    gate = AlertGate(cooldown_s=900)
    first = gate.admit(_alert(Route.VERIFY), 0.0)
    assert first is not None and first.supersedes is None
    assert gate.admit(_alert(Route.VERIFY), 10.0) is None  # same entity, same route
    up = gate.admit(_alert(Route.ALERT_NOW), 20.0)
    assert up is not None and up.supersedes == first.alert_id
    assert gate.admit(_alert(Route.LOG_ONLY), 30.0) is None
    assert gate.admit(_alert(Route.VERIFY, entity="cam:mot:2"), 30.0) is not None  # other bike
    assert gate.admit(_alert(Route.ALERT_NOW), 2000.0) is not None  # cooldown over


@pytest.mark.parametrize(("events", "bound"), [(0, 2.996), (1, 4.744), (2, 6.296)])
def test_fa_upper_bound_is_exact_poisson(events: int, bound: float) -> None:
    from jikimi_edge.__main__ import _poisson_upper

    assert _poisson_upper(events) == pytest.approx(bound, abs=1e-3)
