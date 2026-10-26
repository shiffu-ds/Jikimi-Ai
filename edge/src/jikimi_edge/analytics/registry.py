"""Plugin discovery (entry points) with a hard blocklist (Responsible use, Section 13.1).

Face recognition and demographic classifiers can never be loaded, whatever a config says.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from importlib.metadata import entry_points
from typing import Any

from .base import AnalyticsPlugin, CameraConfig

log = logging.getLogger(__name__)

BLOCKLIST = frozenset(
    {"face_recognition", "face_id", "facial_recognition", "demographics", "gender", "age", "ethnicity", "emotion"}
)
DEFAULT_PLUGINS = ("loitering", "snatch", "camera_health", "rules")
SAFETY_PLUGINS = ("foot_snatch", "person_safety", "vehicle_theft", "crowd")
"""Behaviour-only personal-safety plugins (no gender, age or identity: see person_safety)."""


class BlockedPluginError(RuntimeError):
    pass


def _builtin() -> dict[str, Callable[[], AnalyticsPlugin]]:
    from .camera_health.plugin import CameraHealthPlugin
    from .crowd.plugin import CrowdPlugin
    from .foot_snatch.plugin import FootSnatchPlugin
    from .loitering.plugin import LoiteringPlugin
    from .person_safety.plugin import PersonSafetyPlugin
    from .rules.plugin import RulesPlugin
    from .snatch.plugin import SnatchPlugin
    from .vehicle_theft.plugin import VehicleTheftPlugin

    return {
        "loitering": LoiteringPlugin,
        "snatch": SnatchPlugin,
        "camera_health": CameraHealthPlugin,
        "rules": RulesPlugin,
        "foot_snatch": FootSnatchPlugin,
        "person_safety": PersonSafetyPlugin,
        "vehicle_theft": VehicleTheftPlugin,
        "crowd": CrowdPlugin,
    }


def discover() -> dict[str, Callable[[], AnalyticsPlugin]]:
    found = _builtin()
    for ep in entry_points(group="jikimi.analytics"):
        if ep.name in found:
            continue
        try:
            found[ep.name] = ep.load()
        except Exception:
            log.exception("plugin entry point failed", extra={"plugin": ep.name})
    return found


def build_plugins(names: Iterable[str], site_cfg: dict[str, Any], camera: CameraConfig) -> list[AnalyticsPlugin]:
    available = discover()
    plugins: list[AnalyticsPlugin] = []
    for name in names:
        if name.lower() in BLOCKLIST or any(b in name.lower() for b in ("face_rec", "facial")):
            raise BlockedPluginError(f"plugin '{name}' is not allowed (no face recognition / demographics)")
        factory = available.get(name)
        if factory is None:
            log.warning("unknown plugin skipped", extra={"plugin": name})
            continue
        plugin = factory()
        plugin.configure(site_cfg, camera)
        plugins.append(plugin)
    return plugins


def resolve_needs(plugins: Iterable[AnalyticsPlugin]) -> set[str]:
    needs: set[str] = set()
    for p in plugins:
        needs |= set(p.needs)
    return needs
