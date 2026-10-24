"""YAML config loading with environment references.

Secrets never live in YAML: a key ending in ``_env`` names an environment variable, and the
loader adds the resolved value under the key without the suffix::

    rtsp_url_env: CAM_GATE_01_RTSP   ->   rtsp_url: "rtsp://..." (from the environment)
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def resolve_env_refs(obj: Any, environ: Mapping[str, str] | None = None) -> Any:
    env = os.environ if environ is None else environ
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            out[key] = resolve_env_refs(value, env)
            if isinstance(key, str) and key.endswith("_env") and isinstance(value, str):
                out[key[: -len("_env")]] = env.get(value)
        return out
    if isinstance(obj, list):
        return [resolve_env_refs(v, env) for v in obj]
    return obj


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    resolved: dict[str, Any] = resolve_env_refs(load_yaml(path), environ)
    return resolved


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_dotenv(path: str | Path = ".env", override: bool = False) -> int:
    """Tiny ``.env`` reader (KEY=VALUE, # comments). Returns the number of keys set."""
    p = Path(path)
    if not p.exists():
        return 0
    count = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value
            count += 1
    return count
