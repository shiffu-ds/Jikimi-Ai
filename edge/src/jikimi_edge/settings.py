"""Edge settings: site YAML (versioned, optionally signed) + environment secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jikimi_common.config import load_config
from jikimi_common.explain import CameraNames
from jikimi_contracts import Severity

from .analytics.base import CameraConfig, ZoneConfig
from .analytics.registry import DEFAULT_PLUGINS
from .routing.router import RoutingConfig


@dataclass
class EdgeSettings:
    site_id: str
    site_name: str
    timezone: str
    device_id: str
    process_fps: float
    cameras: list[CameraConfig]
    plugins: list[str]
    routing: RoutingConfig
    server_url: str
    device_token: str
    data_dir: Path
    calibration_dir: Path
    sms_numbers: list[str]
    sms_min_severity: Severity
    sms_grace_s: float
    sms_gateway: str
    modem_port: str | None
    pre_s: float
    post_s: float
    face_detector: str
    snapshots: bool
    snapshot_interval_s: float
    send_log_only: bool
    model_profile: str | None
    models_registry: Path
    repo_root: Path
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def camera(self, camera_id: str) -> CameraConfig:
        for c in self.cameras:
            if c.id == camera_id:
                return c
        raise KeyError(camera_id)

    def camera_names(self, camera_id: str) -> CameraNames:
        c = self.camera(camera_id)
        return CameraNames(id=c.id, name=c.name, name_ur=c.name_ur, name_roman=c.name_roman)

    def zone_label(self, camera_id: str, zone_id: str | None) -> str:
        c = self.camera(camera_id)
        if zone_id:
            for z in c.zones:
                if z.id == zone_id:
                    return (z.name or z.id).replace(" ", "-")
        return c.name_roman or c.id

    @property
    def keys_dir(self) -> Path:
        return self.data_dir / "keys"

    @property
    def offline_flag(self) -> Path:
        return self.data_dir / "OFFLINE"


def _camera(c: dict[str, Any]) -> CameraConfig:
    zones = [
        ZoneConfig(id=z["id"], polygon=z["polygon"], name=z.get("name"), name_ur=z.get("name_ur"))
        for z in c.get("zones") or []
    ]
    source = c.get("source") or c.get("rtsp_url")
    known = {"id", "name", "name_ur", "name_roman", "source", "rtsp_url", "rtsp_url_env", "zones", "audio", "plugins"}
    return CameraConfig(
        id=c["id"],
        name=c.get("name"),
        name_ur=c.get("name_ur"),
        name_roman=c.get("name_roman"),
        source=source,
        zones=zones,
        audio=bool(c.get("audio", False)),
        plugins=c.get("plugins"),
        extra={k: v for k, v in c.items() if k not in known},
    )


def load_settings(path: str | Path, repo_root: str | Path | None = None) -> EdgeSettings:
    root = Path(repo_root) if repo_root else Path.cwd()
    cfg = load_config(path)
    alerts = cfg.get("alerts") or {}
    offline = cfg.get("offline") or {}
    privacy = cfg.get("privacy") or {}
    paths = cfg.get("paths") or {}
    server = cfg.get("server") or {}
    models = cfg.get("models") or {}
    clips = cfg.get("clips") or {}
    numbers_raw = offline.get("sms_numbers") or os.environ.get("GUARD_SMS_NUMBERS", "")
    numbers = [n.strip() for n in str(numbers_raw).split(",") if n.strip()]
    data_dir = Path(paths.get("data_dir") or os.environ.get("JIKIMI_EDGE_DATA_DIR") or "data/edge")
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    plugins_cfg = cfg.get("plugins") or {}
    token = server.get("token") or os.environ.get("JIKIMI_DEVICE_TOKEN", "")
    token_file = data_dir / "keys" / "device.token"
    if not token and token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
    return EdgeSettings(
        site_id=cfg["site_id"],
        site_name=cfg.get("site_name", cfg["site_id"]),
        timezone=cfg.get("timezone", "Asia/Karachi"),
        device_id=cfg.get("device_id") or os.environ.get("JIKIMI_DEVICE_ID", f"edge-{cfg['site_id']}"),
        process_fps=float(cfg.get("process_fps", 5)),
        cameras=[_camera(c) for c in cfg.get("cameras", [])],
        plugins=list(plugins_cfg.get("enabled") or DEFAULT_PLUGINS),
        routing=RoutingConfig(
            alpha_alert=float(alerts.get("alpha_alert", 0.01)),
            alpha_verify=float(alerts.get("alpha_verify", 0.05)),
            uncalibrated_alert=float(alerts.get("uncalibrated_alert", 0.8)),
            uncalibrated_verify=float(alerts.get("uncalibrated_verify", 0.55)),
            log_only_max_p=float(alerts.get("log_only_max_p", 0.25)),
            cooldown_s=float(alerts.get("cooldown_min", 15)) * 60,
        ),
        server_url=server.get("url") or os.environ.get("JIKIMI_SERVER_URL", "http://localhost:8000"),
        device_token=token,
        data_dir=data_dir,
        calibration_dir=root / paths.get("calibration_dir", "edge/config/calibration"),
        sms_numbers=numbers,
        sms_min_severity=Severity(offline.get("sms_min_severity", "high")),
        sms_grace_s=float(offline.get("sms_grace_s", 5)),
        sms_gateway=str(offline.get("gateway") or os.environ.get("JIKIMI_SMS_GATEWAY", "file")),
        modem_port=offline.get("modem_port") or os.environ.get("JIKIMI_MODEM_PORT"),
        pre_s=float(clips.get("pre_s", 20)),
        post_s=float(clips.get("post_s", 10)),
        face_detector=str(privacy.get("face_detector", "auto")),
        snapshots=bool(privacy.get("snapshots", True)),
        snapshot_interval_s=float(privacy.get("snapshot_interval_s", 5)),
        send_log_only=bool(alerts.get("send_log_only", True)),
        model_profile=models.get("profile"),
        models_registry=root / models.get("registry", "edge/config/models.yaml"),
        repo_root=root,
        raw=cfg,
    )
