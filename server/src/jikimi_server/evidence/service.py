"""Evidence packs (F8): manifest -> server signature -> PDF -> daily Merkle batch -> OTS.

Layer 1 (edge key) signatures are carried inside the manifest; layer 2 (server evidence key)
signs the manifest. ``verify()`` re-checks everything from stored bytes, so tampering with the
database, the stored clips or the PDF is detected.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import qrcode
import qrcode.image.svg
from jikimi_common.explain import pvalue_text
from jikimi_common.ids import evidence_id
from jikimi_contracts.evidence import (
    CheckStatus,
    EvidenceAlertRef,
    EvidenceClip,
    EvidenceManifest,
    FileMatch,
    MerkleProof,
    ProofStep,
    VerificationCheck,
    VerificationReport,
)
from jikimi_crypto import Signer, inclusion_proof, key_id_for, merkle_root, sha256_hex, verify_inclusion
from jikimi_crypto import ots as ots_lib
from jikimi_crypto.hashing import json_digest
from jikimi_crypto.signing import verify_bytes
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Alert, Camera, Device, Evidence, EvidenceAlert, MerkleBatch, Site
from ..storage import LocalStore

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"
TYPE_NAMES = {
    "snatch": ("چھینا جھپٹی کا شبہ", "Suspected snatching"),
    "loitering": ("مشکوک چکر", "Suspicious loitering"),
    "camera_tamper": ("کیمرے سے چھیڑ چھاڑ", "Camera tampering"),
    "rule": ("قاعدہ", "Rule"),
    "sos": ("ایس او ایس", "SOS"),
    "audio_event": ("آواز", "Audio event"),
    "network_match": ("پڑوس سے ملتی بائیک", "Bike seen at a neighbour"),
    "person_in_danger": ("کسی کو خطرہ", "Person in danger"),
    "vehicle_theft": ("بائیک چوری کا شبہ", "Suspected bike theft"),
    "crowd_panic": ("بھگدڑ", "Crowd panic"),
}


class EvidenceError(ValueError):
    pass


def load_retired_keys(folder: Path) -> dict[str, str]:
    """Public keys of rotated-out server keys (``keys/retired/*.pub``), by key id, so evidence
    signed before a rotation stays verifiable (``docs/runbooks/key_rotation.md``)."""
    keys: dict[str, str] = {}
    for f in sorted(folder.glob("*.pub")):
        pub = f.read_text(encoding="utf-8").strip()
        keys[key_id_for(pub, "server")] = pub
    return keys


@dataclass
class EvidenceService:
    store: LocalStore
    signer: Signer
    public_base_url: str
    retired_keys: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ build
    def create(
        self,
        db: Session,
        alerts: list[Alert],
        created_by: str,
        case_reference: str | None = None,
        notes: str | None = None,
    ) -> Evidence:
        if not alerts:
            raise EvidenceError("no alerts")
        site_ids = {a.site_id for a in alerts}
        if len(site_ids) != 1:
            raise EvidenceError("all alerts must belong to one site")
        site = db.get(Site, site_ids.pop())
        assert site is not None
        tz = ZoneInfo(site.timezone)
        cams = {c.id: c for c in db.scalars(select(Camera).where(Camera.site_id == site.id))}
        now = datetime.now(UTC)
        day = now.astimezone(tz).date()
        prefix = f"EV-{day:%Y-%m-%d}-"
        seq = (db.scalar(select(func.count()).select_from(Evidence).where(Evidence.id.like(prefix + "%"))) or 0) + 1
        ev_id = evidence_id(day, seq)
        alert_refs: list[EvidenceAlertRef] = []
        clips: list[EvidenceClip] = []
        versions: dict[str, str] = {}
        for a in sorted(alerts, key=lambda x: x.ts_start):
            cam = cams.get(a.camera_id or "")
            alert_refs.append(
                EvidenceAlertRef(
                    alert_id=a.id,
                    type=a.type,
                    severity=a.severity,
                    camera_id=a.camera_id or "-",
                    camera_name=cam.name if cam else None,
                    ts_start=a.ts_start,
                    ts_end=a.ts_end,
                    alert_sha256=a.alert_sha256
                    or json_digest({k: v for k, v in a.payload.items() if k != "signature"}).hex(),
                    edge_signature=a.signature,
                    device_key_id=a.device_key_id,
                    explanation_ur=a.explanation_ur,
                    explanation_en=a.explanation_en,
                )
            )
            versions.update({k: str(v) for k, v in (a.payload.get("model_versions") or {}).items()})
            if a.clip_uri and a.attestation:
                att = dict(a.attestation)
                sig = att.pop("signature", None)
                clips.append(
                    EvidenceClip(
                        clip_id=a.clip_id or "",
                        alert_id=a.id,
                        camera_id=a.camera_id or "-",
                        uri=a.clip_uri,
                        sha256=a.clip_sha256 or "",
                        original_sha256=a.original_sha256,
                        ts_start=datetime.fromisoformat(att["ts_start"]),
                        ts_end=datetime.fromisoformat(att["ts_end"]),
                        attestation_sha256=json_digest(att).hex(),
                        attestation_signature=sig,
                        device_key_id=att.get("device_key_id"),
                        keyframes=[
                            {"name": k["name"], "sha256": k["sha256"], "uri": k.get("uri", "")}
                            for k in a.keyframes or []
                        ],
                    )
                )
        manifest = EvidenceManifest(
            evidence_id=ev_id,
            site_id=site.id,
            site_name=site.name,
            case_reference=case_reference,
            alerts=alert_refs,
            clips=clips,
            model_versions=versions,
            created_at=now.replace(microsecond=0),
            created_by=created_by,
            server_key_id=self.signer.key_id,
            notes=notes,
        )
        mdict = manifest.model_dump(mode="json")
        digest = json_digest(mdict)
        signature = self.signer.sign(mdict)
        ev = Evidence(
            id=ev_id,
            tenant_id=site.tenant_id,
            site_id=site.id,
            manifest=mdict,
            manifest_sha256=digest.hex(),
            server_signature=signature,
            server_key_id=self.signer.key_id,
            case_reference=case_reference,
            created_by=created_by,
            created_at=manifest.created_at,
        )
        pdf = self.render_pdf(ev, alerts, cams, tz)
        ev.pdf_uri = self.store.put_bytes(f"evidence/{site.id}/{ev_id}.pdf", pdf)
        ev.pdf_sha256 = sha256_hex(pdf)
        db.add(ev)
        for a in alerts:
            db.add(EvidenceAlert(evidence_id=ev_id, alert_id=a.id))
        db.flush()
        return ev

    def verify_url(self, ev_id: str) -> str:
        return f"{self.public_base_url}/verify/{ev_id}"

    def render_pdf(self, ev: Evidence, alerts: list[Alert], cams: dict[str, Camera], tz: ZoneInfo) -> bytes:
        from weasyprint import HTML  # heavy import, only when a PDF is made

        env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
        qr_img = qrcode.make(self.verify_url(ev.id), image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
        buf = io.BytesIO()
        qr_img.save(buf)
        qr_uri = "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()
        rows = []
        frames = []
        for a in sorted(alerts, key=lambda x: x.ts_start):
            cam = cams.get(a.camera_id or "")
            local = a.ts_end.astimezone(tz)
            ptxt = pvalue_text(a.p_value, (a.features or {}).get("calibration_mode", "normal"))
            ur, en = TYPE_NAMES.get(a.type, (a.type, a.type))
            rows.append(
                {
                    "alert_id": str(a.id),
                    "severity": a.severity,
                    "explanation_ur": a.explanation_ur,
                    "explanation_en": a.explanation_en,
                    "time_local": local.strftime("%Y-%m-%d %H:%M:%S"),
                    "camera": (cam.name if cam else a.camera_id) or "-",
                    "type_ur": ur,
                    "type_en": en,
                    "p_text": ptxt[2] if ptxt else None,
                }
            )
            for k in (a.keyframes or [])[:: max(1, len(a.keyframes or []) // 3)][:3]:
                uri = k.get("uri")
                if uri and self.store.exists(uri):
                    data = self.store.path(uri).read_bytes()
                    ts = k.get("ts")
                    label = datetime.fromisoformat(ts).astimezone(tz).strftime("%H:%M:%S") if ts else k["name"]
                    frames.append(
                        {
                            "src": "data:image/jpeg;base64," + base64.b64encode(data).decode(),
                            "label": f"{label} · {a.camera_id}",
                        }
                    )
        html = env.get_template("evidence.html").render(
            m=ev.manifest,
            alerts=rows,
            frames=frames[:9],
            qr=qr_uri,
            manifest_sha256=ev.manifest_sha256,
            server_signature=ev.server_signature,
            created_local=ev.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S"),
            verify_url=self.verify_url(ev.id),
        )
        return HTML(string=html, base_url=str(TEMPLATES)).write_pdf()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------ merkle + timestamps
    def close_batch(self, db: Session, day: date | None = None, stamp: bool = True) -> MerkleBatch | None:
        pending = db.scalars(
            select(Evidence).where(Evidence.merkle_batch_id.is_(None)).order_by(Evidence.created_at, Evidence.id)
        ).all()
        if not pending:
            return None
        leaves = [bytes.fromhex(e.manifest_sha256) for e in pending]
        root = merkle_root(leaves).hex()
        batch = MerkleBatch(
            day=day or datetime.now(UTC).date(), root=root, tree_size=len(leaves), ots_status="unavailable"
        )
        db.add(batch)
        db.flush()
        for i, e in enumerate(pending):
            path = inclusion_proof(leaves, i)
            proof = MerkleProof(
                batch_id=batch.id,
                day=batch.day.isoformat(),
                leaf_index=i,
                tree_size=len(leaves),
                path=[ProofStep(side=s, hash=h.hex()) for s, h in path],
                root=root,
            )
            e.merkle_batch_id = batch.id
            e.merkle_leaf_index = i
            e.merkle_proof = proof.model_dump(mode="json")
        if stamp:
            self._stamp(batch)
        db.flush()
        log.info("merkle batch closed", extra={"batch": batch.id, "size": batch.tree_size, "ots": batch.ots_status})
        return batch

    @staticmethod
    def _stamp(batch: MerkleBatch) -> None:
        try:
            res = ots_lib.stamp(batch.root)
            batch.ots_proof, batch.ots_status = res.proof, "pending"
        except ots_lib.OTSUnavailableError:
            batch.ots_status = "unavailable"
        except Exception as exc:  # network down: keep the batch, retry later
            log.warning("OTS stamp failed: %s", exc)
            batch.ots_status = "failed"

    def upgrade_timestamps(self, db: Session) -> int:
        n = 0
        for batch in db.scalars(select(MerkleBatch).where(MerkleBatch.ots_status.in_(["pending", "failed"]))):
            if batch.ots_status == "failed" or batch.ots_proof is None:
                self._stamp(batch)
                continue
            try:
                res = ots_lib.upgrade(batch.root, batch.ots_proof)
            except Exception as exc:
                log.warning("OTS upgrade failed: %s", exc)
                continue
            batch.ots_proof = res.proof
            if res.confirmed:
                batch.ots_status = "confirmed"
                n += 1
        return n

    # ------------------------------------------------------------------ verification
    def verify(self, db: Session, ev: Evidence) -> VerificationReport:
        checks: list[VerificationCheck] = []

        def add(name: str, ok: bool | None, en: str, ur: str, **data: Any) -> None:
            status = CheckStatus.PENDING if ok is None else CheckStatus.PASS if ok else CheckStatus.FAIL
            checks.append(VerificationCheck(name=name, status=status, detail_en=en, detail_ur=ur, data=data))

        manifest = ev.manifest
        recomputed = json_digest(manifest).hex()
        ok = recomputed == ev.manifest_sha256
        add(
            "manifest_hash",
            ok,
            "Manifest hash matches" if ok else "Manifest was modified",
            "منشور کا ہیش درست ہے" if ok else "منشور میں تبدیلی پائی گئی",
            sha256=recomputed,
        )

        pub = (
            self.signer.public_key
            if ev.server_key_id == self.signer.key_id
            else self.retired_keys.get(ev.server_key_id)
        )
        ok = pub is not None and verify_bytes(pub, bytes.fromhex(ev.manifest_sha256), ev.server_signature)
        add(
            "server_signature",
            ok,
            "Server signature (Ed25519) is valid" if ok else "Server signature is invalid",
            "سرور کے دستخط درست ہیں" if ok else "سرور کے دستخط درست نہیں",
            key_id=ev.server_key_id,
        )

        devices = {d.key_id: d for d in db.scalars(select(Device))}
        alert_ok, alert_n = 0, 0
        for ref in manifest.get("alerts", []):
            if not ref.get("device_key_id"):
                continue  # server-originated (SOS from the guard app): covered by the server signature
            alert_n += 1
            dev = devices.get(ref.get("device_key_id") or "")
            stored = db.get(Alert, _uuid(ref["alert_id"]))
            payload_ok = (
                stored is not None
                and json_digest({k: v for k, v in stored.payload.items() if k != "signature"}).hex()
                == ref["alert_sha256"]
            )
            sig_ok = (
                dev is not None
                and bool(ref.get("edge_signature"))
                and verify_bytes(dev.public_key, bytes.fromhex(ref["alert_sha256"]), ref["edge_signature"])
            )
            alert_ok += int(payload_ok and sig_ok)
        if alert_n:
            ok = alert_ok == alert_n
            add(
                "edge_signatures",
                ok,
                f"Edge device signatures valid ({alert_ok}/{alert_n})",
                f"کیمرہ ڈیوائس کے دستخط درست ہیں ({alert_ok}/{alert_n})"
                if ok
                else f"ڈیوائس دستخط میں مسئلہ ({alert_ok}/{alert_n})",
            )

        artifacts: list[dict[str, str]] = []
        clip_ok, clip_n = 0, 0
        for c in manifest.get("clips", []):
            clip_n += 1
            dev = devices.get(c.get("device_key_id") or "")
            att_ok = (
                dev is not None
                and bool(c.get("attestation_signature"))
                and verify_bytes(dev.public_key, bytes.fromhex(c["attestation_sha256"]), c["attestation_signature"])
            )
            path = self.store.path(c["uri"]) if c.get("uri") else None
            file_ok = path is not None and path.exists() and _file_sha(path) == c["sha256"]
            clip_ok += int(att_ok and file_ok)
            artifacts.append({"kind": "clip", "name": f"{c['clip_id']}.mp4", "sha256": c["sha256"]})
            artifacts.extend(
                {"kind": "keyframe", "name": k["name"], "sha256": k["sha256"]} for k in c.get("keyframes", [])
            )
        if clip_n:
            ok = clip_ok == clip_n
            add(
                "clip_files",
                ok,
                f"Clip files and attestations intact ({clip_ok}/{clip_n})"
                if ok
                else f"Clip file or attestation changed ({clip_ok}/{clip_n})",
                f"ویڈیو فائلیں درست ہیں ({clip_ok}/{clip_n})" if ok else f"ویڈیو فائل میں تبدیلی ({clip_ok}/{clip_n})",
            )

        if ev.pdf_uri and ev.pdf_sha256:
            p = self.store.path(ev.pdf_uri)
            ok = p.exists() and _file_sha(p) == ev.pdf_sha256
            add(
                "pdf",
                ok,
                "Stored PDF unchanged" if ok else "Stored PDF was modified",
                "پی ڈی ایف میں کوئی تبدیلی نہیں" if ok else "پی ڈی ایف میں تبدیلی پائی گئی",
            )
            artifacts.insert(0, {"kind": "pdf", "name": f"{ev.id}.pdf", "sha256": ev.pdf_sha256})

        batch = db.get(MerkleBatch, ev.merkle_batch_id) if ev.merkle_batch_id else None
        if batch is None or not ev.merkle_proof:
            add("merkle_proof", None, "Will join tonight's Merkle batch (00:05)", "آج رات کے مرکل بیچ میں شامل ہوگا")
            checks.append(
                VerificationCheck(
                    name="timestamp",
                    status=CheckStatus.PENDING,
                    detail_en="Timestamp after the Merkle batch",
                    detail_ur="مرکل بیچ کے بعد ٹائم اسٹیمپ",
                )
            )
        else:
            proof = ev.merkle_proof
            path = [(s["side"], bytes.fromhex(s["hash"])) for s in proof["path"]]
            ok = proof["root"] == batch.root and verify_inclusion(
                bytes.fromhex(ev.manifest_sha256), path, bytes.fromhex(batch.root)
            )
            add(
                "merkle_proof",
                ok,
                f"Included in Merkle batch #{batch.id} ({batch.day})" if ok else "Merkle proof does not match",
                f"مرکل بیچ #{batch.id} میں شامل ہے" if ok else "مرکل ثبوت درست نہیں",
                root=batch.root,
                batch=batch.id,
            )
            status = {"confirmed": CheckStatus.PASS, "pending": CheckStatus.PENDING, "failed": CheckStatus.PENDING}.get(
                batch.ots_status, CheckStatus.SKIPPED
            )
            en = {
                CheckStatus.PASS: "Bitcoin timestamp confirmed (OpenTimestamps)",
                CheckStatus.PENDING: "Bitcoin timestamp pending (a few hours)",
                CheckStatus.SKIPPED: "OpenTimestamps not enabled on this server",
            }[status]
            ur = {
                CheckStatus.PASS: "بٹ کوائن ٹائم اسٹیمپ کی تصدیق ہو گئی",
                CheckStatus.PENDING: "ٹائم اسٹیمپ زیرِ التوا (چند گھنٹے)",
                CheckStatus.SKIPPED: "اوپن ٹائم اسٹیمپس فعال نہیں",
            }[status]
            checks.append(
                VerificationCheck(
                    name="timestamp", status=status, detail_en=en, detail_ur=ur, data={"root": batch.root}
                )
            )

        failed = any(c.status == CheckStatus.FAIL for c in checks)
        site = db.get(Site, ev.site_id)
        return VerificationReport(
            evidence_id=ev.id,
            verified=not failed,
            summary_en="Evidence is intact" if not failed else "Evidence verification FAILED",
            summary_ur="ثبوت درست اور بغیر تبدیلی کے ہے" if not failed else "ثبوت کی تصدیق ناکام",
            checks=checks,
            manifest_sha256=ev.manifest_sha256,
            pdf_sha256=ev.pdf_sha256,
            site_name=site.name if site else ev.site_id,
            created_at=ev.created_at,
            alert_count=len(manifest.get("alerts", [])),
            clip_count=len(manifest.get("clips", [])),
            artifacts=artifacts,
        )

    @staticmethod
    def match(ev: Evidence, report: VerificationReport, sha256: str) -> FileMatch:
        sha = sha256.lower()
        for a in report.artifacts:
            if a["sha256"] == sha:
                return FileMatch(evidence_id=ev.id, sha256=sha, matched=True, kind=a["kind"], name=a["name"])
        return FileMatch(evidence_id=ev.id, sha256=sha, matched=False)


def _file_sha(path: Path) -> str:
    from jikimi_crypto import sha256_file

    return sha256_file(path)


def _uuid(v: str) -> Any:
    import uuid

    return uuid.UUID(v)


def next_close_time(now: datetime, tz: ZoneInfo, at: tuple[int, int] = (0, 5)) -> datetime:
    local = now.astimezone(tz)
    target = local.replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target
