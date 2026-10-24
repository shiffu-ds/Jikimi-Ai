"""Rule DSL for the Roman Urdu rule builder (F11, plan Section 8.11).

Text -> (lexicon parser or LLM structured output) -> this schema -> validator (site vocabulary)
-> backtest -> admin approval -> signed config on the edge.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .alerts import Severity

DayName = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ALL_DAYS: list[DayName] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class Schedule(BaseModel):
    """Active window; ``to`` earlier than ``from`` means the window crosses midnight."""

    model_config = ConfigDict(populate_by_name=True)

    days: list[DayName] = Field(default_factory=lambda: list(ALL_DAYS))
    from_: str = Field(alias="from")
    to: str

    @field_validator("from_", "to")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("time must be HH:MM (24h)")
        return v

    def contains(self, local: datetime) -> bool:
        """Is site-local wall-clock time ``local`` inside the window? An overnight window belongs to
        the day it starts on: "jumma ki raat" (fri 22:00-05:00) still runs at 02:00 on saturday."""
        start, end = (int(v[:2]) * 60 + int(v[3:]) for v in (self.from_, self.to))
        m = local.hour * 60 + local.minute
        if start == end:
            inside = True
        elif start < end:
            inside = start <= m < end
        else:
            inside = m >= start or m < end
        if not inside:
            return False
        day = local.weekday()
        if start > end and m < end:
            day = (day - 1) % 7
        return ALL_DAYS[day] in self.days


class ObjectFilter(BaseModel):
    type: str
    color: str | None = None


class Condition(BaseModel):
    dwell_seconds_gt: int | None = Field(default=None, ge=10, le=24 * 3600)
    count_gt: int | None = Field(default=None, ge=0, le=500)

    @model_validator(mode="after")
    def _at_least_one(self) -> Condition:
        if self.dwell_seconds_gt is None and self.count_gt is None:
            raise ValueError("condition needs dwell_seconds_gt or count_gt")
        return self


class When(BaseModel):
    schedule: Schedule | None = None
    camera_ids: list[str] = Field(min_length=1)
    zone: str | None = None
    object: ObjectFilter
    condition: Condition


NotifyTarget = Literal["guard", "supervisor", "owner"]


def _default_notify() -> list[NotifyTarget]:
    return ["guard"]


class AlertAction(BaseModel):
    severity: Severity = Severity.MEDIUM
    notify: list[NotifyTarget] = Field(default_factory=_default_notify)


class Then(BaseModel):
    alert: AlertAction


class Rule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rule_id: str = Field(pattern=r"^r-[a-z0-9-]{3,64}$")
    name_ur: str
    name_en: str | None = None
    site_id: str
    when: When
    then: Then
    created_by: str
    approved_by: str | None = None
    version: int = 1
    source_text: str | None = None


RuleStatus = Literal["pending", "active", "disabled"]


class RuleDraftRequest(BaseModel):
    site_id: str
    text: str = Field(min_length=3, max_length=300)


class RuleBacktest(BaseModel):
    """How often the rule would have fired on the last ``days`` of indexed tracks (plan 8.11)."""

    days: int
    tracks_checked: int
    matches: int
    per_day: float
    last_matches: list[AwareDatetime] = Field(default_factory=list)


class RuleDraft(BaseModel):
    """Parser output. ``questions`` instead of a guessed rule when the text is unclear."""

    valid: bool
    rule: Rule | None = None
    questions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    understood: dict[str, Any] = Field(default_factory=dict)
    backtest: RuleBacktest | None = None


class RuleCreate(BaseModel):
    rule: Rule


class RuleOut(BaseModel):
    rule_id: str
    site_id: str
    status: RuleStatus
    rule: Rule
    created_by: str
    approved_by: str | None = None
    version: int
    created_at: AwareDatetime
    backtest: RuleBacktest | None = None
    on_edge: bool | None = None
    """Active rules: ``True`` once an edge of the site reports the current bundle in its heartbeat."""


class RuleBundle(BaseModel):
    """Active rules of one site, signed by the server; the edge pulls it from ``/v1/edge/rules``."""

    site_id: str
    version: str
    rules: list[Rule]
    key_id: str
    public_key: str
    signed_at: AwareDatetime
    signature: str

    def signing_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude={"signature"})


def rule_json_schema() -> dict[str, Any]:
    """JSON Schema handed to the LLM as structured-output format."""
    return Rule.model_json_schema(by_alias=True)
