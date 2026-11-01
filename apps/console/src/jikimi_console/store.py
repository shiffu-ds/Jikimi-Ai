"""Small things the console keeps itself: the handover note between shifts (per site)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("JIKIMI_CONSOLE_DATA", Path(__file__).resolve().parents[4] / "data" / "console"))


def note(site_id: str) -> dict[str, str] | None:
    p = ROOT / "notes.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get(site_id)


def save_note(site_id: str, text: str, by: str) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    p = ROOT / "notes.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data[site_id] = {"text": text.strip(), "by": by, "at": datetime.now(UTC).isoformat(timespec="seconds")}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
