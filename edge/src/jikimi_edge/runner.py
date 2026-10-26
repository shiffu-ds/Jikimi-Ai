"""Wiring: build the pipeline from settings, run cameras live, or replay scenarios fast."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jikimi_contracts import AlertCandidate
from jikimi_contracts.commands import EdgeCommand
from jikimi_contracts.events import EdgeHeartbeat

from . import __version__
from .analytics.rules.sync import RuleSync
from .calibration.store import CalibrationStore
from .config_sync import CalendarSync, CommandSync, NetworkSync
from .evidence.signer import DeviceSigner
from .health import watchdog
from .ingest.sources import FrameSource, RtspSource, VideoFileSource
from .outbox.db import Outbox
from .outbox.server_client import ServerClient
from .outbox.sms_gateway import make_gateway
from .outbox.sync_agent import SyncAgent, SyncConfig
from .pipeline import EdgePipeline, data_paths
from .power.profiles import fps_for
from .power.ups_monitor import PowerMonitor
from .privacy.vault import Vault, load_or_create_key
from .settings import EdgeSettings
from .sim.source import SimSource

log = logging.getLogger(__name__)


def make_source(
    settings: EdgeSettings, camera_id: str, realtime: bool = True, start_ts: float | None = None, seed: int = 1
) -> FrameSource:
    cam = settings.camera(camera_id)
    src = cam.source or ""
    if src.startswith("sim:"):
        return SimSource(
            camera_id,
            src[4:],
            fps=settings.process_fps,
            realtime=realtime,
            loop=realtime,
            start_ts=start_ts,
            seed=seed,
            tz=settings.tz,
        )
    if src.startswith("file:"):
        return VideoFileSource(camera_id, src[5:], fps=settings.process_fps, realtime=realtime, loop=realtime)
    if src.startswith(("rtsp://", "rtsps://", "http://", "https://", "webcam:")):
        return RtspSource(camera_id, src, fps=settings.process_fps)
    raise ValueError(
        f"camera {camera_id}: no usable source (set rtsp_url_env / source: sim:<scenario> / file:<path> / webcam:0)"
    )


def load_enhancer(settings: EdgeSettings) -> Any:
    """Brightens dark frames for the detector (F18); off unless ``low_light.enabled`` (no measured gain yet)."""
    cfg = settings.raw.get("low_light") or {}
    if not cfg.get("enabled", False):
        return None
    from .inference.lowlight import LowLightEnhancer

    method = str(cfg.get("method", "clahe"))
    path = settings.repo_root / str(cfg.get("model", "models/zero_dce_pp.onnx"))
    try:
        return LowLightEnhancer(method, str(path) if method == "zero_dce" else None, tau=float(cfg.get("tau", 0.25)))
    except Exception:
        log.exception("low-light enhancer unavailable; detection runs on the original frames")
        return None


def load_detectors(settings: EdgeSettings, need_pose: bool) -> tuple[Any, Any, dict[str, str]]:
    """YOLO detector (+ pose) for real cameras; ``(None, None, {})`` if models are missing."""
    if not settings.model_profile or not settings.models_registry.exists():
        return None, None, {}
    from jikimi_ml_runtime import EngineUnavailableError, load_registry

    from .inference.detector import YoloDetector, YoloPose

    specs = load_registry(settings.models_registry, settings.model_profile)
    det = pose = None
    versions: dict[str, str] = {}
    try:
        if "detector" in specs:
            det = YoloDetector(specs["detector"], settings.repo_root, threads=4)
            versions["detector"] = det.version
        if need_pose and "pose" in specs:
            pose = YoloPose(specs["pose"], settings.repo_root, threads=4)
            versions["pose"] = specs["pose"].path
    except (EngineUnavailableError, ValueError) as exc:
        log.error("detector unavailable: %s - run `make models` (camera health still runs)", exc)
    return det, pose, versions


def build_pipeline(
    settings: EdgeSettings, *, with_outbox: bool = True, record_clips: bool = True, real_perception: bool = False
) -> tuple[EdgePipeline, Outbox | None, DeviceSigner]:
    paths = data_paths(settings)
    signer = DeviceSigner(paths["device_key"])
    outbox = Outbox(paths["outbox"]) if with_outbox else None
    vault = Vault(load_or_create_key(paths["vault_key"])) if with_outbox else None
    det = pose = None
    versions: dict[str, str] = {}
    if real_perception:
        det, pose, versions = load_detectors(
            settings, need_pose=bool({"snatch", "foot_snatch"} & set(settings.plugins))
        )
    pipeline = EdgePipeline(
        settings,
        outbox=outbox,
        signer=signer,
        calibration=CalibrationStore(settings.calibration_dir, settings.site_id),
        vault=vault,
        detector=det,
        pose=pose,
        enhancer=load_enhancer(settings) if det is not None else None,
        record_clips=record_clips,
        model_versions={"edge": __version__, **versions},
    )
    return pipeline, outbox, signer


@dataclass
class ReplayResult:
    alerts: list[AlertCandidate]
    frames: int
    seconds: float


def replay(
    settings: EdgeSettings,
    camera_id: str,
    scenario: str,
    seed: int = 1,
    start_ts: float = 1_793_000_000.0,
    pipeline: EdgePipeline | None = None,
) -> ReplayResult:
    """Run a scenario through the pipeline as fast as possible (golden tests, calibration)."""
    own = pipeline is None
    if pipeline is None:
        pipeline, _, _ = build_pipeline(settings, with_outbox=False, record_clips=False)
    src = SimSource(
        camera_id,
        scenario,
        fps=settings.process_fps,
        realtime=False,
        loop=False,
        start_ts=start_ts,
        seed=seed,
        tz=settings.tz,
    )
    t0 = time.perf_counter()
    frames = 0
    before = len(pipeline.alerts)
    while (frame := src.read()) is not None:
        pipeline.process(camera_id, frame)
        frames += 1
    if own:
        pipeline.flush()
    return ReplayResult(alerts=pipeline.alerts[before:], frames=frames, seconds=time.perf_counter() - t0)


class LiveRunner:
    def __init__(
        self,
        settings: EdgeSettings,
        pipeline: EdgePipeline,
        outbox: Outbox,
        sources: dict[str, FrameSource],
        heartbeat_s: float = 30.0,
    ) -> None:
        self.s = settings
        self.pipeline = pipeline
        self.outbox = outbox
        self.sources = sources
        self.heartbeat_s = heartbeat_s
        self.power = PowerMonitor()
        self.started = time.time()
        self._stop = threading.Event()
        paths = data_paths(settings)
        self.sms = make_gateway(settings.sms_gateway, paths["sms"], settings.modem_port)
        self.client = ServerClient(settings.server_url, settings.device_token)
        self.rules = RuleSync(paths["rules"], paths["server_key"], settings.site_id, pipeline.set_rules)
        self.calendar = CalendarSync(paths["calendar"], paths["server_key"], settings.site_id, pipeline.set_calendar)
        self.commands = CommandSync(paths["commands"], paths["server_key"], settings.site_id, self._execute)
        self.network = NetworkSync(paths["network"], paths["server_key"], settings.site_id, pipeline.set_network)
        for sync in (self.rules, self.calendar, self.commands, self.network):
            sync.load()
        self.sync = SyncAgent(
            outbox,
            self.client,
            self.sms,
            SyncConfig(
                sms_numbers=settings.sms_numbers,
                sms_min_severity=settings.sms_min_severity,
                sms_grace_s=settings.sms_grace_s,
                offline_flag=settings.offline_flag,
            ),
            where=pipeline.where,
            local_time=pipeline.local_time,
            bundles=(self.rules, self.calendar, self.commands, self.network),
        )

    def _execute(self, cmd: EdgeCommand) -> bool:
        if cmd.kind == "accept_view":
            return self.pipeline.reanchor(cmd.camera_id, by=f"admin:{cmd.issued_by}")
        log.error("unknown command %s", cmd.kind)
        return False

    def _camera_loop(self, camera_id: str, source: FrameSource) -> None:
        while not self._stop.is_set():
            try:
                frame = source.read()
            except Exception:
                log.exception("source failed", extra={"camera": camera_id})
                time.sleep(1.0)
                continue
            if frame is None:
                time.sleep(0.2)
                continue
            try:
                self.pipeline.process(camera_id, frame)
            except Exception:
                log.exception("pipeline step failed", extra={"camera": camera_id})

    def heartbeat(self) -> EdgeHeartbeat:
        now = time.time()
        counts = self.outbox.counts()
        drift = {}
        for t in ("loitering", "snatch"):
            res = self.pipeline.calibration.drift(t)
            if res is not None:
                drift[t] = res.drift
        hb = EdgeHeartbeat(
            device_id=self.s.device_id,
            site_id=self.s.site_id,
            ts=datetime.fromtimestamp(now, UTC),
            uptime_s=round(now - self.started, 1),
            cameras=self.pipeline.camera_health(now),
            outbox_backlog=counts["pending"] + counts["sms_sent"],
            outbox_dead=counts["dead"],
            sms_gateway=self.sms.name,
            sms_ok=self.sms.healthy(),
            online=self.sync.online,
            power=self.power.state,
            versions={
                **{k: str(v) for k, v in self.pipeline.model_versions.items()},
                # lets the dashboard show "running on the edge" for approved rules / the calendar
                "rules_bundle": self.rules.version or "none",
                "calendar_bundle": self.calendar.version or "none",
                "event_mode": self.pipeline.mode(now),
            },
            drift=drift,
            extra={
                "stats": dict(self.pipeline.stats),
                "sync": dict(self.sync.stats),
                "volume": self.pipeline.volume(now),
                "commands_done": self.commands.done[-20:],
            },
        )
        self.outbox.enqueue(
            "heartbeat", hb.model_dump(mode="json"), severity="low", priority=8, dedupe_key="heartbeat", replace=True
        )
        return hb

    async def _housekeeping(self) -> None:
        last_hb = last_power = 0.0
        while not self._stop.is_set():
            now = time.time()
            self.pipeline.check_offline(now)
            if now - last_power >= 10:
                last_power = now
                state = self.power.poll()
                fps = fps_for(state.profile, self.s.process_fps)
                for src in self.sources.values():
                    if isinstance(src, RtspSource):
                        src.period = 1.0 / fps  # battery profile: fewer frames, same alert path
            if now - last_hb >= self.heartbeat_s:
                last_hb = now
                self.heartbeat()
                self.outbox.purge_sent()
            if any(rt.last_frame_ts and now - rt.last_frame_ts < 30 for rt in self.pipeline.cameras.values()):
                watchdog.ping()
            await asyncio.sleep(2.0)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):  # pragma: no cover - non-unix
                loop.add_signal_handler(sig, self.stop)
        threads = [
            threading.Thread(target=self._camera_loop, args=(cid, src), name=f"cam-{cid}", daemon=True)
            for cid, src in self.sources.items()
        ]
        for t in threads:
            t.start()
        watchdog.ready()
        log.warning(
            "Jikimi edge running: site=%s cameras=%s server=%s sms=%s",
            self.s.site_id,
            ",".join(self.sources),
            self.s.server_url,
            self.sms.name,
        )
        sync_task = asyncio.create_task(self.sync.run())
        try:
            await self._housekeeping()
        finally:
            self.sync.stop()
            await sync_task
            await self.client.aclose()
            for src in self.sources.values():
                src.close()
            self.pipeline.close()

    def stop(self) -> None:
        log.warning("stopping edge")
        self._stop.set()
