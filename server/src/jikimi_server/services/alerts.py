"""Alert lifecycle (state machine of plan Section 7.11) and API views.

Candidate -> LoggedOnly | Verifying | Open
Verifying -> Open (VLM confirmed, or unverified after timeout) | LoggedOnly (VLM rejected)
Open -> Escalated (ack timeout) -> ... ; Open/Escalated -> Acked
Acked -> Resolved | FalseAlarm | Unclear   (guard/supervisor review)
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from jikimi_common.explain import pvalue_text
from jikimi_common.ids import short_code
from jikimi_common.translit import roman_to_devanagari
from jikimi_contracts.api import AlertDetail, AlertEventOut, AlertSummary, ReviewOut
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Alert, AlertEvent, Camera, EvidenceAlert, Review, Site, now_utc
from .effects import Effects
from .notifier import Notifier

log = logging.getLogger(__name__)

ACTIVE = ("open", "escalated")
UNACKED = ("logged_only", "verifying", "open", "escalated")


class TransitionError(ValueError):
    pass


def summary(a: Alert, cam: Camera | None) -> AlertSummary:
    thumb = None
    if a.keyframes:
        thumb = f"/v1/media/keyframes/{a.id}/{len(a.keyframes) // 2}.jpg"
    return AlertSummary(
        id=a.id,
        site_id=a.site_id,
        camera_id=a.camera_id or "-",
        camera_name=cam.name if cam else None,
        camera_name_ur=cam.name_ur if cam else None,
        type=a.type,
        severity=a.severity,
        route=a.route,
        status=a.status,
        mode=a.mode,
        raw_score=a.raw_score,
        p_value=a.p_value,
        explanation_ur=a.explanation_ur,
        explanation_en=a.explanation_en,
        explanation_roman=a.explanation_roman,
        explanation_hi=roman_to_devanagari(a.explanation_roman) if a.explanation_roman else None,
        ts_start=a.ts_start,
        ts_end=a.ts_end,
        created_at=a.created_at,
        opened_at=a.opened_at,
        acked_at=a.acked_at,
        acked_by=a.acked_by,
        has_clip=bool(a.clip_uri),
        thumbnail_url=thumb,
        verified=a.verified,
        vlm_verdict=a.vlm_verdict,
        vlm_confidence=a.vlm_confidence,
        sms_sent=a.sms_sent,
        escalation_step=a.escalation_step,
        short_code=short_code(a.id),
    )


def detail(db: Session, a: Alert) -> AlertDetail:
    cam = db.get(Camera, a.camera_id) if a.camera_id else None
    events = db.scalars(
        select(AlertEvent).where(AlertEvent.alert_id == a.id).order_by(AlertEvent.at, AlertEvent.id)
    ).all()
    reviews = db.scalars(select(Review).where(Review.alert_id == a.id).order_by(Review.at)).all()
    ev_ids = db.scalars(select(EvidenceAlert.evidence_id).where(EvidenceAlert.alert_id == a.id)).all()
    ptxt = pvalue_text(a.p_value, (a.features or {}).get("calibration_mode", "normal"))
    base = summary(a, cam).model_dump()
    return AlertDetail(
        **base,
        features=a.features or {},
        objects=a.objects or [],
        p_value_text_ur=ptxt[0] if ptxt else None,
        p_value_text_en=ptxt[2] if ptxt else None,
        clip_url=f"/v1/media/clips/{a.id}.mp4" if a.clip_uri else None,
        keyframe_urls=[f"/v1/media/keyframes/{a.id}/{i}.jpg" for i in range(len(a.keyframes or []))],
        events=[
            AlertEventOut(kind=e.kind, actor=e.actor, channel=e.channel, payload=e.payload or {}, at=e.at)
            for e in events
        ],
        reviews=[ReviewOut(reviewer=r.reviewer, verdict=r.verdict, notes=r.notes, at=r.at) for r in reviews],  # type: ignore[arg-type]
        model_versions={k: str(v) for k, v in (a.payload.get("model_versions") or {}).items()},
        device_key_id=a.device_key_id,
        signature_valid=a.signature_valid,
        clip_sha256=a.clip_sha256,
        zone_id=a.zone_id,
        track_ids=[int(t) for t in a.track_ids or []],
        evidence_ids=list(ev_ids),
    )


class AlertService:
    def __init__(
        self, notifier: Notifier, verify_timeout_s: float, vlm_enabled: bool, vlm_advisory: bool = False
    ) -> None:
        self.notifier = notifier
        self.verify_timeout_s = verify_timeout_s
        self.vlm_enabled = vlm_enabled
        self.vlm_advisory = vlm_advisory

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _event(
        db: Session,
        a: Alert,
        kind: str,
        actor: str | None = "system",
        channel: str | None = None,
        at: datetime | None = None,
        **payload: Any,
    ) -> None:
        db.add(AlertEvent(alert_id=a.id, kind=kind, actor=actor, channel=channel, payload=payload, at=at or now_utc()))

    @staticmethod
    def _first_notified(a: Alert) -> datetime | None:
        """When a person was first told: the server's notification, or the edge's SMS fallback,
        which goes out before the server even knows about the alert when the internet is down."""
        times = [a.opened_at] if a.opened_at else []
        sms_at = (a.delivery or {}).get("sms_sent_at")
        if isinstance(sms_at, str):
            with contextlib.suppress(ValueError):
                times.append(datetime.fromisoformat(sms_at))
        return min(times) if times else None

    def _summary_dict(self, db: Session, a: Alert) -> dict[str, Any]:
        cam = db.get(Camera, a.camera_id) if a.camera_id else None
        return summary(a, cam).model_dump(mode="json")

    def changed(self, db: Session, a: Alert, effects: Effects, event: str = "alert.updated") -> None:
        db.flush()
        effects.publish(event, a.site_id, {"alert": self._summary_dict(db, a)})

    # ------------------------------------------------------------------ transitions
    def after_ingest(self, db: Session, a: Alert, effects: Effects, now: datetime | None = None) -> None:
        now = now or now_utc()
        if a.status == "open":
            self.open(db, a, effects, now, reason="alert_now")
        elif a.status == "verifying":
            if self.vlm_enabled:
                a.verify_deadline = now + timedelta(seconds=self.verify_timeout_s)
                self._event(db, a, "verify_requested", deadline_s=self.verify_timeout_s)
            elif self.vlm_advisory:
                a.verified = None
                self._event(db, a, "verify_requested", mode="advisory")  # opened now, the verdict follows
                self.open(db, a, effects, now, reason="unverified")
            else:
                a.verified = None
                self._event(db, a, "verify_skipped", note="no VLM configured; opened as unverified (FMEA #9)")
                self.open(db, a, effects, now, reason="unverified")
        self.changed(db, a, effects, "alert.created")

    def open(self, db: Session, a: Alert, effects: Effects, now: datetime, reason: str) -> None:
        a.status = "open"
        a.opened_at = a.opened_at or now
        a.next_escalation_at = None
        self._event(db, a, "opened", at=now, reason=reason)
        site = db.get(Site, a.site_id)
        db.flush()
        self.notifier.notify(a, site, 0, now, effects, db.add, self._summary_dict(db, a))

    def verify_result(
        self,
        db: Session,
        a: Alert,
        verdict: str,
        confidence: float,
        effects: Effects,
        provider: str,
        evidence: list[str] | None = None,
    ) -> None:
        """``verdict``: the alert's type (confirmed), "normal" or "unclear". While a VERIFY alert waits
        (gate mode), a confirmation opens it, "normal" logs it and "unclear" opens it unverified; on
        an alert that is already open the verdict is only attached (advisory)."""
        gate = a.status == "verifying"
        a.vlm_verdict, a.vlm_confidence = verdict, confidence
        self._event(
            db,
            a,
            "verified",
            actor=provider,
            verdict=verdict,
            confidence=confidence,
            evidence=evidence or [],
            mode="gate" if gate else "advisory",
        )
        if gate:
            now = now_utc()
            a.verify_deadline = None
            if verdict == a.type:
                a.verified = True
                self.open(db, a, effects, now, reason="vlm_confirmed")
            elif verdict == "normal":
                a.verified = False
                a.status = "logged_only"
            else:
                self.open(db, a, effects, now, reason="vlm_unclear")
        self.changed(db, a, effects)

    def ack(
        self,
        db: Session,
        a: Alert,
        actor: str,
        channel: str,
        effects: Effects,
        note: str | None = None,
        at: datetime | None = None,
    ) -> None:
        if a.status in ("resolved", "false_alarm", "unclear"):
            raise TransitionError(f"alert already {a.status}")
        if a.status == "acked":
            return
        at = at or now_utc()
        a.status = "acked"
        a.acked_at = at
        a.acked_by = actor
        a.next_escalation_at = None
        # an SMS reply synced after an outage can predate the server's own "opened" time
        first = self._first_notified(a)
        mtta = max(0.0, (at - first).total_seconds()) if first else None
        self._event(
            db,
            a,
            "acked",
            actor=actor,
            channel=channel,
            at=at,
            mtta_s=None if mtta is None else round(mtta, 1),
            note=note,
        )
        self.changed(db, a, effects)

    def review(
        self, db: Session, a: Alert, reviewer: str, verdict: str, effects: Effects, notes: str | None = None
    ) -> None:
        if a.status not in ("acked", "open", "escalated", "logged_only", "verifying"):
            raise TransitionError(f"cannot review an alert that is {a.status}")
        if a.status in ("open", "escalated"):
            self.ack(db, a, reviewer, "review", effects)
        db.add(Review(alert_id=a.id, reviewer=reviewer, verdict=verdict, notes=notes, at=now_utc()))
        a.status = {"true": "resolved", "false": "false_alarm", "unclear": "unclear"}[verdict]
        a.resolved_at = now_utc()
        a.next_escalation_at = None
        self._event(db, a, "reviewed", actor=reviewer, verdict=verdict, notes=notes)
        if verdict == "true":  # F21: a confirmed incident may go to opted-in neighbours
            from . import network

            shared = network.on_confirmed(db, a, reviewer, now_utc())
            if shared:
                self._event(db, a, "network_shared", actor=reviewer, sites=shared)
        effects.publish("review.recorded", a.site_id, {"alert_id": str(a.id), "verdict": verdict})
        self.changed(db, a, effects)

    def need_help(self, db: Session, a: Alert, actor: str, effects: Effects) -> None:
        """Guard replied "3 / madad": jump straight to the supervisor step."""
        self._event(db, a, "need_help", actor=actor)
        if a.status in ("acked",):
            a.status = "escalated"
        site = db.get(Site, a.site_id)
        db.flush()
        self.notifier.notify(
            a, site, min(2, len(self.notifier.plan(site)) - 1), now_utc(), effects, db.add, self._summary_dict(db, a)
        )
        self.changed(db, a, effects)

    def supersede(self, db: Session, new: Alert, effects: Effects) -> None:
        if new.supersedes is None:
            return
        prev = db.get(Alert, new.supersedes)
        if prev is None:
            return
        prev.superseded_by = new.id
        self._event(db, prev, "superseded", by=str(new.id), route=new.route)
        if prev.status in ("logged_only", "verifying", "open", "escalated"):
            prev.status = "resolved"
            prev.resolved_at = now_utc()
            prev.next_escalation_at = None
            prev.verify_deadline = None
        self.changed(db, prev, effects)

    # ------------------------------------------------------------------ timers (worker tick)
    def escalate_due(self, db: Session, now: datetime, effects: Effects) -> int:
        due = db.scalars(
            select(Alert)
            .where(Alert.status.in_(ACTIVE), Alert.next_escalation_at.is_not(None), Alert.next_escalation_at <= now)
            .limit(100)
        ).all()
        for a in due:
            site = db.get(Site, a.site_id)
            self.notifier.notify(a, site, a.escalation_step + 1, now, effects, db.add, self._summary_dict(db, a))
            self.changed(db, a, effects)
        return len(due)

    def verify_timeouts(self, db: Session, now: datetime, effects: Effects) -> int:
        late = db.scalars(
            select(Alert)
            .where(Alert.status == "verifying", Alert.verify_deadline.is_not(None), Alert.verify_deadline <= now)
            .limit(100)
        ).all()
        for a in late:
            a.verified = None
            a.verify_deadline = None
            self._event(db, a, "verify_timeout", note="VLM did not answer in time; opened as unverified")
            self.open(db, a, effects, now, reason="verify_timeout")
            self.changed(db, a, effects)
        return len(late)


def new_alert_id() -> uuid.UUID:
    from jikimi_common.ids import uuid7

    return uuid7()
