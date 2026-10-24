"""Stream messages (Redis Streams in compose mode, in-memory bus in lite mode) and edge health.

Event catalog: plan Section 7.12. Every message carries ``schema_version``; consumers are
idempotent on ``alert_id`` / ``evidence_id``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from .version import SCHEMA_VERSION


class StreamName(StrEnum):
    EDGE_ALERTS = "edge.alerts"
    VERIFY_REQ = "verify.req"
    VERIFY_RES = "verify.res"
    INDEX_JOBS = "index.jobs"
    NOTIFY_JOBS = "notify.jobs"
    EVIDENCE_JOBS = "evidence.jobs"
    REVIEWS = "reviews"


class _Msg(BaseModel):
    schema_version: str = SCHEMA_VERSION


class AlertCreated(_Msg):
    alert_id: UUID
    site_id: str
    status: str
    route: str | None = None


class VerifyRequest(_Msg):
    alert_id: UUID
    requested_at: AwareDatetime
    deadline_s: float = 20.0


class VerifyVerdict(StrEnum):
    SNATCH = "snatch"
    LOITERING = "loitering"
    NORMAL = "normal"
    UNCLEAR = "unclear"


class VerifyResult(_Msg):
    alert_id: UUID
    verdict: VerifyVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    explanation_en: str = ""
    samples: int = 1
    agreement: float = 1.0
    provider: str = "none"
    latency_ms: float = 0.0


class NotifyJob(_Msg):
    alert_id: UUID
    step: int = 0
    reason: str = "opened"


class IndexJob(_Msg):
    clip_index_id: int


class EvidenceJob(_Msg):
    evidence_id: str
    requested_by: str


class ReviewRecorded(_Msg):
    alert_id: UUID
    verdict: str
    reviewer: str
    at: AwareDatetime


class PowerSource(StrEnum):
    AC = "ac"
    BATTERY = "battery"
    UNKNOWN = "unknown"


class PowerState(BaseModel):
    source: PowerSource = PowerSource.UNKNOWN
    battery_pct: float | None = None
    profile: str = "normal"


class CameraHealth(BaseModel):
    camera_id: str
    online: bool
    fps: float = 0.0
    last_frame_at: AwareDatetime | None = None
    checks: dict[str, str] = Field(default_factory=dict)
    """check name -> ``ok`` | ``warn`` | ``alarm`` (blur, covered, moved, frozen, offline)."""


class EdgeHeartbeat(_Msg):
    device_id: str
    site_id: str
    ts: AwareDatetime
    uptime_s: float
    cameras: list[CameraHealth] = Field(default_factory=list)
    outbox_backlog: int = 0
    outbox_dead: int = 0
    sms_gateway: str = "none"
    sms_ok: bool | None = None
    online: bool = True
    power: PowerState = Field(default_factory=PowerState)
    versions: dict[str, str] = Field(default_factory=dict)
    drift: dict[str, bool] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class EdgeAck(_Msg):
    """An acknowledgement collected on the edge while offline (SMS reply), synced later."""

    alert_id: UUID
    action: str  # ack | false_alarm | need_help
    actor: str
    channel: str = "sms"
    at: AwareDatetime
