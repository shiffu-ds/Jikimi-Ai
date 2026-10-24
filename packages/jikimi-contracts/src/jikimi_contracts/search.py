"""Roman Urdu search contracts (F1, plan Section 8.6)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class TimeRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: AwareDatetime = Field(alias="from")
    to: AwareDatetime


class ObjectQuery(BaseModel):
    type: str
    color: str | None = None
    riders: int | None = None
    helmet: bool | None = None


class SearchIntent(StrEnum):
    FIND_CLIPS = "find_clips"
    TRAJECTORY = "trajectory"
    COUNT = "count"
    REPORT = "report"


class ParsedQuery(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    time_range: TimeRange | None = None
    time_phrase: str | None = None
    default_time_range: bool = False
    cameras: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)
    objects: list[ObjectQuery] = Field(default_factory=list)
    alert_types: list[str] = Field(default_factory=list)
    text_en: str = ""
    intent: SearchIntent = SearchIntent.FIND_CLIPS
    parser_path: Literal["lexicon", "llm", "hybrid"] = "lexicon"
    coverage: float = 1.0
    unknown_tokens: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    site_id: str
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=10, ge=1, le=50)


class ClipRef(BaseModel):
    clip_id: str
    kind: Literal["alert", "track"]
    alert_id: UUID | None = None
    alert_type: str | None = None
    camera_id: str
    camera_name: str | None = None
    ts_start: AwareDatetime
    ts_end: AwareDatetime
    score: float
    thumbnail_url: str | None = None
    clip_url: str | None = None
    objects: list[dict[str, object]] = Field(default_factory=list)
    matched: list[str] = Field(default_factory=list)
    """Human-readable reasons, e.g. ``"color:black"``, ``"riders:2"``, ``"zone:gate-2"``."""


class SearchResponse(BaseModel):
    parsed: ParsedQuery
    results: list[ClipRef]
    took_ms: float
    next_cursor: str | None = None


class AgentContext(BaseModel):
    """What the previous turn found, sent back by the client (re-checked by the server)."""

    clip_ids: list[str] = Field(default_factory=list, max_length=20)
    last_query: str | None = Field(default=None, max_length=300)


class AgentTurn(BaseModel):
    site_id: str
    message: str = Field(min_length=1, max_length=300)
    context: AgentContext | None = None


class ToolCall(BaseModel):
    name: str
    args: dict[str, object] = Field(default_factory=dict)
    results: int
    ms: float


class AgentReply(BaseModel):
    """F1 Tier 2: an answer whose every claim cites clips of this site."""

    intent: str
    answer_ur: str
    answer_roman: str
    answer_en: str
    citations: list[ClipRef]
    tools: list[ToolCall]
    context: AgentContext
    draft_report: str | None = None
    count: int | None = None
    """For "kitni / how many": distinct bikes (or people) that match every asked attribute."""
