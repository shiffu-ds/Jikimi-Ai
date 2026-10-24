"""Background jobs: escalation timers, VERIFY timeouts, the VLM verifier (one alert at a time, in
the thread pool), camera staleness, daily Merkle batch (00:05 site time), hourly OpenTimestamps
upgrades.

Lite profile runs this inside the API process; compose runs ``python -m jikimi_server workers``.
Every job is idempotent and driven by database state, so restarts lose nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .context import AppContext
from .db.models import Alert, Camera, Device
from .evidence.service import next_close_time
from .services import network
from .services.effects import Effects

log = logging.getLogger(__name__)


class Workers:
    def __init__(self, ctx: AppContext, tz: str = "Asia/Karachi") -> None:
        self.ctx = ctx
        self.tz = ZoneInfo(tz)
        now = datetime.now(UTC)
        self.next_merkle = next_close_time(now, self.tz)
        self.last_ots = now
        self.last_stale = now - timedelta(minutes=5)
        self.ticks = 0
        self._vlm_busy = False
        self._vlm_tried: set[object] = set()

    async def run(self, stop: asyncio.Event, interval_s: float = 1.0) -> None:
        log.info("workers started (escalation, verify timeouts, merkle %s)", self.next_merkle.isoformat())
        while not stop.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.exception("worker tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval_s)

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self.ticks += 1
        effects = Effects()
        with self.ctx.db.session() as db:
            self.ctx.alerts.escalate_due(db, now, effects)
            self.ctx.alerts.verify_timeouts(db, now, effects)
            self._next_vlm_job(db, now)
            if self.ticks % 60 == 1:  # F21: expired shares and embeddings are deleted
                network.purge(db, now)
            if now - self.last_stale >= timedelta(seconds=30):
                self.last_stale = now
                self._mark_stale_cameras(db, now, effects)
            if now >= self.next_merkle:
                self.ctx.evidence.close_batch(db, now.astimezone(self.tz).date() - timedelta(days=1))
                self.next_merkle = next_close_time(now, self.tz)
            if now - self.last_ots >= timedelta(hours=1):
                self.last_ots = now
                self.ctx.evidence.upgrade_timestamps(db)
        self.ctx.dispatch(effects)

    def _next_vlm_job(self, db, now: datetime) -> Future[None] | None:  # type: ignore[no-untyped-def]
        """Hand the oldest recent alert that has keyframes but no VLM verdict to the verifier."""
        types = [] if self._vlm_busy else self.ctx.verifier.types()  # cheap: from verifier.json
        if not types or not self.ctx.verifier.available:  # only then import torch / transformers
            return None
        recent = db.scalars(
            select(Alert)
            .where(
                Alert.vlm_verdict.is_(None),
                Alert.type.in_(types),
                Alert.created_at >= now - timedelta(minutes=30),
            )
            .order_by(Alert.created_at)
            .limit(20)
        ).all()
        a = next((x for x in recent if x.keyframes and x.id not in self._vlm_tried), None)
        if a is None:
            return None
        self._vlm_tried.add(a.id)
        kfs = list(a.keyframes)
        n = max(1, self.ctx.settings.vlm_frames)
        picks = [kfs[round(i * (len(kfs) - 1) / max(n - 1, 1))]["uri"] for i in range(min(n, len(kfs)))]
        self._vlm_busy = True
        return self.ctx.executor.submit(self._vlm_job, a.id, a.type, picks)

    def _vlm_job(self, alert_id: object, alert_type: str, uris: list[str]) -> None:
        import cv2

        try:
            images = [img for u in uris if (img := cv2.imread(str(self.ctx.store.path(u)))) is not None]
            answer = self.ctx.verifier.verify(alert_type, images) if images else None
            if answer is None:
                return
            verdict = {"yes": alert_type, "no": "normal"}.get(answer.verdict, "unclear")
            effects = Effects()
            with self.ctx.db.session() as db:
                a = db.get(Alert, alert_id)
                if a is not None:
                    self.ctx.alerts.verify_result(
                        db,
                        a,
                        verdict,
                        answer.confidence,
                        effects,
                        provider=f"vlm:{self.ctx.verifier.name}",
                        evidence=[f"P(yes) {answer.p_yes:.2f} over {answer.frames} keyframes", f"{answer.ms} ms"],
                    )
            self.ctx.dispatch(effects)
        except Exception:
            log.exception("VLM verification failed", extra={"alert": str(alert_id)})
        finally:
            self._vlm_busy = False

    @staticmethod
    def _mark_stale_cameras(db, now: datetime, effects: Effects) -> None:  # type: ignore[no-untyped-def]
        """A silent edge (power or internet down) must not leave cameras shown as 'online'."""
        for dev in db.scalars(select(Device)):
            stale = dev.last_seen is None or now - dev.last_seen > timedelta(seconds=120)
            if not stale:
                continue
            for cam in db.scalars(select(Camera).where(Camera.site_id == dev.site_id, Camera.status == "online")):
                cam.status = "unknown"
                effects.publish("health.updated", cam.site_id, {"camera_id": cam.id, "status": "unknown"})
