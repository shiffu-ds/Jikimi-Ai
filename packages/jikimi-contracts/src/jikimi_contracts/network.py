"""Mohalla alert network (F21, opt-in): what neighbouring sites may share, and nothing more.

A confirmed high-severity incident at an opted-in site shares the bike's *appearance embedding*
(no image, no face, no plate), its rider count and colour with opted-in sites within both sites'
radius, for two hours. Each neighbour's edge matches it locally against bikes it sees and tells
only its own guard; nothing is acted on automatically, and every share is audited.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

SHARE_HOURS = 2.0
EMBEDDING_HOURS = 24.0  # re-ID embeddings are kept no longer (plan Section 8.19)


class BikeEmbedding(BaseModel):
    """Edge -> server, next to a bike alert; dropped unless the site is opted in."""

    alert_id: UUID
    site_id: str
    descriptor_b64: str = Field(max_length=4096)
    riders: int | None = None
    color: str | None = None


class NetworkShare(BaseModel):
    id: str
    alert_type: str
    riders: int | None = None
    color: str | None = None
    descriptor_b64: str
    seen_at: AwareDatetime
    expires_at: AwareDatetime
    distance_km: float


class NetworkBundle(BaseModel):
    site_id: str
    version: str
    opted_in: bool
    shares: list[NetworkShare]
    key_id: str
    public_key: str
    signed_at: AwareDatetime
    signature: str

    def signing_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"signature"})


class NetworkSettings(BaseModel):
    opted_in: bool = False
    radius_km: float = Field(default=1.5, ge=0.5, le=2.0)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    agreement: str | None = Field(default=None, max_length=200)
    """Who signed the written agreement, and when (required to opt in)."""


class NetworkStatus(BaseModel):
    settings: NetworkSettings
    neighbors: int
    shares_sent_24h: int
    shares_received_active: int
