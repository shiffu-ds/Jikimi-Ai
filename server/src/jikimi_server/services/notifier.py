"""Notification channels + escalation chain (F17, plan Section 8.17).

    0 s    guard: app push + loud sound
    60 s   guard: app + Telegram/WhatsApp voice note + SMS
    120 s  supervisor: app + Telegram
    300 s  owner/admin: app + Telegram (+ call, optional)

Timers live in the database (``alerts.next_escalation_at``), so a server restart never loses an
escalation. ``JIKIMI_ESCALATION_SCALE=0.25`` compresses the timeline for demos.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from ..db.models import Alert, AlertEvent, Site
from ..settings import ServerSettings
from .effects import Effects

log = logging.getLogger(__name__)

DEFAULT_PLAN: list[dict[str, Any]] = [
    {"after_s": 0, "roles": ["guard"], "channels": ["app"]},
    {"after_s": 60, "roles": ["guard"], "channels": ["app", "telegram", "sms"]},
    {"after_s": 120, "roles": ["supervisor"], "channels": ["app", "telegram"]},
    {"after_s": 300, "roles": ["owner", "admin"], "channels": ["app", "telegram", "call"]},
]


class Telegram:
    def __init__(self, token: str, chat_ids: list[str]) -> None:
        self.token = token
        self.chat_ids = chat_ids

    def send(self, text: str) -> int:
        ok = 0
        for chat in self.chat_ids:
            try:
                r = httpx.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": chat, "text": text},
                    timeout=10,
                )
                ok += int(r.status_code == 200)
            except httpx.HTTPError as exc:
                log.warning("telegram send failed: %s", exc)
        return ok


class Notifier:
    def __init__(self, settings: ServerSettings) -> None:
        self.s = settings
        self.telegram = (
            Telegram(settings.telegram_bot_token, settings.telegram_chat_ids)
            if settings.telegram_bot_token and settings.telegram_chat_ids
            else None
        )

    def plan(self, site: Site | None) -> list[dict[str, Any]]:
        plan = (site.config or {}).get("escalation") if site is not None else None
        plan = plan or DEFAULT_PLAN
        scale = self.s.escalation_scale
        return [{**step, "after_s": float(step["after_s"]) * scale} for step in plan]

    def notify(
        self,
        alert: Alert,
        site: Site | None,
        step_idx: int,
        now: datetime,
        effects: Effects,
        db_add: Any,
        summary: dict[str, Any],
    ) -> None:
        plan = self.plan(site)
        if step_idx >= len(plan):
            alert.next_escalation_at = None
            return
        step = plan[step_idx]
        kind = "notified" if step_idx == 0 else "escalated"
        for channel in step["channels"]:
            delivered: bool | None = True
            note = None
            if channel == "app":
                effects.publish(
                    "alert.notify",
                    alert.site_id,
                    {"alert": summary, "step": step_idx, "roles": step["roles"], "sound": True},
                    set(step["roles"]),
                )
            elif channel == "telegram":
                if self.telegram is not None:
                    text = f"JIKIMI {'⚠️ ' if alert.severity == 'high' else ''}{alert.explanation_ur or ''}\n{alert.explanation_roman or ''}\n{self.s.public_base_url}/alerts/view/?id={alert.id}"
                    tg = self.telegram
                    effects.later(lambda tg=tg, text=text: tg.send(text) and None)  # type: ignore[misc]
                else:
                    delivered, note = None, "telegram not configured"
            elif channel == "sms":
                delivered, note = None, "server SMS provider not configured (edge sends SMS when offline)"
            elif channel == "call":
                delivered, note = None, "call channel not configured"
            db_add(
                AlertEvent(
                    alert_id=alert.id,
                    kind=kind,
                    actor="system",
                    channel=channel,
                    payload={
                        "step": step_idx,
                        "roles": step["roles"],
                        "delivered": delivered,
                        **({"note": note} if note else {}),
                    },
                    at=now,
                )
            )
        alert.escalation_step = step_idx
        if step_idx > 0 and alert.status == "open":
            alert.status = "escalated"
        base = alert.opened_at or now
        alert.next_escalation_at = (
            base + timedelta(seconds=plan[step_idx + 1]["after_s"]) if step_idx + 1 < len(plan) else None
        )
