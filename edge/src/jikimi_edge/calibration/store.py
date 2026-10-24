"""Calibration sets per (site, alert type, event mode), stored as small JSON files.

``edge/config/calibration/<site_id>/<alert_type>.<mode>.json``::

    {"site_id": "...", "alert_type": "loitering", "mode": "normal", "n": 1200,
     "scores": [...], "created_at": "...", "source": "pilot-48h | simulator"}

A missing mode falls back to ``normal``; a missing type leaves the alert *uncalibrated*
(raw-score thresholds, flagged in the alert features).
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .conformal import SplitConformal
from .drift import KSResult, ks_2samp

log = logging.getLogger(__name__)


class CalibrationStore:
    def __init__(self, root: str | Path, site_id: str, recent_maxlen: int = 2000) -> None:
        self.root = Path(root) / site_id
        self.site_id = site_id
        self._cache: dict[tuple[str, str], SplitConformal | None] = {}
        self._versions: dict[tuple[str, str], str | None] = {}
        self._warned: set[tuple[str, str]] = set()
        self._recent: dict[str, deque[float]] = {}
        self._recent_maxlen = recent_maxlen

    def _path(self, alert_type: str, mode: str) -> Path:
        return self.root / f"{alert_type}.{mode}.json"

    def get(self, alert_type: str, mode: str = "normal", model_version: str | None = None) -> SplitConformal | None:
        """Calibration for this type/mode, or ``None``.

        A set is only valid for the scorer that produced it: if ``model_version`` differs from
        the version recorded at calibration time (e.g. heuristic -> ST-GCN), the alert is treated
        as uncalibrated until ``calibrate`` is re-run.
        """
        key = (alert_type, mode)
        if key not in self._cache:
            path = self._path(alert_type, mode)
            if not path.exists() and mode != "normal":
                self._cache[key] = self.get(alert_type, "normal")
                self._versions[key] = self._versions.get((alert_type, "normal"))
                return self._checked(key, model_version)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._cache[key] = SplitConformal(data["scores"])
                self._versions[key] = data.get("model_version")
                log.info(
                    "calibration loaded",
                    extra={"type": alert_type, "mode": mode, "n": data.get("n"), "version": data.get("model_version")},
                )
            else:
                self._cache[key] = None
        return self._checked(key, model_version)

    def _checked(self, key: tuple[str, str], model_version: str | None) -> SplitConformal | None:
        cal = self._cache.get(key)
        recorded = self._versions.get(key)
        if cal is not None and model_version and recorded and recorded != model_version:
            if key not in self._warned:
                self._warned.add(key)
                log.warning(
                    "calibration was made for %s, scorer is %s: alerts are uncalibrated until recalibrated",
                    recorded,
                    model_version,
                )
            return None
        return cal

    def units_per_hour(self, alert_type: str, mode: str = "normal") -> float | None:
        """Calibration units per camera-hour recorded by ``calibrate`` (e.g. bike entities)."""
        path = self._path(alert_type, mode)
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8")).get("units_per_camera_hour")
        return float(value) if value else None

    def calibrated_mode(self, alert_type: str, mode: str) -> str:
        """The mode whose calibration set actually answers for ``mode`` (its own, or "normal")."""
        return mode if mode == "normal" or self._path(alert_type, mode).exists() else "normal"

    def p_value(self, alert_type: str, mode: str, score: float, model_version: str | None = None) -> float | None:
        cal = self.get(alert_type, mode, model_version)
        return None if cal is None else cal.p_value(score)

    def save(
        self, alert_type: str, mode: str, scores: list[float], source: str, extra: dict[str, Any] | None = None
    ) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(alert_type, mode)
        payload = {
            "site_id": self.site_id,
            "alert_type": alert_type,
            "mode": mode,
            "n": len(scores),
            "scores": [round(float(s), 6) for s in scores],
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": source,
            **(extra or {}),
        }
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        self._cache.pop((alert_type, mode), None)
        self._versions.pop((alert_type, mode), None)
        return path

    def observe(self, alert_type: str, score: float) -> None:
        """Track recent candidate scores for the weekly drift check."""
        self._recent.setdefault(alert_type, deque(maxlen=self._recent_maxlen)).append(score)

    def drift(self, alert_type: str, mode: str = "normal", min_recent: int = 200) -> KSResult | None:
        cal = self.get(alert_type, mode)
        recent = self._recent.get(alert_type)
        if cal is None or recent is None or len(recent) < min_recent:
            return None
        return ks_2samp(list(recent), cal.cal)
