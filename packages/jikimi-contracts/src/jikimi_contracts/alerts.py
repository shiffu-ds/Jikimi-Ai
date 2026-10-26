"""Alert contracts shared by edge, server and dashboard (plan Sections 7.11, 8.1, 11.4).

Changes vs. plan v2.3 (see docs/PLAN_REVIEW.md):
- ``severity``, ``trace_id``, ``schema_version`` and ``mode`` are part of the contract (they were
  used by the API example and outbox but missing from ``AlertCandidate``).
- The clip hash is *not* part of the alert signature. A clip needs ~10 s of post-roll, while the
  alert must reach the guard in < 5 s, so the clip gets its own signed ``ClipAttestation``.
- ``AlertStatus`` mirrors the state machine exactly.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from .version import SCHEMA_VERSION


class AlertType(StrEnum):
    SNATCH = "snatch"
    LOITERING = "loitering"
    RULE = "rule"
    TAMPER = "camera_tamper"
    AUDIO = "audio_event"
    SOS = "sos"
    NETWORK = "network_match"
    """F21: a bike like the one in a neighbour's confirmed incident was seen here."""
    PERSON_DANGER = "person_in_danger"
    """Someone may be in danger (``features.pattern``: following, surrounded, struggle, dragged,
    forced_into_vehicle, fall). Behaviour only: nobody's gender, age or identity is estimated."""
    VEHICLE_THEFT = "vehicle_theft"
    """A parked two-wheeler was worked on for a long time, then taken away."""
    CROWD_PANIC = "crowd_panic"
    """Many people suddenly ran away from one place at once."""


DANGER_PATTERNS: tuple[str, ...] = ("following", "surrounded", "struggle", "dragged", "forced_into_vehicle", "fall")
"""``features.pattern`` values of ``person_in_danger`` alerts (each has its own calibration set)."""
URGENT_PATTERNS: frozenset[str] = frozenset({"struggle", "dragged", "forced_into_vehicle", "fall"})
"""Patterns where someone is being hurt or taken right now: high severity once past LOG_ONLY."""


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2}[self.value]


class Route(StrEnum):
    """Cascade routing decision (Section 8.4)."""

    ALERT_NOW = "ALERT_NOW"
    VERIFY = "VERIFY"
    LOG_ONLY = "LOG_ONLY"

    @property
    def rank(self) -> int:
        return {"LOG_ONLY": 0, "VERIFY": 1, "ALERT_NOW": 2}[self.value]


class AlertStatus(StrEnum):
    """Server-side lifecycle; identical to the state machine in Section 7.11."""

    LOGGED_ONLY = "logged_only"
    VERIFYING = "verifying"
    OPEN = "open"
    ESCALATED = "escalated"
    ACKED = "acked"
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"
    UNCLEAR = "unclear"


ACTIVE_STATUSES: frozenset[AlertStatus] = frozenset(
    {AlertStatus.VERIFYING, AlertStatus.OPEN, AlertStatus.ESCALATED, AlertStatus.ACKED}
)
TERMINAL_STATUSES: frozenset[AlertStatus] = frozenset(
    {AlertStatus.RESOLVED, AlertStatus.FALSE_ALARM, AlertStatus.UNCLEAR, AlertStatus.LOGGED_ONLY}
)


class ReviewVerdict(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNCLEAR = "unclear"


class ObjectSummary(BaseModel):
    """Searchable attributes of an object involved in an alert or track (feeds F1 search)."""

    type: str
    color: str | None = None
    riders: int | None = None
    helmet: bool | None = None
    count: int = 1


class AlertCandidate(BaseModel):
    """What the edge produces for every suspicious pattern, and what the server ingests."""

    schema_version: str = SCHEMA_VERSION
    alert_id: UUID
    site_id: str
    camera_id: str
    type: AlertType
    severity: Severity = Severity.MEDIUM
    ts_start: AwareDatetime
    ts_end: AwareDatetime
    raw_score: float
    p_value: float | None = None
    route: Route | None = None
    mode: str = "normal"
    zone_id: str | None = None
    track_ids: list[int] = Field(default_factory=list)
    entity_id: str | None = None
    supersedes: UUID | None = None
    """Earlier alert for the same entity that this one upgrades (LOG_ONLY -> VERIFY -> ALERT_NOW)."""
    objects: list[ObjectSummary] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    explanation_roman: str | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)
    device_key_id: str | None = None
    signature: str | None = None
    trace_id: str | None = None

    def signing_payload(self) -> dict[str, Any]:
        """The exact dict whose canonical-JSON SHA-256 the edge signs (signature excluded)."""
        return self.model_dump(mode="json", exclude={"signature"})


class KeyframeRef(BaseModel):
    name: str
    sha256: str
    ts: AwareDatetime | None = None


class ClipAttestation(BaseModel):
    """Signed statement about a finished alert clip (sent after the post-roll completes)."""

    schema_version: str = SCHEMA_VERSION
    alert_id: UUID
    clip_id: str
    site_id: str
    camera_id: str
    ts_start: AwareDatetime
    ts_end: AwareDatetime
    clip_sha256: str
    original_sha256: str | None = None
    keyframes: list[KeyframeRef] = Field(default_factory=list)
    frames: int = 0
    fps: float = 0.0
    blur: dict[str, Any] = Field(default_factory=dict)
    device_key_id: str | None = None
    signature: str | None = None

    def signing_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"signature"})


class DeliveryInfo(BaseModel):
    """Transport metadata added by the edge outbox (not signed: it changes after signing)."""

    attempts: int = 0
    queued_at: AwareDatetime | None = None
    sms_sent_at: AwareDatetime | None = None
    sms_recipients: int = 0


class EdgeAlertEnvelope(BaseModel):
    """Body of ``POST /v1/edge/alerts``."""

    alert: AlertCandidate
    delivery: DeliveryInfo = Field(default_factory=DeliveryInfo)


class TrackSummary(BaseModel):
    """Metadata-only record of one finished track (activity-gated indexing, ADR-015).

    Carries a small *blurred* thumbnail; never raw video, never a face crop template.
    """

    schema_version: str = SCHEMA_VERSION
    site_id: str
    camera_id: str
    entity_id: str
    track_ids: list[int] = Field(default_factory=list)
    object: ObjectSummary
    zones: list[str] = Field(default_factory=list)
    ts_start: AwareDatetime
    ts_end: AwareDatetime
    passes: int = 0
    thumbnail_jpeg_b64: str | None = None
