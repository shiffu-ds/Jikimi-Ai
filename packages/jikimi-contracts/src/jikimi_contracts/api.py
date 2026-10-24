"""Dashboard-facing REST models (plan Section 11.2 / 11.4).

These are exported to TypeScript (``apps/dashboard/src/lib/contracts.gen.ts``) by
``scripts/gen_contract_types.py`` so the web app never hand-writes API types.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from .alerts import ReviewVerdict


class Problem(BaseModel):
    """RFC 9457 ``application/problem+json``."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


Role = Literal["owner", "admin", "supervisor", "guard", "police_viewer"]


class UserInfo(BaseModel):
    id: UUID
    username: str
    name: str
    role: Role
    tenant_id: UUID
    site_ids: list[str] | None = None
    permissions: list[str] = Field(default_factory=list)


class ZoneInfo(BaseModel):
    id: str
    name: str | None = None
    name_ur: str | None = None
    polygon: list[tuple[float, float]] = Field(default_factory=list)


class CameraInfo(BaseModel):
    id: str
    site_id: str
    name: str
    name_ur: str | None = None
    name_roman: str | None = None
    zones: list[ZoneInfo] = Field(default_factory=list)
    status: str = "unknown"
    fps: float = 0.0
    last_seen: AwareDatetime | None = None
    health: dict[str, str] = Field(default_factory=dict)
    snapshot_url: str | None = None


class SiteInfo(BaseModel):
    id: str
    name: str
    name_ur: str | None = None
    timezone: str
    cameras: list[CameraInfo] = Field(default_factory=list)


class AlertSummary(BaseModel):
    id: UUID
    site_id: str
    camera_id: str
    camera_name: str | None = None
    camera_name_ur: str | None = None
    type: str
    severity: str
    route: str
    status: str
    mode: str = "normal"
    raw_score: float | None = None
    p_value: float | None = None
    explanation_ur: str | None = None
    explanation_en: str | None = None
    explanation_roman: str | None = None
    explanation_hi: str | None = None
    """The Urdu explanation in Devanagari, for phones with a Hindi voice and no Urdu one."""
    ts_start: AwareDatetime
    ts_end: AwareDatetime
    created_at: AwareDatetime
    opened_at: AwareDatetime | None = None
    acked_at: AwareDatetime | None = None
    acked_by: str | None = None
    has_clip: bool = False
    thumbnail_url: str | None = None
    verified: bool | None = None
    vlm_verdict: str | None = None
    vlm_confidence: float | None = None
    sms_sent: bool = False
    escalation_step: int = 0
    short_code: str


class AlertEventOut(BaseModel):
    kind: str
    actor: str | None = None
    channel: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    at: AwareDatetime


class ReviewOut(BaseModel):
    reviewer: str
    verdict: ReviewVerdict
    notes: str | None = None
    at: AwareDatetime


class AlertDetail(AlertSummary):
    features: dict[str, Any] = Field(default_factory=dict)
    objects: list[dict[str, Any]] = Field(default_factory=list)
    p_value_text_ur: str | None = None
    p_value_text_en: str | None = None
    clip_url: str | None = None
    keyframe_urls: list[str] = Field(default_factory=list)
    events: list[AlertEventOut] = Field(default_factory=list)
    reviews: list[ReviewOut] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    device_key_id: str | None = None
    signature_valid: bool = False
    clip_sha256: str | None = None
    zone_id: str | None = None
    track_ids: list[int] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class AlertPage(BaseModel):
    items: list[AlertSummary]
    next_cursor: str | None = None


class AckRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ReviewRequest(BaseModel):
    verdict: ReviewVerdict
    notes: str | None = Field(default=None, max_length=1000)


class EvidenceCreateRequest(BaseModel):
    alert_ids: list[UUID] = Field(min_length=1, max_length=20)
    case_reference: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


class EvidenceSummary(BaseModel):
    id: str
    site_id: str
    created_at: AwareDatetime
    created_by: str
    case_reference: str | None = None
    alert_count: int
    clip_count: int
    manifest_sha256: str
    pdf_sha256: str | None = None
    pdf_url: str | None = None
    verify_url: str
    merkle_status: str
    ots_status: str


class CustodyEvent(BaseModel):
    actor: str | None
    action: str
    at: AwareDatetime
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceDetail(EvidenceSummary):
    manifest: dict[str, Any]
    custody: list[CustodyEvent] = Field(default_factory=list)


class SosRequest(BaseModel):
    site_id: str
    camera_id: str | None = None
    note: str | None = Field(default=None, max_length=300)


class HotspotZone(BaseModel):
    zone_key: str
    camera_id: str
    zone_id: str | None = None
    name: str
    name_ur: str | None = None
    expected_events: float
    events_90d: int


class PatrolStop(BaseModel):
    zone_key: str
    name: str
    name_ur: str | None = None
    arrive_min: float


class Hotspots(BaseModel):
    """F15: where incidents are most likely in the next hours, and a patrol route through them.
    A risk estimate from this site's own past incidents (Hawkes process), not a crime prediction."""

    site_id: str
    window_hours: float
    zones: list[HotspotZone]
    patrol: list[PatrolStop]
    alpha: float
    decay_hours: float
    events_used: int
    days: float


class VoiceReply(BaseModel):
    """A guard's spoken reply, transcribed on the server (F12). Nothing is applied: the guard app
    shows the text and the intent, and the guard confirms with one tap. The audio is not kept."""

    text: str
    language: str | None = None
    intent: Literal["ack", "false_alarm", "need_help"] | None = None
    matched: str | None = None
    duration_s: float
    ms: int


class DeviceStatus(BaseModel):
    id: str
    site_id: str
    name: str
    status: str
    online: bool
    last_seen: AwareDatetime | None = None
    outbox_backlog: int = 0
    outbox_dead: int = 0
    power_source: str = "unknown"
    battery_pct: float | None = None
    power_profile: str = "normal"
    sms_gateway: str = "none"
    versions: dict[str, str] = Field(default_factory=dict)
    drift: dict[str, bool] = Field(default_factory=dict)


class HealthOverview(BaseModel):
    devices: list[DeviceStatus]
    cameras: list[CameraInfo]
    server_time: AwareDatetime


class CountByKey(BaseModel):
    key: str
    count: int


class StatsOut(BaseModel):
    site_id: str | None
    days: int
    open_alerts: int
    alerts_today: int
    alerts_total: int
    reviewed: int
    false_alarms: int
    false_alarm_rate: float | None
    mtta_median_s: float | None
    mtta_p95_s: float | None
    sms_fallbacks: int
    by_type: list[CountByKey]
    by_status: list[CountByKey]
    by_day: list[CountByKey]
    cameras_online: int
    cameras_total: int


class WsEvent(BaseModel):
    event: str
    site_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
