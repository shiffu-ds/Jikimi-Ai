"""The edge pipeline (plan Section 8.1)::

    frame -> perception (sim truth | YOLO + ByteTrack [+ pose]) -> riders, re-ID, zones
          -> analytics plugins -> conformal p-value -> router -> alert gate
          -> Ed25519 signature -> SQLite outbox  (alert reaches the guard in seconds)
          -> clip job (-20/+10 s) -> blur -> H.264 -> hash -> encrypted original -> attestation

``process()`` is deterministic for a given frame sequence (no wall clock inside), which is what
makes golden replays and simulator calibration possible. IO-heavy work (clip encoding) runs on
a small thread pool so it never delays the next alert.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from jikimi_common.explain import explain_alert
from jikimi_common.ids import clip_id_for, new_trace_id, short_code, uuid7
from jikimi_contracts import (
    TWO_WHEELERS,
    AlertCandidate,
    AlertType,
    ClipAttestation,
    DeliveryInfo,
    EdgeAlertEnvelope,
    KeyframeRef,
    ObjectSummary,
    Route,
    TrackSummary,
)
from jikimi_contracts.events import CameraHealth
from jikimi_contracts.modes import ModeWindow, mode_on
from jikimi_contracts.rules_dsl import Rule
from jikimi_crypto import sha256_bytes, sha256_file

from .analytics.base import AnalyticsPlugin, CameraConfig, FrameContext
from .analytics.camera_health.plugin import CameraHealthPlugin
from .analytics.cross_camera import MIN_SEGMENTS, CrossCameraLinker, Segment, TrajectoryScorer, turns_of
from .analytics.registry import build_plugins, resolve_needs
from .analytics.rules.plugin import RulesPlugin
from .analytics.snatch.pair_builder import pairs_in_reach, people_in_reach
from .calibration.store import CalibrationStore
from .evidence.signer import DeviceSigner
from .ingest.clip_recorder import ClipJob, ClipRecorder, decode
from .ingest.clip_writer import write_mp4
from .ingest.sources import Frame
from .outbox.db import Outbox
from .privacy.face_blur import PrivacyBlur, rider_head_proxy
from .privacy.vault import Vault
from .routing.router import DETERMINISTIC_TYPES, AlertGate, route, severity_for
from .settings import EdgeSettings
from .tracking.bytetrack import ByteTracker
from .tracking.reid import EntityLinker, cosine
from .tracking.riders import RiderMemory, associate_riders
from .tracking.track_store import TrackHistory, TrackStore

log = logging.getLogger(__name__)
NETWORK_MATCH = 0.92  # appearance similarity for a neighbour's bike (stricter than re-entry linking)

INDEXED = frozenset({"motorcycle", "bicycle", "car", "van", "bus", "truck", "rickshaw", "qingqi", "loader_rickshaw"})
PRIORITY = {"high": 0, "medium": 1, "low": 3}
MOTION_TYPES = frozenset(
    {AlertType.SNATCH, AlertType.LOITERING, AlertType.PERSON_DANGER, AlertType.VEHICLE_THEFT, AlertType.CROWD_PANIC}
)
"""Alerts made from movement in the image: meaningless while the camera itself moves."""


@dataclass
class CameraRuntime:
    cfg: CameraConfig
    store: TrackStore
    plugins: list[AnalyticsPlugin]
    needs: set[str]
    recorder: ClipRecorder
    tracker: ByteTracker = field(default_factory=ByteTracker)
    frames: int = 0
    first_frame_ts: float | None = None
    last_frame_ts: float | None = None
    fps_ema: float = 0.0
    last_snapshot: float = -1e18
    last_state_save: float = -1e18
    offline_alerted: bool = False
    current_persons: list[tuple[float, float, float, float]] = field(default_factory=list)
    rider_memory: RiderMemory = field(default_factory=RiderMemory)
    bike_ends: deque[float] = field(default_factory=deque)
    """When each motorcycle track ended, last hour (traffic volume for the rush hint, F16)."""

    def mark_frame(self, ts: float) -> None:
        if self.last_frame_ts is not None and ts > self.last_frame_ts:
            inst = 1.0 / (ts - self.last_frame_ts)
            self.fps_ema = inst if self.fps_ema == 0 else 0.9 * self.fps_ema + 0.1 * inst
        if self.first_frame_ts is None:
            self.first_frame_ts = ts
        self.last_frame_ts = ts
        self.frames += 1
        self.offline_alerted = False

    @property
    def health_plugin(self) -> CameraHealthPlugin | None:
        for p in self.plugins:
            if isinstance(p, CameraHealthPlugin):
                return p
        return None


class EdgePipeline:
    def __init__(
        self,
        settings: EdgeSettings,
        *,
        outbox: Outbox | None = None,
        signer: DeviceSigner | None = None,
        calibration: CalibrationStore | None = None,
        blur: PrivacyBlur | None = None,
        vault: Vault | None = None,
        detector: Any = None,
        pose: Any = None,
        enhancer: Any = None,
        record_clips: bool = True,
        clip_workers: int = 1,
        index_tracks: bool = True,
        model_versions: dict[str, str] | None = None,
    ) -> None:
        self.s = settings
        self.outbox = outbox
        self.signer = signer
        self.calibration = calibration or CalibrationStore(settings.calibration_dir, settings.site_id)
        self.blur = blur or PrivacyBlur(
            settings.face_detector, settings.repo_root / "models/face_detection_yunet_2023mar.onnx"
        )
        self.vault = vault
        self.detector = detector
        self.pose = pose
        self.enhancer = enhancer
        self.record_clips = record_clips and outbox is not None
        self.index_tracks = index_tracks
        self.gate = AlertGate(settings.routing.cooldown_s)
        self.model_versions = model_versions or {}
        self.alerts: list[AlertCandidate] = []
        self.stats: dict[str, int] = {"frames": 0, "candidates": 0, "alerts": 0, "dropped": 0, "clips": 0, "tracks": 0}
        self._pool = (
            ThreadPoolExecutor(max_workers=clip_workers, thread_name_prefix="clip") if self.record_clips else None
        )
        self._futures: list[Future[None]] = []
        self._lock = threading.RLock()
        self._calendar: list[ModeWindow] = []
        self.cameras: dict[str, CameraRuntime] = {}
        for cam in settings.cameras:
            plugins = build_plugins(cam.plugins or settings.plugins, settings.raw, cam)
            reid_cfg = settings.raw.get("reid") or {}
            linker = EntityLinker(
                cam.id,
                window_s=float(reid_cfg.get("window_min", 15)) * 60,
                threshold=float(reid_cfg.get("threshold", 0.95)),
            )
            rt = CameraRuntime(
                cfg=cam,
                store=TrackStore(cam, linker=linker, thumb_fn=None),
                plugins=plugins,
                needs=resolve_needs(plugins),
                recorder=ClipRecorder(cam.id, settings.pre_s, settings.post_s),
            )
            rt.store.thumb_fn = self._make_thumb_fn(rt)
            if outbox is not None:
                for p in plugins:
                    state = outbox.load_state(p.name, cam.id)
                    if state:
                        p.load_state(state)
            self.cameras[cam.id] = rt
        self.xcam = self._cross_camera()
        self._network: list[Any] = []  # F21 shares from opted-in neighbours
        self._network_hits: set[str] = set()

    def _cross_camera(self) -> tuple[CrossCameraLinker, TrajectoryScorer] | None:
        """F2 Tier 2: two or more cameras and a trajectory model trained for *this* site's cameras."""
        cfg = self.s.raw.get("cross_camera") or {}
        model = self.s.repo_root / str(cfg.get("model", "models/trajectory_tf.onnx"))
        if len(self.cameras) < 2 or cfg.get("enabled") is False or not model.exists():
            return None
        meta = model.with_suffix(".json")
        known = json.loads(meta.read_text(encoding="utf-8")).get("cameras", []) if meta.exists() else []
        if not set(self.cameras) <= set(known):
            log.warning("trajectory model was trained for cameras %s, not this site's: cross-camera off", known)
            return None
        try:
            scorer = TrajectoryScorer(str(model), known)
        except Exception:
            log.exception("trajectory model could not be loaded: cross-camera off")
            return None
        linker = CrossCameraLinker(
            self.s.raw.get("camera_graph") or [],
            threshold=float(cfg.get("threshold", 0.9)),
            window_s=float(cfg.get("window_min", 30)) * 60,
        )
        return linker, scorer

    def _cross_camera_step(self, rt: CameraRuntime, h: TrackHistory, ts: float) -> AlertCandidate | None:
        """A bike left this camera: extend its route across cameras and score the route."""
        if self.xcam is None or h.desc is None or h.last_seen - h.first_seen < 1.0:
            return None
        linker, scorer = self.xcam
        local = datetime.fromtimestamp(h.first_seen, UTC).astimezone(self.s.tz)
        seg = Segment(
            rt.cfg.id,
            h.first_seen,
            h.last_seen,
            h.median_speed(),
            turns_of([p[1] for p in h.points]),
            local.hour + local.minute / 60,
        )
        traj = linker.add(rt.cfg.id, seg, h.desc, h.riders(), h.color())
        cams = sorted({s.camera for s in traj.segments})
        if len(traj.segments) < MIN_SEGMENTS or len(cams) < 2:
            return None
        traj.max_score = max(traj.max_score, scorer(traj.segments))
        cand = AlertCandidate(
            alert_id=uuid7(),
            site_id=self.s.site_id,
            camera_id=rt.cfg.id,
            type=AlertType.LOITERING,
            ts_start=datetime.fromtimestamp(traj.segments[0].start, UTC),
            ts_end=datetime.fromtimestamp(ts, UTC),
            raw_score=traj.max_score,
            mode=self.mode(ts),
            entity_id=traj.gid,
            features={
                "cross_camera": True,
                "passes": len(traj.segments),
                "cameras": cams,
                "window_min": max(1, round(traj.span_s / 60)),
                "riders": traj.riders or 1,
                "vehicle": "motorcycle",
                "color": traj.color,
                "calibration_key": "loitering_xcam",
                "dedupe_key": traj.gid,
            },
            objects=[ObjectSummary(type="motorcycle", color=traj.color, riders=traj.riders or None)],
            model_versions={"loitering": "xcam-tf-v1"},
        )
        return self._finalize(rt, cand, ts)

    # ------------------------------------------------------------------ helpers
    def local_time(self, dt: datetime) -> datetime:
        return dt.astimezone(self.s.tz)

    def where(self, alert: AlertCandidate) -> str:
        return self.s.zone_label(alert.camera_id, alert.zone_id)

    def _make_thumb_fn(self, rt: CameraRuntime) -> Any:
        def thumb(frame: np.ndarray, box: tuple[float, float, float, float]) -> bytes | None:
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = box
            pad_x, pad_y = (x2 - x1) * 0.12, (y2 - y1) * 0.12
            X1, Y1 = int(max(0, x1 - pad_x) * w), int(max(0, y1 - pad_y) * h)
            X2, Y2 = int(min(1, x2 + pad_x) * w), int(min(1, y2 + pad_y) * h)
            if X2 - X1 < 8 or Y2 - Y1 < 8:
                return None
            crop = frame[Y1:Y2, X1:X2]
            cw, ch = X2 - X1, Y2 - Y1
            local = [
                ((px1 * w - X1) / cw, (py1 * h - Y1) / ch, (px2 * w - X1) / cw, (py2 * h - Y1) / ch)
                for (px1, py1, px2, py2) in rt.current_persons
                if px2 > x1 - pad_x and px1 < x2 + pad_x and py2 > y1 - pad_y and py1 < y2 + pad_y
            ]
            blurred, _ = self.blur.apply(crop, local)
            scale = 128 / max(cw, ch)
            if scale < 1:
                blurred = cv2.resize(
                    blurred, (max(1, int(cw * scale)), max(1, int(ch * scale))), interpolation=cv2.INTER_AREA
                )
            ok, enc = cv2.imencode(".jpg", blurred, [cv2.IMWRITE_JPEG_QUALITY, 72])
            return enc.tobytes() if ok else None

        return thumb

    # ------------------------------------------------------------------ main step
    def process(self, camera_id: str, frame: Frame) -> list[AlertCandidate]:
        with self._lock:
            return self._process(camera_id, frame)

    def _process(self, camera_id: str, frame: Frame) -> list[AlertCandidate]:
        rt = self.cameras[camera_id]
        ts = frame.ts
        rt.mark_frame(ts)
        self.stats["frames"] += 1
        seen = frame.image  # what the detector and pose model see (F18: brightened copy when dark)
        if frame.tracks is not None:
            tracks, poses = frame.tracks, dict(frame.poses or {})
        elif self.detector is not None and frame.image is not None:
            if self.enhancer is not None:
                seen = self.enhancer(frame.image)
            tracks, poses = rt.tracker.update(self.detector(seen), ts), {}
        else:
            tracks, poses = [], {}
        # heads to blur in clips, snapshots, thumbnails: every person, plus riders above every
        # two-wheeler (undetected riders squeezed in traffic, seen on real footage)
        rt.current_persons = [t.bbox for t in tracks if t.cls == "person"] + [
            rider_head_proxy(t.bbox) for t in tracks if t.cls in TWO_WHEELERS
        ]
        riders_of = associate_riders(tracks)
        rider_ids = rt.rider_memory.update(
            [t.track_id for t in tracks if t.cls == "person"], [i for ids in riders_of.values() for i in ids], ts
        )
        tracks, zone_events, new_ids = rt.store.update(tracks, ts, frame.image, riders_of)
        if (
            rt.needs & {"poses", "person_poses"}
            and not poses
            and self.pose is not None
            and frame.image is not None
            and (
                ("poses" in rt.needs and pairs_in_reach(tracks, riders_of, rider_ids))
                or ("person_poses" in rt.needs and people_in_reach(tracks, rider_ids))
            )
        ):
            persons = [t for t in tracks if t.cls == "person"]
            poses = self.pose(seen, persons)
        ctx = FrameContext(
            site_id=self.s.site_id,
            camera_id=camera_id,
            ts=ts,
            frame=frame.image,
            tracks=tracks,
            poses=poses,
            mode=self.mode(ts),
            riders_of=riders_of,
            rider_ids=rider_ids,
            histories=rt.store.histories,
            zone_events=zone_events,
            new_track_ids=new_ids,
            tz_offset_s=self._tz_offset(ts),
        )
        candidates: list[AlertCandidate] = []
        for plugin in rt.plugins:
            try:
                candidates.extend(plugin.on_step(ctx))
            except Exception:  # one faulty plugin must never stop the alert path
                log.exception("plugin failed", extra={"plugin": plugin.name, "camera": camera_id})
        if self.record_clips:
            rt.recorder.push(ts, frame.image, rt.current_persons)
        sent: list[AlertCandidate] = []
        for cand in candidates:
            self.stats["candidates"] += 1
            alert = self._finalize(rt, cand, ts)
            if alert is not None:
                sent.append(alert)
        for hist in rt.store.pop_finished(ts):
            if hist.cls == "motorcycle":
                rt.bike_ends.append(ts)
                for extra in (self._cross_camera_step(rt, hist, ts), self._network_match(rt, hist, ts)):
                    if extra is not None:
                        sent.append(extra)
            self._track_summary(rt, hist)
        if self.record_clips:
            for job in rt.recorder.ready():
                self._submit_clip(job)
        self._periodic(rt, frame, ts)
        return sent

    def mode(self, ts: float) -> str:
        """Event mode (F16) of the site-local day: the server's confirmed calendar, else the
        config default (``event_mode.current``, normally "normal")."""
        default = str((self.s.raw.get("event_mode") or {}).get("current", "normal"))
        if not self._calendar:
            return default
        return mode_on(self._calendar, datetime.fromtimestamp(ts, UTC).astimezone(self.s.tz).date(), default)

    def volume(self, now: float, min_window_s: float = 900.0) -> dict[str, float]:
        """Bike traffic per camera as a multiple of the calibration's units/hour (F16 finding: the
        score distribution barely moves on a festival day, the volume does). Needs 15 min."""
        base = self.calibration.units_per_hour("loitering", "normal")
        out: dict[str, float] = {}
        for cam, rt in self.cameras.items():
            while rt.bike_ends and now - rt.bike_ends[0] > 3600.0:
                rt.bike_ends.popleft()
            window = min(3600.0, now - (rt.first_frame_ts or now))
            if base and window >= min_window_s:
                out[cam] = round(len(rt.bike_ends) * 3600.0 / window / base, 2)
        return out

    def reanchor(self, camera_id: str, by: str = "admin") -> bool:
        """Accept the camera's current view as its new reference (after it was moved)."""
        with self._lock:
            rt = self.cameras.get(camera_id)
            if rt is None or rt.health_plugin is None:
                return False
            rt.health_plugin.request_reanchor(by)
            return True

    def set_network(self, shares: list[Any]) -> None:
        """Neighbours' confirmed incidents (F21), from the signed network bundle."""
        with self._lock:
            self._network = list(shares)

    def _network_match(self, rt: CameraRuntime, h: TrackHistory, ts: float) -> AlertCandidate | None:
        """A bike left this camera: is it the bike of a neighbour's confirmed incident?"""
        if not self._network or h.desc is None:
            return None
        riders = h.riders()
        for share in self._network:
            if share.id in self._network_hits or share.expires_at.timestamp() < ts:
                continue
            if riders and share.riders and riders != share.riders:
                continue
            ref = np.frombuffer(base64.b64decode(share.descriptor_b64), dtype=np.float16).astype(np.float32)
            if ref.shape != h.desc.shape or cosine(h.desc, ref) < NETWORK_MATCH:
                continue
            self._network_hits.add(share.id)
            cand = AlertCandidate(
                alert_id=uuid7(),
                site_id=self.s.site_id,
                camera_id=rt.cfg.id,
                type=AlertType.NETWORK,
                ts_start=datetime.fromtimestamp(h.first_seen, UTC),
                ts_end=datetime.fromtimestamp(ts, UTC),
                raw_score=1.0,
                mode=self.mode(ts),
                entity_id=h.entity_id,
                track_ids=[h.track_id],
                features={
                    "network_match": True,
                    "share_id": share.id,
                    "incident_type": share.alert_type,
                    "distance_km": share.distance_km,
                    "riders": riders or share.riders or 1,
                    "vehicle": "motorcycle",
                    "color": h.color() or share.color,
                    "dedupe_key": share.id,
                },
                objects=[ObjectSummary(type="motorcycle", color=h.color() or share.color, riders=riders or None)],
            )
            return self._finalize(rt, cand, ts)
        return None

    def _share_embedding(self, rt: CameraRuntime, alert: AlertCandidate) -> None:
        """Send a bike alert's appearance embedding (F21); the server keeps it only if the site
        opted in, and for 24 h at most. Never part of the signed alert, which is kept for a year."""
        if self.outbox is None or alert.type not in (AlertType.SNATCH, AlertType.LOITERING, AlertType.VEHICLE_THEFT):
            return
        desc, riders, color = None, None, None
        for tid in alert.track_ids:
            h = rt.store.histories.get(tid)
            if h is not None and h.cls in TWO_WHEELERS and h.desc is not None:
                desc, riders, color = h.desc, h.riders(), h.color()
                break
        if desc is None and alert.features.get("cross_camera") and self.xcam is not None:
            traj = self.xcam[0]._open.get(str(alert.entity_id))
            if traj is not None:
                desc, riders, color = traj.descriptor, traj.riders, traj.color
        if desc is None:
            return
        self.outbox.enqueue(
            "embedding",
            {
                "alert_id": str(alert.alert_id),
                "site_id": alert.site_id,
                "descriptor_b64": base64.b64encode(np.asarray(desc, np.float16).tobytes()).decode("ascii"),
                "riders": riders or None,
                "color": color,
            },
            severity="low",
            priority=9,
            dedupe_key=f"emb:{alert.alert_id}",
        )

    def set_calendar(self, windows: list[ModeWindow]) -> None:
        """Confirmed event-mode windows from the server (F16), applied between two frames."""
        with self._lock:
            self._calendar = list(windows)

    def _tz_offset(self, ts: float) -> float:
        off = datetime.fromtimestamp(ts, UTC).astimezone(self.s.tz).utcoffset()
        return off.total_seconds() if off else 0.0

    def _finalize(self, rt: CameraRuntime, cand: AlertCandidate, ts: float) -> AlertCandidate | None:
        deterministic = cand.type in DETERMINISTIC_TYPES
        scorer = cand.model_versions.get(cand.type.value)
        cal_key = str(cand.features.get("calibration_key") or cand.type.value)  # e.g. loitering_xcam
        p = None if deterministic else self.calibration.p_value(cal_key, cand.mode, cand.raw_score, scorer)
        if not deterministic:
            self.calibration.observe(cal_key, cand.raw_score)
        r = route(cand.type, cand.raw_score, p, self.s.routing)
        moving = (
            cand.type in MOTION_TYPES
            and rt.health_plugin is not None
            and rt.health_plugin.status.get("moving") == "warn"
        )
        if moving:
            # the camera itself is moving (vehicle-mounted, handheld, swaying): speeds, slow-downs
            # and jerks measured in the image are not the people's own, so no ALERT_NOW from them
            r = Route.LOG_ONLY
        if r == Route.LOG_ONLY and (not self.s.send_log_only or p is None or p > self.s.routing.log_only_max_p):
            self.stats["dropped"] += 1
            return None
        features = dict(cand.features)
        if moving:
            features["camera_moving"] = True
        if not deterministic:
            features["calibrated"] = p is not None
            if cand.mode != "normal":  # which "normal" the p-value compares against (F16)
                features["calibration_mode"] = self.calibration.calibrated_mode(cal_key, cand.mode)
        sev = severity_for(
            cand.type,
            r,
            features.get("rule_severity") or features.get("severity"),
            pattern=features.get("pattern"),
            risky=bool(features.get("night") and features.get("alone")),
        )
        names = self.s.camera_names(cand.camera_id)
        expl = explain_alert(cand.type.value, features, names, self.local_time(cand.ts_end), p, cand.raw_score)
        alert = cand.model_copy(
            update={
                "p_value": p,
                "route": r,
                "severity": sev,
                "features": features,
                "explanation_roman": expl.roman,
                "trace_id": new_trace_id(),
                "model_versions": {**self.model_versions, **cand.model_versions},
            }
        )
        admitted = self.gate.admit(alert, ts)
        if admitted is None:
            self.stats["dropped"] += 1
            return None
        alert = admitted
        if self.signer is not None:
            alert = self.signer.sign_alert(alert)
        if self.outbox is not None:
            envelope = EdgeAlertEnvelope(alert=alert, delivery=DeliveryInfo(queued_at=datetime.now(UTC)))
            self.outbox.enqueue(
                "alert",
                envelope.model_dump(mode="json"),
                severity=alert.severity.value,
                priority=PRIORITY[alert.severity.value],
                dedupe_key=str(alert.alert_id),
            )
        if r != Route.LOG_ONLY and self.record_clips and cand.type != AlertType.SOS:
            rt.recorder.request(alert.alert_id, ts, alert.ts_start.timestamp())
        if r != Route.LOG_ONLY:
            self._share_embedding(rt, alert)
        self.stats["alerts"] += 1
        self.alerts.append(alert)
        level = logging.WARNING if r != Route.LOG_ONLY else logging.INFO
        log.log(
            level,
            "ALERT %s %s %s p=%s [%s]",
            alert.type.value,
            r.value,
            alert.severity.value,
            "-" if p is None else f"{p:.4f}",
            short_code(alert.alert_id),
            extra={"camera": rt.cfg.id, "score": round(alert.raw_score, 3)},
        )
        return alert

    # ------------------------------------------------------------------ clips
    def _submit_clip(self, job: ClipJob) -> None:
        if self._pool is None:
            return
        fut = self._pool.submit(self._finalize_clip, job)
        self._futures.append(fut)
        self._futures = [f for f in self._futures if not f.done()]

    def _finalize_clip(self, job: ClipJob) -> None:
        try:
            self._write_clip(job)
            self.stats["clips"] += 1
        except Exception:
            log.exception("clip finalize failed", extra={"alert": short_code(job.alert_id)})

    def _write_clip(self, job: ClipJob) -> None:
        assert self.outbox is not None
        frames = [decode(f) for f in job.frames]
        blurred = []
        heads = 0
        for img, bf in zip(frames, job.frames, strict=True):
            out, st = self.blur.apply(img, bf.persons, inplace=False)
            blurred.append(out)
            heads += st.heads + st.faces
        span = max(job.frames[-1].ts - job.frames[0].ts, 1e-3)
        fps = max(1.0, (len(frames) - 1) / span) if len(frames) > 1 else 1.0
        start_dt = datetime.fromtimestamp(job.frames[0].ts, UTC)
        clip_id = clip_id_for(job.alert_id, self.local_time(start_dt))
        folder = self.s.data_dir / "clips" / self.local_time(start_dt).strftime("%Y-%m-%d")
        clip_path = write_mp4(blurred, fps, folder / f"{clip_id}.mp4")
        original_sha = None
        if self.vault is not None:
            tmp = folder / f".{clip_id}.orig.mp4"
            write_mp4(frames, fps, tmp)
            original_sha = sha256_file(tmp)
            self.vault.seal_file(tmp, self.s.data_dir / "originals" / f"{clip_id}.mp4.enc", aad=clip_id)
            tmp.unlink(missing_ok=True)
        idx = np.linspace(0, len(blurred) - 1, num=min(8, len(blurred))).round().astype(int)
        keyframes: list[KeyframeRef] = []
        kf_paths: list[str] = []
        for n, i in enumerate(sorted(set(idx.tolist()))):
            ok, enc = cv2.imencode(".jpg", blurred[i], [cv2.IMWRITE_JPEG_QUALITY, 82])
            if not ok:
                continue
            name = f"{clip_id}_k{n}.jpg"
            path = folder / name
            path.write_bytes(enc.tobytes())
            keyframes.append(
                KeyframeRef(
                    name=name,
                    sha256=sha256_bytes(enc.tobytes()).hex(),
                    ts=datetime.fromtimestamp(job.frames[i].ts, UTC),
                )
            )
            kf_paths.append(str(path))
        att = ClipAttestation(
            alert_id=job.alert_id,
            clip_id=clip_id,
            site_id=self.s.site_id,
            camera_id=job.camera_id,
            ts_start=start_dt,
            ts_end=datetime.fromtimestamp(job.frames[-1].ts, UTC),
            clip_sha256=sha256_file(clip_path),
            original_sha256=original_sha,
            keyframes=keyframes,
            frames=len(frames),
            fps=round(fps, 2),
            blur={"method": self.blur.method, "regions": heads},
        )
        if self.signer is not None:
            att = self.signer.sign_attestation(att)
        self.outbox.enqueue(
            "clip",
            att.model_dump(mode="json"),
            severity="medium",
            priority=4,
            dedupe_key=f"clip:{job.alert_id}",
            files=[str(clip_path), *kf_paths],
        )
        log.info("clip ready", extra={"clip": clip_id, "frames": len(frames), "fps": round(fps, 1)})

    # ------------------------------------------------------------------ tracks / snapshots
    def _track_summary(self, rt: CameraRuntime, h: TrackHistory) -> None:
        if not self.index_tracks or self.outbox is None or h.entity_id is None:
            return
        duration = h.last_seen - h.first_seen
        is_vehicle = h.cls in INDEXED
        if (is_vehicle and duration < 1.0) or (not is_vehicle and (h.cls != "person" or duration < 8.0)):
            return
        zones = sorted({z for _, z in h.zone_entries})
        summary = TrackSummary(
            site_id=self.s.site_id,
            camera_id=rt.cfg.id,
            entity_id=h.entity_id,
            track_ids=[h.track_id],
            object=h.summary(),
            zones=zones,
            ts_start=datetime.fromtimestamp(h.first_seen, UTC),
            ts_end=datetime.fromtimestamp(h.last_seen, UTC),
            passes=len(h.zone_entries),
            thumbnail_jpeg_b64=base64.b64encode(h.thumb_jpeg).decode() if h.thumb_jpeg else None,
        )
        self.outbox.enqueue(
            "track",
            summary.model_dump(mode="json"),
            severity="low",
            priority=7,
            dedupe_key=f"track:{rt.cfg.id}:{h.track_id}:{int(h.first_seen)}",
        )
        self.stats["tracks"] += 1

    def _periodic(self, rt: CameraRuntime, frame: Frame, ts: float) -> None:
        if self.outbox is None:
            return
        if self.s.snapshots and frame.image is not None and ts - rt.last_snapshot >= self.s.snapshot_interval_s:
            rt.last_snapshot = ts
            img, _ = self.blur.apply(frame.image, rt.current_persons)
            h, w = img.shape[:2]
            if w > 640:
                img = cv2.resize(img, (640, int(h * 640 / w)), interpolation=cv2.INTER_AREA)
            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                self.outbox.enqueue(
                    "snapshot",
                    {"camera_id": rt.cfg.id, "ts": ts, "jpeg_b64": base64.b64encode(enc.tobytes()).decode()},
                    severity="low",
                    priority=9,
                    dedupe_key=f"snapshot:{rt.cfg.id}",
                    replace=True,
                )
        if ts - rt.last_state_save >= 30.0:
            rt.last_state_save = ts
            for p in rt.plugins:
                try:
                    self.outbox.save_state(p.name, rt.cfg.id, p.state_dict())
                except Exception:
                    log.exception("plugin state save failed", extra={"plugin": p.name})

    # ------------------------------------------------------------------ health
    def set_rules(self, rules: list[Rule]) -> None:
        """Apply the server's approved rules (F11) to every camera, between two frames."""
        with self._lock:
            for rt in self.cameras.values():
                for p in rt.plugins:
                    if isinstance(p, RulesPlugin):
                        p.set_remote(rules)

    def check_offline(self, now: float, after_s: float = 15.0) -> list[AlertCandidate]:
        """Camera produced no frames for ``after_s``: high-severity tamper alert (F10)."""
        out: list[AlertCandidate] = []
        with self._lock:
            for rt in self.cameras.values():
                last = rt.last_frame_ts
                if last is None or rt.offline_alerted or now - last < after_s:
                    continue
                rt.offline_alerted = True
                ctx = FrameContext(site_id=self.s.site_id, camera_id=rt.cfg.id, ts=now, frame=None)
                cand = ctx.make_alert(
                    AlertType.TAMPER,
                    1.0,
                    last,
                    features={"check": "offline", "silent_s": round(now - last, 1), "dedupe_key": "offline"},
                    model_versions={"camera_health": "heartbeat-v1"},
                )
                alert = self._finalize(rt, cand, now)
                if alert is not None:
                    out.append(alert)
        return out

    def camera_health(self, now: float) -> list[CameraHealth]:
        out = []
        for rt in self.cameras.values():
            online = rt.last_frame_ts is not None and now - rt.last_frame_ts < 15
            checks = dict(rt.health_plugin.status) if rt.health_plugin else {}
            checks["offline"] = "ok" if online else "alarm"
            out.append(
                CameraHealth(
                    camera_id=rt.cfg.id,
                    online=online,
                    fps=round(rt.fps_ema, 2),
                    last_frame_at=datetime.fromtimestamp(rt.last_frame_ts, UTC) if rt.last_frame_ts else None,
                    checks=checks,
                )
            )
        return out

    def flush(self, timeout: float = 60.0) -> None:
        """End of a replay: finish clips and track summaries."""
        with self._lock:
            for rt in self.cameras.values():
                if self.record_clips:
                    for job in rt.recorder.ready(force=True):
                        self._submit_clip(job)
                for hist in rt.store.pop_finished(0.0, force=True):
                    self._track_summary(rt, hist)
        deadline = time.monotonic() + timeout
        for fut in list(self._futures):
            fut.result(timeout=max(0.1, deadline - time.monotonic()))

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)


def data_paths(settings: EdgeSettings) -> dict[str, Path]:
    d = settings.data_dir
    return {
        "outbox": d / "outbox.db",
        "device_key": d / "keys" / "device.key",
        "vault_key": d / "keys" / "vault.key",
        "sms": d / "sms",
        "rules": d / "rules",
        "calendar": d / "calendar",
        "commands": d / "commands",
        "network": d / "network",
        "server_key": d / "keys" / "server.pub",
    }
