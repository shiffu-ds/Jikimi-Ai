"""SQLAlchemy models (plan Section 11.1, with the v2.4 fixes from docs/PLAN_REVIEW.md).

Runs on SQLite (lite profile: zero setup) and PostgreSQL 16 (compose profile). Fixes vs. v2.3:
- ``tenant_id`` on every tenant-scoped table (the RLS claim needs it)
- alert ``status`` values mirror the state machine
- signed edge payloads are stored verbatim, so evidence can be re-verified at any time
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from jikimi_common.ids import uuid7
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC everywhere; SQLite stores naive UTC and gets tzinfo back on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


JSONType = JSON().with_variant(JSONB(), "postgresql")


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this class attribute
        datetime: UTCDateTime(),
        dict[str, Any]: JSONType,
        list[Any]: JSONType,
        uuid.UUID: Uuid(),
    }


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now_utc)


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    name_ur: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Karachi")
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cameras: Mapped[list[Camera]] = relationship(back_populates="site", order_by="Camera.id")


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    name_ur: Mapped[str | None] = mapped_column(String(200))
    name_roman: Mapped[str | None] = mapped_column(String(200))
    zones: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(16), default="unknown")
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    health: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_seen: Mapped[datetime | None] = mapped_column()
    position: Mapped[dict[str, Any]] = mapped_column(default=dict)
    site: Mapped[Site] = relationship(back_populates="cameras")


class Device(Base):
    """Edge device registry: public key for signature checks + hashed API token (FMEA #12)."""

    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    public_key: Mapped[str] = mapped_column(String(64))
    key_id: Mapped[str] = mapped_column(String(64), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(default=now_utc)
    last_seen: Mapped[datetime | None] = mapped_column()
    last_heartbeat: Mapped[dict[str, Any]] = mapped_column(default=dict)
    revoked_at: Mapped[datetime | None] = mapped_column()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(32))
    site_ids: Mapped[list[Any] | None] = mapped_column(JSONType, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=now_utc)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"))
    camera_id: Mapped[str | None] = mapped_column(ForeignKey("cameras.id"))
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    route: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(32), default="normal")
    raw_score: Mapped[float | None] = mapped_column(Float)
    p_value: Mapped[float | None] = mapped_column(Float)
    features: Mapped[dict[str, Any]] = mapped_column(default=dict)
    objects: Mapped[list[Any]] = mapped_column(default=list)
    zone_id: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    track_ids: Mapped[list[Any]] = mapped_column(default=list)
    explanation_ur: Mapped[str | None] = mapped_column(Text)
    explanation_en: Mapped[str | None] = mapped_column(Text)
    explanation_roman: Mapped[str | None] = mapped_column(Text)
    vlm_verdict: Mapped[str | None] = mapped_column(String(16))
    vlm_confidence: Mapped[float | None] = mapped_column(Float)
    verified: Mapped[bool | None] = mapped_column(Boolean)
    ts_start: Mapped[datetime] = mapped_column()
    ts_end: Mapped[datetime] = mapped_column()
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """The signed ``AlertCandidate`` exactly as received from the edge."""
    alert_sha256: Mapped[str | None] = mapped_column(String(64))
    signature: Mapped[str | None] = mapped_column(String(128))
    device_key_id: Mapped[str | None] = mapped_column(String(64))
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    supersedes: Mapped[uuid.UUID | None] = mapped_column()
    superseded_by: Mapped[uuid.UUID | None] = mapped_column()
    clip_id: Mapped[str | None] = mapped_column(String(64), index=True)
    clip_uri: Mapped[str | None] = mapped_column(String(300))
    clip_sha256: Mapped[str | None] = mapped_column(String(64))
    original_sha256: Mapped[str | None] = mapped_column(String(64))
    keyframes: Mapped[list[Any]] = mapped_column(default=list)
    attestation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    delivery: Mapped[dict[str, Any]] = mapped_column(default=dict)
    sms_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    escalation_step: Mapped[int] = mapped_column(Integer, default=0)
    next_escalation_at: Mapped[datetime | None] = mapped_column()
    verify_deadline: Mapped[datetime | None] = mapped_column()
    opened_at: Mapped[datetime | None] = mapped_column()
    acked_at: Mapped[datetime | None] = mapped_column()
    acked_by: Mapped[str | None] = mapped_column(String(128))
    resolved_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(default=now_utc, onupdate=now_utc)

    __table_args__ = (
        Index("ix_alerts_site_created", "site_id", "created_at"),
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_next_escalation", "next_escalation_at"),
        Index("ix_alerts_tenant", "tenant_id"),
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(128))
    channel: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    at: Mapped[datetime] = mapped_column(default=now_utc)


class Review(Base):
    """Append-only guard/supervisor verdicts (active learning, FA statistics)."""

    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(128))
    verdict: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str | None] = mapped_column(Text)
    voice_uri: Mapped[str | None] = mapped_column(String(300))
    at: Mapped[datetime] = mapped_column(default=now_utc)


class ClipIndex(Base):
    """Search index (F1): one row per alert clip or finished track (activity-gated, ADR-015)."""

    __tablename__ = "clip_index"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"))
    camera_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    ref: Mapped[str] = mapped_column(String(160), unique=True)
    alert_id: Mapped[uuid.UUID | None] = mapped_column()
    alert_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    ts_start: Mapped[datetime] = mapped_column()
    ts_end: Mapped[datetime] = mapped_column()
    objects: Mapped[list[Any]] = mapped_column(default=list)
    zones: Mapped[list[Any]] = mapped_column(default=list)
    passes: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_uri: Mapped[str | None] = mapped_column(String(300))
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(default=now_utc)

    __table_args__ = (Index("ix_clip_index_site_ts", "site_id", "ts_start"),)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"))
    manifest: Mapped[dict[str, Any]] = mapped_column()
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    server_signature: Mapped[str] = mapped_column(String(128))
    server_key_id: Mapped[str] = mapped_column(String(64))
    merkle_batch_id: Mapped[int | None] = mapped_column(ForeignKey("merkle_batches.id"))
    merkle_leaf_index: Mapped[int | None] = mapped_column(Integer)
    merkle_proof: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    pdf_uri: Mapped[str | None] = mapped_column(String(300))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    case_reference: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=now_utc)


class EvidenceAlert(Base):
    __tablename__ = "evidence_alerts"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), primary_key=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id"), primary_key=True)


class MerkleBatch(Base):
    __tablename__ = "merkle_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    root: Mapped[str] = mapped_column(String(64))
    tree_size: Mapped[int] = mapped_column(Integer)
    ots_proof: Mapped[bytes | None] = mapped_column(LargeBinary)
    ots_status: Mapped[str] = mapped_column(String(16), default="pending")
    closed_at: Mapped[datetime] = mapped_column(default=now_utc)


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"))
    dsl: Mapped[dict[str, Any]] = mapped_column()
    source_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending -> active -> disabled
    created_by: Mapped[str] = mapped_column(String(128))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    backtest: Mapped[dict[str, Any]] = mapped_column(default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=now_utc)


class EdgeCommandRow(Base):
    """An admin command for an edge (e.g. accept a camera's new view); done once the edge
    reports it in a heartbeat."""

    __tablename__ = "edge_commands"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    camera_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    issued_by: Mapped[str] = mapped_column(String(128))
    issued_at: Mapped[datetime] = mapped_column(default=now_utc)
    done_at: Mapped[datetime | None] = mapped_column()


class ModeWindowRow(Base):
    """F16 event mode on site-local dates (inclusive). Rows are confirmed by an admin; Hijri
    estimates are computed on the fly and never stored until someone confirms them."""

    __tablename__ = "mode_windows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    mode: Mapped[str] = mapped_column(String(32))
    starts: Mapped[date] = mapped_column(Date)
    ends: Mapped[date] = mapped_column(Date)
    confirmed_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=now_utc)


class AuditLog(Base):
    """Hash-chained: ``row_hash = SHA256(prev_hash || canonical(row))`` (chain of custody)."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column()
    actor: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(160), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    row_hash: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(default=now_utc)


class AlertEmbedding(Base):
    """A bike alert's appearance embedding, kept 24 h and only at opted-in sites (F21): long
    enough for a supervisor to confirm the incident and share it with the neighbours."""

    __tablename__ = "alert_embeddings"
    alert_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    descriptor_b64: Mapped[str] = mapped_column(Text)
    riders: Mapped[int | None] = mapped_column(Integer)
    color: Mapped[str | None] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(index=True)


class NetworkShareRow(Base):
    """One confirmed incident shared with one neighbouring site, until ``expires_at`` (2 h)."""

    __tablename__ = "network_shares"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    from_site: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    to_site: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    alert_id: Mapped[uuid.UUID] = mapped_column()
    alert_type: Mapped[str] = mapped_column(String(32))
    riders: Mapped[int | None] = mapped_column(Integer)
    color: Mapped[str | None] = mapped_column(String(16))
    descriptor_b64: Mapped[str] = mapped_column(Text)
    distance_km: Mapped[float] = mapped_column(Float)
    seen_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(index=True)
