"""Jikimi AI shared contracts: the single source of truth between edge, server and dashboard."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from . import api, commands, events, evidence, modes, network, rules_dsl, search
from .alerts import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    AlertCandidate,
    AlertStatus,
    AlertType,
    ClipAttestation,
    DeliveryInfo,
    EdgeAlertEnvelope,
    KeyframeRef,
    ObjectSummary,
    ReviewVerdict,
    Route,
    Severity,
    TrackSummary,
)
from .detections import (
    COCO_TO_JIKIMI,
    KEYPOINT_NAMES,
    KP,
    NUM_KEYPOINTS,
    TWO_WHEELERS,
    VEHICLE_CLASSES,
    BBox,
    Detection,
    ObjectClass,
    Pose,
    Track,
)
from .version import SCHEMA_VERSION

__all__ = [
    "ACTIVE_STATUSES",
    "COCO_TO_JIKIMI",
    "KEYPOINT_NAMES",
    "KP",
    "NUM_KEYPOINTS",
    "SCHEMA_VERSION",
    "TERMINAL_STATUSES",
    "TWO_WHEELERS",
    "VEHICLE_CLASSES",
    "AlertCandidate",
    "AlertStatus",
    "AlertType",
    "BBox",
    "ClipAttestation",
    "DeliveryInfo",
    "Detection",
    "EdgeAlertEnvelope",
    "KeyframeRef",
    "ObjectClass",
    "ObjectSummary",
    "Pose",
    "ReviewVerdict",
    "Route",
    "Severity",
    "Track",
    "TrackSummary",
    "api",
    "commands",
    "events",
    "evidence",
    "exported_models",
    "modes",
    "network",
    "rules_dsl",
    "search",
]


def exported_models() -> list[type[BaseModel]]:
    """Models exported to TypeScript, in a stable order."""
    from .alerts import AlertCandidate as _AC

    mods: list[Any] = [api, search, evidence, events, rules_dsl, modes, commands, network]
    seen: dict[str, type[BaseModel]] = {"AlertCandidate": _AC, "ObjectSummary": ObjectSummary}
    for mod in mods:
        for name in sorted(dir(mod)):
            obj = getattr(mod, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__module__ == mod.__name__
                and not name.startswith("_")
            ):
                seen.setdefault(name, obj)
    return [seen[k] for k in sorted(seen)]
