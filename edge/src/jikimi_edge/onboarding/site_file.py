"""What the setup wizard writes (F20): a camera block added to ``site.yaml`` with every comment
kept, and the camera's RTSP URL in ``.env``, the only place a password may live. Both files are
backed up first; the new ``site.yaml`` is parsed again before it replaces the old one."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

import yaml

_TOP_LEVEL = re.compile(r"^[A-Za-z_][\w-]*\s*:")


class _Dumper(yaml.SafeDumper):
    """The site files' own style: nested lists indented, polygons on one line."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


class Polygon(list[list[float]]):
    pass


_Dumper.add_representer(Polygon, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))


def slug(text: str, default: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24] or default


def camera_id(existing: set[str], name: str) -> str:
    """``cam-gate-01``, ``cam-gate-02``, ... (unique within the site)."""
    base = slug(name, "camera")
    n = 1
    while f"cam-{base}-{n:02d}" in existing:
        n += 1
    return f"cam-{base}-{n:02d}"


def env_var(cam_id: str) -> str:
    """``cam-gate-01`` -> ``CAM_GATE_01_RTSP`` (as in site.example.yaml)."""
    return re.sub(r"[^A-Z0-9]+", "_", cam_id.upper()).strip("_") + "_RTSP"


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    dst = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, dst)
    return dst


def set_env(path: Path, key: str, value: str) -> None:
    """Set ``key=value`` in a ``.env`` file: the line is replaced if present, else appended."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or "\n" in value:
        raise ValueError(f"bad environment entry {key!r}")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if not line.lstrip().startswith("#") and line.partition("=")[0].strip() == key:
            if not done:
                out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    path.chmod(0o600)


def camera_ids(site_text: str) -> set[str]:
    data = yaml.safe_load(site_text) or {}
    return {str(c.get("id")) for c in data.get("cameras") or [] if isinstance(c, dict)}


def add_camera(path: Path, camera: dict[str, Any]) -> None:
    """Append ``camera`` to the ``cameras:`` list of a site file, keeping its layout and comments."""
    text = path.read_text(encoding="utf-8")
    before = camera_ids(text)
    if camera["id"] in before:
        raise ValueError(f"camera id {camera['id']} already exists")
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start = next((i for i, ln in enumerate(lines) if re.match(r"^cameras\s*:", ln)), None)
    if start is None:
        lines += ["\n", "cameras:\n"]
        start, end, indent = len(lines) - 1, len(lines), "  "
    else:
        if re.match(r"^cameras\s*:\s*\[\s*\]\s*(#.*)?$", lines[start]):
            lines[start] = "cameras:\n"
        end = start + 1
        while end < len(lines) and not _TOP_LEVEL.match(lines[end]) and not lines[end].startswith("#"):
            end += 1
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1  # the new block goes right after the last camera, before blank lines
        item = next((ln for ln in lines[start + 1 : end] if ln.lstrip().startswith("- ")), "  - ")
        indent = item[: len(item) - len(item.lstrip())]
    dumped = yaml.dump([camera], Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=110)
    block = "".join(indent + ln if ln.strip() else ln for ln in dumped.splitlines(keepends=True))
    lines[end:end] = [block]
    new = "".join(lines)
    if camera_ids(new) != before | {camera["id"]}:
        raise ValueError("could not add the camera to site.yaml safely; nothing was changed")
    path.write_text(new, encoding="utf-8")
