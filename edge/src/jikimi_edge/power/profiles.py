"""Runtime profiles by power state (plan Section 8.8: battery -> fps down, VLM off)."""

from __future__ import annotations

PROFILES: dict[str, dict[str, float | bool]] = {
    "normal": {"fps_factor": 1.0, "snapshots": True},
    "battery": {"fps_factor": 0.6, "snapshots": True},
    "critical": {"fps_factor": 0.4, "snapshots": False},
}


def fps_for(profile: str, base_fps: float) -> float:
    factor = float(PROFILES.get(profile, PROFILES["normal"])["fps_factor"])
    return max(1.0, base_fps * factor)
