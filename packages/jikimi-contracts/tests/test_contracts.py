from datetime import UTC, datetime
from uuid import uuid4

import pytest
from jikimi_contracts import AlertCandidate, AlertType, Pose, Route, Severity, exported_models
from jikimi_contracts.rules_dsl import Rule, rule_json_schema
from pydantic import ValidationError


def _alert(**kw: object) -> AlertCandidate:
    now = datetime(2026, 11, 21, 18, 38, tzinfo=UTC)
    base: dict[str, object] = dict(
        alert_id=uuid4(),
        site_id="society-gate-north",
        camera_id="cam-gate-01",
        type=AlertType.LOITERING,
        ts_start=now,
        ts_end=now,
        raw_score=0.81,
    )
    base.update(kw)
    return AlertCandidate.model_validate(base)


def test_signing_payload_excludes_signature() -> None:
    a = _alert(signature="abc")
    payload = a.signing_payload()
    assert "signature" not in payload
    assert payload["schema_version"] == "1.0"
    assert payload["type"] == "loitering"


def test_naive_datetimes_rejected() -> None:
    with pytest.raises(ValidationError):
        _alert(ts_start=datetime(2026, 1, 1))


def test_ranks() -> None:
    assert Severity.HIGH.rank > Severity.MEDIUM.rank > Severity.LOW.rank
    assert Route.ALERT_NOW.rank > Route.VERIFY.rank > Route.LOG_ONLY.rank


def test_pose_needs_17_keypoints() -> None:
    Pose(track_id=1, keypoints=[(0.5, 0.5, 0.9)] * 17)
    with pytest.raises(ValidationError):
        Pose(track_id=1, keypoints=[(0.5, 0.5, 0.9)] * 16)


def test_rule_dsl_example_from_plan() -> None:
    rule = Rule.model_validate(
        {
            "rule_id": "r-gate2-night-dwell",
            "name_ur": "Raat ko gate 2 par der tak rukna",
            "site_id": "society-gate-north",
            "when": {
                "schedule": {"days": ["mon", "tue"], "from": "23:00", "to": "05:00"},
                "camera_ids": ["cam-gate-01"],
                "zone": "gate-2",
                "object": {"type": "person"},
                "condition": {"dwell_seconds_gt": 300},
            },
            "then": {"alert": {"severity": "medium", "notify": ["guard", "supervisor"]}},
            "created_by": "admin@site",
        }
    )
    assert rule.when.schedule is not None and rule.when.schedule.from_ == "23:00"
    with pytest.raises(ValidationError):
        Rule.model_validate(
            {
                **rule.model_dump(by_alias=True),
                "when": {**rule.when.model_dump(by_alias=True), "condition": {"dwell_seconds_gt": 3}},
            }
        )
    assert "properties" in rule_json_schema()


def test_exported_models_are_stable() -> None:
    names = [m.__name__ for m in exported_models()]
    assert names == sorted(names)
    assert {"AlertDetail", "ParsedQuery", "VerificationReport", "EdgeHeartbeat"} <= set(names)
