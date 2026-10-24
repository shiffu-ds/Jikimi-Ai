"""Evidence pack contracts (F8, plan Section 8.9).

Two-layer signatures (improvement over plan v2.3, ADR-017):
1. The **edge device key** signs every alert and every clip attestation at capture time. The
   private key never leaves the site.
2. The **server evidence key** signs the evidence manifest, which embeds the edge signatures.

The verifier checks both, plus file hashes, the Merkle inclusion proof and the OpenTimestamps
proof. Any 1-byte change to a clip, PDF or manifest makes at least one check fail.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from .version import SCHEMA_VERSION


class EvidenceAlertRef(BaseModel):
    alert_id: UUID
    type: str
    severity: str
    camera_id: str
    camera_name: str | None = None
    ts_start: AwareDatetime
    ts_end: AwareDatetime
    alert_sha256: str
    """SHA-256 of the canonical JSON the edge signed."""
    edge_signature: str | None
    device_key_id: str | None
    explanation_ur: str | None = None
    explanation_en: str | None = None


class EvidenceClip(BaseModel):
    clip_id: str
    alert_id: UUID
    camera_id: str
    uri: str
    sha256: str
    original_sha256: str | None = None
    ts_start: AwareDatetime
    ts_end: AwareDatetime
    attestation_sha256: str
    attestation_signature: str | None
    device_key_id: str | None
    keyframes: list[dict[str, str]] = Field(default_factory=list)


class EvidenceManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    site_id: str
    site_name: str
    case_reference: str | None = None
    alerts: list[EvidenceAlertRef]
    clips: list[EvidenceClip] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    created_at: AwareDatetime
    created_by: str
    server_key_id: str
    notes: str | None = None


class ProofStep(BaseModel):
    side: Literal["left", "right"]
    hash: str


class MerkleProof(BaseModel):
    """RFC 6962 inclusion proof of ``leaf`` (a manifest SHA-256) in a daily batch."""

    batch_id: int
    day: str
    leaf_index: int
    tree_size: int
    path: list[ProofStep]
    root: str


class CheckStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - a check status, not a password
    FAIL = "fail"
    PENDING = "pending"
    SKIPPED = "skipped"


class VerificationCheck(BaseModel):
    name: str
    status: CheckStatus
    detail_en: str
    detail_ur: str
    data: dict[str, Any] = Field(default_factory=dict)


class VerificationReport(BaseModel):
    evidence_id: str
    verified: bool
    """True when no check failed (pending checks, e.g. a fresh Bitcoin timestamp, are allowed)."""
    summary_en: str
    summary_ur: str
    checks: list[VerificationCheck]
    manifest_sha256: str
    pdf_sha256: str | None
    site_name: str
    created_at: AwareDatetime
    alert_count: int
    clip_count: int
    artifacts: list[dict[str, str]] = Field(default_factory=list)
    """``{"kind", "name", "sha256"}`` for every file a verifier can drop in to compare."""


class FileMatch(BaseModel):
    """Answer to "does this file (by hash) belong to the evidence pack?"."""

    evidence_id: str
    sha256: str
    matched: bool
    kind: str | None = None
    name: str | None = None
