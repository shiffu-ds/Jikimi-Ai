"""Edge -> server ingest: alerts, clips, track summaries, heartbeats, snapshots, SMS acks.

Every alert and clip attestation must carry a valid Ed25519 signature from the *registered*
device key of the same site (STRIDE: spoofing/tampering). Ingest is idempotent on alert_id.
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from jikimi_common.explain import CameraNames, explain_alert
from jikimi_contracts import AlertCandidate, ClipAttestation, EdgeAlertEnvelope, Route, TrackSummary
from jikimi_contracts.events import EdgeAck, EdgeHeartbeat
from jikimi_crypto import sha256_hex
from jikimi_crypto.hashing import json_digest
from jikimi_crypto.signing import verify_bytes
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import audit
from ..db.models import Alert, AlertEvent, Camera, ClipIndex, Device, Site, now_utc
from ..storage import LocalStore
from . import commands as commands_svc
from .alerts import AlertService, TransitionError
from .effects import Effects

log = logging.getLogger(__name__)

STATUS_FOR_ROUTE = {Route.ALERT_NOW: "open", Route.VERIFY: "verifying", Route.LOG_ONLY: "logged_only"}


class IngestError(ValueError):
    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail


def _verify_signed(
    device: Device, payload: dict[str, Any], signature: str | None, key_id: str | None
) -> tuple[bool, str]:
    digest = json_digest(payload)
    ok = key_id == device.key_id and bool(signature) and verify_bytes(device.public_key, digest, signature or "")
    return ok, digest.hex()


class EdgeIngest:
    def __init__(self, alerts: AlertService, store: LocalStore) -> None:
        self.alerts = alerts
        self.store = store

    def ingest_alert(self, db: Session, device: Device, env: EdgeAlertEnvelope, effects: Effects) -> tuple[Alert, bool]:
        a: AlertCandidate = env.alert
        existing = db.get(Alert, a.alert_id)
        if existing is not None:
            return existing, False
        if a.site_id != device.site_id:
            raise IngestError(403, "Wrong site", f"device {device.id} is registered for {device.site_id}")
        cam = db.get(Camera, a.camera_id)
        if cam is None or cam.site_id != device.site_id:
            raise IngestError(422, "Unknown camera", f"camera '{a.camera_id}' is not registered for this site")
        ok, alert_sha = _verify_signed(device, a.signing_payload(), a.signature, a.device_key_id)
        if not ok:
            audit.record(
                db,
                "edge.signature_invalid",
                f"device:{device.id}",
                str(a.alert_id),
                {"key_id": a.device_key_id},
                device.tenant_id,
            )
            raise IngestError(
                422, "Invalid signature", "alert signature does not verify against the registered device key"
            )
        site = db.get(Site, a.site_id)
        assert site is not None and a.route is not None
        tz = ZoneInfo(site.timezone)
        names = CameraNames(id=cam.id, name=cam.name, name_ur=cam.name_ur, name_roman=cam.name_roman)
        expl = explain_alert(a.type.value, a.features, names, a.ts_end.astimezone(tz), a.p_value, a.raw_score)
        status = STATUS_FOR_ROUTE[a.route]
        row = Alert(
            id=a.alert_id,
            tenant_id=device.tenant_id,
            site_id=a.site_id,
            camera_id=a.camera_id,
            type=a.type.value,
            severity=a.severity.value,
            route=a.route.value,
            status=status,
            mode=a.mode,
            raw_score=a.raw_score,
            p_value=a.p_value,
            features=a.features,
            objects=[o.model_dump(mode="json") for o in a.objects],
            zone_id=a.zone_id,
            entity_id=a.entity_id,
            track_ids=a.track_ids,
            explanation_ur=expl.ur,
            explanation_en=expl.en,
            explanation_roman=a.explanation_roman or expl.roman,
            ts_start=a.ts_start,
            ts_end=a.ts_end,
            payload=a.model_dump(mode="json"),
            alert_sha256=alert_sha,
            signature=a.signature,
            device_key_id=a.device_key_id,
            signature_valid=True,
            supersedes=a.supersedes,
            trace_id=a.trace_id,
            delivery=env.delivery.model_dump(mode="json"),
            sms_sent=env.delivery.sms_sent_at is not None,
        )
        db.add(row)
        db.flush()
        now = now_utc()
        db.add(
            AlertEvent(
                alert_id=row.id,
                kind="ingested",
                actor=f"device:{device.id}",
                payload={
                    "route": row.route,
                    "p_value": a.p_value,
                    "latency_s": round((now - a.ts_end).total_seconds(), 2),
                },
                at=now,
            )
        )
        if env.delivery.sms_sent_at is not None:
            db.add(
                AlertEvent(
                    alert_id=row.id,
                    kind="sms_sent",
                    actor=f"device:{device.id}",
                    channel="sms",
                    payload={"recipients": env.delivery.sms_recipients},
                    at=env.delivery.sms_sent_at,
                )
            )
        db.add(
            ClipIndex(
                tenant_id=row.tenant_id,
                site_id=row.site_id,
                camera_id=row.camera_id or "-",
                kind="alert",
                ref=f"alert:{row.id}",
                alert_id=row.id,
                alert_type=row.type,
                entity_id=row.entity_id,
                ts_start=row.ts_start,
                ts_end=row.ts_end,
                objects=row.objects,
                zones=[row.zone_id] if row.zone_id else [],
                passes=int(a.features.get("passes", 0) or 0),
            )
        )
        self.alerts.supersede(db, row, effects)
        self.alerts.after_ingest(db, row, effects, now)
        return row, True

    def ingest_clip(
        self,
        db: Session,
        device: Device,
        att: ClipAttestation,
        clip: bytes,
        keyframes: list[tuple[str, bytes]],
        effects: Effects,
    ) -> Alert:
        a = db.get(Alert, att.alert_id)
        if a is None or a.site_id != device.site_id:
            raise IngestError(404, "Unknown alert", "clip for an alert this device did not send")
        ok, att_sha = _verify_signed(device, att.signing_payload(), att.signature, att.device_key_id)
        if not ok:
            audit.record(
                db, "edge.signature_invalid", f"device:{device.id}", att.clip_id, {"kind": "clip"}, device.tenant_id
            )
            raise IngestError(422, "Invalid signature", "clip attestation signature does not verify")
        if sha256_hex(clip) != att.clip_sha256:
            raise IngestError(422, "Hash mismatch", "uploaded clip does not match the attested SHA-256")
        expected = {k.name: k.sha256 for k in att.keyframes}
        stored_kf: list[dict[str, Any]] = []
        for name, data in keyframes:
            if expected.get(name) != sha256_hex(data):
                raise IngestError(422, "Hash mismatch", f"keyframe {name} does not match its attested SHA-256")
        day = att.ts_start.strftime("%Y-%m-%d")
        base = f"clips/{a.site_id}/{day}"
        a.clip_uri = self.store.put_bytes(f"{base}/{att.clip_id}.mp4", clip)
        by_name = dict(keyframes)
        for k in att.keyframes:
            if k.name in by_name:
                uri = self.store.put_bytes(f"{base}/{k.name}", by_name[k.name])
                stored_kf.append(
                    {"name": k.name, "sha256": k.sha256, "uri": uri, "ts": k.ts.isoformat() if k.ts else None}
                )
        a.clip_id = att.clip_id
        a.clip_sha256 = att.clip_sha256
        a.original_sha256 = att.original_sha256
        a.keyframes = stored_kf
        a.attestation = att.model_dump(mode="json")
        db.add(
            AlertEvent(
                alert_id=a.id,
                kind="clip_received",
                actor=f"device:{device.id}",
                payload={"clip_id": att.clip_id, "frames": att.frames, "attestation_sha256": att_sha},
                at=now_utc(),
            )
        )
        idx = db.scalar(select(ClipIndex).where(ClipIndex.ref == f"alert:{a.id}"))
        if idx is not None and stored_kf:
            idx.thumbnail_uri = stored_kf[len(stored_kf) // 2]["uri"]
        self.alerts.changed(db, a, effects)
        return a

    def ingest_track(self, db: Session, device: Device, t: TrackSummary) -> bool:
        if t.site_id != device.site_id:
            raise IngestError(403, "Wrong site", "track summary for another site")
        ref = f"track:{t.camera_id}:{t.track_ids[0] if t.track_ids else t.entity_id}:{int(t.ts_start.timestamp())}"
        if db.scalar(select(ClipIndex.id).where(ClipIndex.ref == ref)) is not None:
            return False
        thumb_uri = None
        if t.thumbnail_jpeg_b64:
            data = base64.b64decode(t.thumbnail_jpeg_b64)
            thumb_uri = self.store.put_bytes(
                f"thumbs/{t.site_id}/{t.ts_start:%Y-%m-%d}/{sha256_hex(ref.encode())[:20]}.jpg", data
            )
        db.add(
            ClipIndex(
                tenant_id=device.tenant_id,
                site_id=t.site_id,
                camera_id=t.camera_id,
                kind="track",
                ref=ref,
                entity_id=t.entity_id,
                ts_start=t.ts_start,
                ts_end=t.ts_end,
                objects=[t.object.model_dump(mode="json")],
                zones=t.zones,
                passes=t.passes,
                thumbnail_uri=thumb_uri,
            )
        )
        return True

    def heartbeat(self, db: Session, device: Device, hb: EdgeHeartbeat, effects: Effects) -> None:
        now = now_utc()
        device.last_seen = now
        device.last_heartbeat = hb.model_dump(mode="json")
        commands_svc.mark_done(db, device.site_id, hb.extra.get("commands_done") or [], now)
        for ch in hb.cameras:
            cam = db.get(Camera, ch.camera_id)
            if cam is None or cam.site_id != device.site_id:
                continue
            cam.status = "online" if ch.online else "offline"
            cam.fps = ch.fps
            cam.health = ch.checks
            cam.last_seen = ch.last_frame_at or cam.last_seen
        effects.publish(
            "health.updated",
            device.site_id,
            {
                "device_id": device.id,
                "online": hb.online,
                "backlog": hb.outbox_backlog,
                "power": hb.power.model_dump(mode="json"),
            },
        )

    def snapshot(self, device: Device, camera_id: str, jpeg: bytes) -> str:
        return self.store.put_bytes(f"snapshots/{device.site_id}/{camera_id}.jpg", jpeg)

    def edge_ack(self, db: Session, device: Device, ack: EdgeAck, effects: Effects) -> str:
        a = db.get(Alert, ack.alert_id)
        if a is None or a.site_id != device.site_id:
            raise IngestError(404, "Unknown alert", "ack for an unknown alert")
        actor = f"{ack.channel}:{ack.actor}"
        try:
            if ack.action == "ack":
                self.alerts.ack(db, a, actor, ack.channel, effects, at=min(ack.at, datetime.now(UTC)))
            elif ack.action == "false_alarm":
                self.alerts.review(db, a, actor, "false", effects, notes=f"via {ack.channel}")
            elif ack.action == "need_help":
                self.alerts.need_help(db, a, actor, effects)
        except TransitionError as exc:
            return f"ignored: {exc}"
        return "applied"
