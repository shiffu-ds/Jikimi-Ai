"""``edge/config/models.yaml``: which model file, format and backend each profile uses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelSpec:
    name: str
    path: str
    backend: str
    device: str = "CPU"
    imgsz: int = 640
    classes: str = "coco"
    conf: float = 0.25
    iou: float = 0.45
    sha256: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def resolve(self, root: str | Path) -> Path:
        p = Path(self.path)
        return p if p.is_absolute() else Path(root) / p


def load_registry(path: str | Path, profile: str) -> dict[str, ModelSpec]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    profiles = data.get("profiles", {})
    if profile not in profiles:
        raise KeyError(f"profile '{profile}' not in {path} (have: {', '.join(profiles)})")
    specs: dict[str, ModelSpec] = {}
    for name, cfg in (profiles[profile] or {}).items():
        known = {
            k: cfg[k] for k in ("path", "backend", "device", "imgsz", "classes", "conf", "iou", "sha256") if k in cfg
        }
        extra = {k: v for k, v in cfg.items() if k not in known}
        specs[name] = ModelSpec(name=name, extra=extra, **known)
    return specs
