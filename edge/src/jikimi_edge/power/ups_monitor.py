"""Power awareness (F4): laptop battery via sysfs, or a UPS via NUT (``upsc``).

Profiles (``profiles.py``) lower the frame rate on battery so a load-shedding hour does not
drain the UPS, while every alert path keeps running.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from jikimi_contracts.events import PowerSource, PowerState

SYS_POWER = Path("/sys/class/power_supply")


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def read_sysfs(root: Path = SYS_POWER) -> PowerState:
    mains_online: bool | None = None
    battery_pct: float | None = None
    discharging = False
    if root.exists():
        for dev in root.iterdir():
            kind = _read(dev / "type")
            if kind in ("Mains", "USB"):
                online = _read(dev / "online")
                if online is not None:
                    mains_online = bool(mains_online) or online == "1"
            elif kind == "Battery":
                cap = _read(dev / "capacity")
                if cap is not None and cap.isdigit():
                    battery_pct = float(cap)
                discharging = discharging or _read(dev / "status") == "Discharging"
    if mains_online or (mains_online is None and battery_pct is not None and not discharging):
        source = PowerSource.AC
    elif battery_pct is not None and (discharging or mains_online is False):
        source = PowerSource.BATTERY
    else:
        source = PowerSource.UNKNOWN
    return PowerState(source=source, battery_pct=battery_pct)


def read_nut(ups: str = "ups@localhost") -> PowerState | None:
    if shutil.which("upsc") is None:
        return None
    try:
        out = subprocess.run(["upsc", ups], capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    vals = dict(line.split(": ", 1) for line in out.splitlines() if ": " in line)
    status = vals.get("ups.status", "")
    pct = float(vals["battery.charge"]) if vals.get("battery.charge", "").replace(".", "", 1).isdigit() else None
    source = PowerSource.BATTERY if "OB" in status.split() else PowerSource.AC if status else PowerSource.UNKNOWN
    state = PowerState(source=source, battery_pct=pct)
    if "LB" in status.split():
        state.profile = "critical"
    return state


def profile_for(state: PowerState, critical_pct: float = 25.0) -> str:
    if state.profile == "critical":
        return "critical"
    if state.source == PowerSource.BATTERY:
        return "critical" if (state.battery_pct is not None and state.battery_pct <= critical_pct) else "battery"
    return "normal"


class PowerMonitor:
    def __init__(self, nut_ups: str | None = None) -> None:
        self.nut_ups = nut_ups
        self.state = PowerState()

    def poll(self) -> PowerState:
        state = (read_nut(self.nut_ups) if self.nut_ups else None) or read_sysfs()
        state.profile = profile_for(state)
        self.state = state
        return state
