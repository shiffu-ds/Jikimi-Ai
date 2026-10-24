"""Camera health / tamper plugin (F10). Tamper alerts are always high severity: thieves
often cover or turn the camera first.

After a ``moved`` alarm the old reference view would never match again, so the camera would stay
"moved" for ever. A new view is accepted either by an admin (dashboard -> signed command) or by
itself once the camera has stayed still in its new position for ``reanchor_after_s``; both send a
low-severity notice, because zones drawn on the old view may no longer fit.
"""

from __future__ import annotations

import statistics
from collections import deque
from typing import Any

from jikimi_contracts import AlertCandidate, AlertType

from ..base import CameraConfig, FrameContext
from .checks import EgoMotion, MotionReference, frame_stats, frozen_diff, is_covered, small_gray

# seconds a condition must persist before it becomes an alert (plan Section 8.10)
HOLD_S = {"covered": 8.0, "blur": 60.0, "moved": 30.0, "frozen": 20.0}
MOVING_THRESHOLD = 0.02  # 2 % of the frame width (or 2 % zoom / ~1 degree) between checks 1 s apart


class CameraHealthPlugin:
    name = "camera_health"
    version = "checks-v1"
    needs = frozenset({"frame"})

    def __init__(self) -> None:
        self.interval_s = 1.0
        self.warmup_s = 10.0
        self.hold_s = dict(HOLD_S)
        self._last_check = -1e18
        self._started: float | None = None
        self._sharp_hist: deque[float] = deque(maxlen=360)
        self._last_sample = -1e18
        self._prev_gray: Any = None
        self._ref = MotionReference()
        self._ego = EgoMotion()
        self._ego_recent: deque[bool] = deque(maxlen=3)
        self._last_moved_check = -1e18
        self._moved_value: float | None = None
        self._onset: dict[str, float | None] = dict.fromkeys(self.hold_s)
        self._alarmed: set[str] = set()
        self.status: dict[str, str] = dict.fromkeys(self.hold_s, "ok")
        self.status["moving"] = "ok"
        """``moving`` is no tamper alarm: it tells motion-based analytics that their evidence is
        unreliable right now (the pipeline keeps snatch / loitering out of ALERT_NOW)."""
        self.reanchor_after_s = 600.0
        self._steady_since: float | None = None
        self._reanchor_by: str | None = None

    def request_reanchor(self, by: str = "admin") -> None:
        """Accept the current view as the new reference on the next check (admin command)."""
        self._reanchor_by = by

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        cfg = (site_cfg.get("plugins") or {}).get(self.name, {}) or {}
        self.hold_s.update({k: float(v) for k, v in (cfg.get("hold_s") or {}).items()})
        self.warmup_s = float(cfg.get("warmup_s", self.warmup_s))
        self.reanchor_after_s = float(cfg.get("reanchor_after_s", self.reanchor_after_s))

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        if ctx.frame is None or ctx.ts - self._last_check < self.interval_s:
            return []
        self._last_check = ctx.ts
        if self._started is None:
            self._started = ctx.ts
        gray = small_gray(ctx.frame)
        stats = frame_stats(gray)
        ego = self._ego.between(self._prev_gray, gray)
        if ego is not None:
            self._ego_recent.append(ego > MOVING_THRESHOLD)
        self.status["moving"] = "warn" if sum(self._ego_recent) >= 2 else "ok"
        cond: dict[str, bool] = {
            "covered": is_covered(stats),
            "frozen": frozen_diff(self._prev_gray, gray) < 0.25,
            "blur": False,
            "moved": False,
        }
        self._prev_gray = gray
        if len(self._sharp_hist) >= 20 and not cond["covered"]:
            baseline = statistics.median(self._sharp_hist)
            cond["blur"] = stats.sharpness < 0.3 * baseline
        warm = ctx.ts - self._started >= self.warmup_s
        if not any(cond.values()):
            if ctx.ts - self._last_sample >= 10.0:
                self._sharp_hist.append(stats.sharpness)
                self._last_sample = ctx.ts
            if warm and not self._ref.ready:
                self._ref.set(gray)
        if self._ref.ready and not cond["covered"] and ctx.ts - self._last_moved_check >= 5.0:
            self._last_moved_check = ctx.ts
            self._moved_value = self._ref.inlier_ratio(gray)
        if self._moved_value is not None and not cond["covered"]:
            cond["moved"] = self._moved_value < 0.25
        out: list[AlertCandidate] = []
        how = None
        if self._reanchor_by is not None and not cond["covered"]:
            how, self._reanchor_by = self._reanchor_by, None
        elif cond["moved"] and self.status["moving"] == "ok":  # moved, but standing still again
            self._steady_since = ctx.ts if self._steady_since is None else self._steady_since
            if ctx.ts - self._steady_since >= self.reanchor_after_s:
                how = "auto"
        else:
            self._steady_since = None
        if how is not None:
            self._ref = MotionReference()
            self._ref.set(gray)  # if the view has too little texture, it is set again once clear
            self._moved_value, self._steady_since = None, None
            self._alarmed.discard("moved")
            cond["moved"] = False
            out.append(
                ctx.make_alert(
                    AlertType.TAMPER,
                    1.0,
                    ctx.ts,
                    features={
                        "check": "view_accepted",
                        "how": how,
                        "severity": "low",
                        "dedupe_key": f"view:{int(ctx.ts)}",
                    },
                    model_versions={"camera_health": self.version},
                )
            )
        for check, active in cond.items():
            onset = self._onset.get(check)
            if active:
                if onset is None:
                    self._onset[check] = onset = ctx.ts
                held = ctx.ts - onset
                self.status[check] = "alarm" if held >= self.hold_s[check] else "warn"
                if held >= self.hold_s[check] and check not in self._alarmed and warm:
                    self._alarmed.add(check)
                    out.append(
                        ctx.make_alert(
                            AlertType.TAMPER,
                            1.0,
                            onset,
                            features={
                                "check": check,
                                "held_s": round(held, 1),
                                "sharpness": round(stats.sharpness, 1),
                                "brightness": round(stats.brightness, 1),
                                "entropy": round(stats.entropy, 2),
                                "inlier_ratio": None if self._moved_value is None else round(self._moved_value, 3),
                                "dedupe_key": check,
                            },
                            model_versions={"camera_health": self.version},
                        )
                    )
            else:
                self._onset[check] = None
                self.status[check] = "ok"
                if check in self._alarmed:
                    self._alarmed.discard(check)
                    if check == "moved":
                        self._ref = MotionReference()  # accept the new view after recovery
        return out

    def state_dict(self) -> dict[str, Any]:
        return {"sharp_hist": list(self._sharp_hist)}

    def load_state(self, state: dict[str, Any]) -> None:
        self._sharp_hist.extend(float(x) for x in state.get("sharp_hist", []))
