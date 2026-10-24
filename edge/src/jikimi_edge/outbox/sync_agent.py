"""Store-and-forward sync agent with SMS fallback (F4, plan Section 8.8).

Bug fix vs. plan v2.3: the plan's loop waited ``age_s > 30`` before sending an SMS, but US2 and
the latency table require the SMS within 20 s. Here a high-severity alert that is still
undelivered after ``sms_grace_s`` (default 5 s) is sent by SMS - whether the internet is down,
the server is down, or the server is erroring - and then still synced when the link returns.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jikimi_common.ids import short_code
from jikimi_contracts import AlertCandidate, Severity

from ..config_sync import SignedBundleSync
from .db import Outbox, OutboxItem
from .formatter import format_alert_sms, parse_reply
from .server_client import ServerClient
from .sms_gateway import SmsGateway

log = logging.getLogger(__name__)


@dataclass
class SyncConfig:
    sms_numbers: list[str] = field(default_factory=list)
    sms_min_severity: Severity = Severity.HIGH
    sms_grace_s: float = 5.0
    loop_interval_s: float = 1.0
    health_cache_s: float = 2.0
    receive_interval_s: float = 3.0
    config_interval_s: float = 60.0
    """How often signed rules (F11) and the event calendar (F16) are pulled while online."""
    offline_flag: Path | None = None
    """If this file exists the link is treated as down (``make net-cut`` demo / chaos test)."""


WhereFn = Callable[[AlertCandidate], str]
LocalTimeFn = Callable[[datetime], datetime]


class SyncAgent:
    def __init__(
        self,
        outbox: Outbox,
        client: ServerClient,
        sms: SmsGateway,
        cfg: SyncConfig,
        where: WhereFn,
        local_time: LocalTimeFn,
        bundles: Sequence[SignedBundleSync[Any]] = (),
    ) -> None:
        self.outbox = outbox
        self.client = client
        self.sms = sms
        self.cfg = cfg
        self.where = where
        self.local_time = local_time
        self.bundles = list(bundles)
        self.online = False
        self._last_health = -1e18
        self._last_receive = -1e18
        self._last_config = -1e18
        self._stop = asyncio.Event()
        self.stats = {"sent": 0, "sms": 0, "failed": 0, "acks_in": 0}

    def stop(self) -> None:
        self._stop.set()

    async def check_online(self) -> bool:
        now = time.monotonic()
        if self.cfg.offline_flag is not None and self.cfg.offline_flag.exists():
            self.online = False
            return False
        if now - self._last_health >= self.cfg.health_cache_s:
            was = self.online
            self.online = await self.client.healthy()
            self._last_health = now
            if was != self.online:
                log.warning("server link %s", "UP" if self.online else "DOWN")
        return self.online

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.step()
            except Exception:
                log.exception("sync step failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.cfg.loop_interval_s)

    async def step(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        online = await self.check_online()
        if online:
            for item in self.outbox.due(now, limit=50):
                await self._deliver(item, now)
            if self.bundles and time.monotonic() - self._last_config >= self.cfg.config_interval_s:
                self._last_config = time.monotonic()
                for sync in self.bundles:
                    await self._pull(sync)
        self._sms_fallback(now)
        if time.monotonic() - self._last_receive >= self.cfg.receive_interval_s:
            self._last_receive = time.monotonic()
            self._receive_replies(now)

    async def _deliver(self, item: OutboxItem, now: float) -> None:
        payload = item.payload
        if item.kind == "alert":
            delivery = payload.setdefault("delivery", {})
            delivery["attempts"] = item.attempts + 1
            if item.sms_sent_at:
                delivery["sms_sent_at"] = datetime.fromtimestamp(item.sms_sent_at, UTC).isoformat()
                delivery["sms_recipients"] = item.sms_recipients
        res = await self.client.send(item)
        if res.ok:
            self.outbox.mark_sent(item.id, now)
            self.stats["sent"] += 1
        elif res.permanent:
            self.outbox.mark_dead(item.id, res.error)
            self.stats["failed"] += 1
            log.error(
                "outbox item rejected permanently", extra={"kind": item.kind, "status": res.status, "error": res.error}
            )
        else:
            self.outbox.backoff(item.id, item.attempts, res.error, now)
            if res.status is not None and res.status >= 500:
                self.online = False

    async def _pull(self, sync: SignedBundleSync[Any]) -> None:
        data = await self.client.get_json(sync.path)
        bundle = sync.parse(data) if data is not None else None
        if bundle is not None:
            sync.accept(bundle)

    def _sms_fallback(self, now: float) -> None:
        if not self.cfg.sms_numbers:
            return
        for item in self.outbox.pending_alerts():
            if item.status != "pending" or item.age_s(now) < self.cfg.sms_grace_s:
                continue
            alert = AlertCandidate.model_validate(item.payload["alert"])
            if alert.severity.rank < self.cfg.sms_min_severity.rank:
                continue
            code = short_code(alert.alert_id)
            text = format_alert_sms(alert, self.where(alert), self.local_time(alert.ts_end), code)
            sent = 0
            for number in self.cfg.sms_numbers:
                ok = self.sms.send(number, text)
                self.outbox.log_sms("out", number, text, "sent" if ok else "failed", str(alert.alert_id), code)
                sent += int(ok)
            if sent:
                self.outbox.mark_sms(item.id, sent, now)
                self.stats["sms"] += 1
                log.warning(
                    "SMS fallback sent", extra={"alert": code, "recipients": sent, "age_s": round(item.age_s(now), 1)}
                )

    def _receive_replies(self, now: float) -> None:
        for msg in self.sms.receive():
            self.outbox.log_sms("in", msg.number, msg.text, "received")
            if self.cfg.sms_numbers and msg.number not in self.cfg.sms_numbers and msg.number != "unknown":
                log.warning("SMS from unknown number ignored", extra={"from": msg.number})
                continue
            action, code = parse_reply(msg.text)
            if action is None:
                continue
            alert_id = (
                self.outbox.alert_for_code(code)
                if code
                else self.outbox.latest_sms_alert(msg.number if msg.number != "unknown" else None)
            )
            if alert_id is None:
                continue
            self.outbox.add_local_ack(alert_id, action, msg.number, "sms", msg.at)
            self.outbox.enqueue(
                "ack",
                {
                    "alert_id": alert_id,
                    "action": action,
                    "actor": msg.number,
                    "channel": "sms",
                    "at": datetime.fromtimestamp(msg.at, UTC).isoformat(),
                },
                severity="high",
                priority=1,
                dedupe_key=f"ack:{alert_id}:{action}:{int(msg.at)}",
                now=now,
            )
            self.stats["acks_in"] += 1
            log.warning("SMS reply recorded", extra={"action": action, "alert": short_code(alert_id)})
