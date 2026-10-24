"""Evaluate approved rule DSL (F11) against live tracks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jikimi_contracts.rules_dsl import Rule


def schedule_active(rule: Rule, ts: float, tz_offset_s: float) -> bool:
    sched = rule.when.schedule
    if sched is None:
        return True
    return sched.contains(datetime.fromtimestamp(ts, UTC) + timedelta(seconds=tz_offset_s))
