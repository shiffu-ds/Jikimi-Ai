"""Cascade router (F5) and the per-entity alert gate.

``ALERT_NOW``  p <= alpha_alert   -> guard right away (VLM may still verify in background)
``VERIFY``     p <= alpha_verify  -> server VLM first; unverified alert after a timeout
``LOG_ONLY``   otherwise          -> stored for search/statistics, never notified

Deterministic checks (camera tamper, SOS, admin-approved rules) bypass calibration: they are
explicit conditions, not learned scores.
"""

from __future__ import annotations

from dataclasses import dataclass

from jikimi_contracts import AlertCandidate, AlertType, Route, Severity

DETERMINISTIC_TYPES = frozenset({AlertType.TAMPER, AlertType.SOS, AlertType.RULE, AlertType.NETWORK})


@dataclass(frozen=True)
class RoutingConfig:
    alpha_alert: float = 0.01
    alpha_verify: float = 0.05
    uncalibrated_alert: float = 0.8
    uncalibrated_verify: float = 0.55
    log_only_max_p: float = 0.25
    """LOG_ONLY candidates above this p-value are too ordinary to even store."""
    cooldown_s: float = 900.0


def route(alert_type: AlertType, raw_score: float, p_value: float | None, cfg: RoutingConfig) -> Route:
    if alert_type in DETERMINISTIC_TYPES:
        return Route.ALERT_NOW
    if p_value is None:
        if raw_score >= cfg.uncalibrated_alert:
            return Route.ALERT_NOW
        if raw_score >= cfg.uncalibrated_verify:
            return Route.VERIFY
        return Route.LOG_ONLY
    if p_value <= cfg.alpha_alert:
        return Route.ALERT_NOW
    if p_value <= cfg.alpha_verify:
        return Route.VERIFY
    return Route.LOG_ONLY


def severity_for(alert_type: AlertType, r: Route, rule_severity: str | None = None) -> Severity:
    """``rule_severity``: a rule's own severity, or a camera-health notice's (``view_accepted``
    is low: an admin should look at the zones, nobody needs to run)."""
    if alert_type == AlertType.TAMPER and rule_severity:
        return Severity(rule_severity)
    if alert_type in (AlertType.TAMPER, AlertType.SOS):
        return Severity.HIGH
    if alert_type == AlertType.RULE:
        return Severity(rule_severity) if rule_severity else Severity.MEDIUM
    if alert_type == AlertType.NETWORK:  # watch and report, nobody runs after anyone
        return Severity.MEDIUM
    return {Route.ALERT_NOW: Severity.HIGH, Route.VERIFY: Severity.MEDIUM, Route.LOG_ONLY: Severity.LOW}[r]


@dataclass
class _Sent:
    alert: AlertCandidate
    ts: float


class AlertGate:
    """One alert per entity per cooldown; a *better* route upgrades (and supersedes) it."""

    def __init__(self, cooldown_s: float = 900.0) -> None:
        self.cooldown_s = cooldown_s
        self._sent: dict[tuple[str, str, str], _Sent] = {}

    @staticmethod
    def key(alert: AlertCandidate) -> tuple[str, str, str]:
        ident = alert.entity_id or str(alert.features.get("dedupe_key") or alert.track_ids or alert.alert_id)
        cam = "xcam" if alert.features.get("cross_camera") else alert.camera_id  # one route, one alert
        return (cam, alert.type.value, ident)

    def admit(self, alert: AlertCandidate, ts: float) -> AlertCandidate | None:
        """Returns the alert to send (``supersedes`` filled for upgrades) or ``None``."""
        assert alert.route is not None
        k = self.key(alert)
        prev = self._sent.get(k)
        if prev is not None and ts - prev.ts <= self.cooldown_s:
            assert prev.alert.route is not None
            if alert.route.rank <= prev.alert.route.rank:
                return None
            alert = alert.model_copy(update={"supersedes": prev.alert.alert_id})
        self._sent[k] = _Sent(alert, ts)
        self._expire(ts)
        return alert

    def _expire(self, ts: float) -> None:
        if len(self._sent) < 512:
            return
        for k in [k for k, v in self._sent.items() if ts - v.ts > self.cooldown_s]:
            del self._sent[k]
