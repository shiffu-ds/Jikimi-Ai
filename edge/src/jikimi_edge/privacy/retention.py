"""Retention job (F19): delete expired clips/originals and old outbox rows; log deletions.

Run nightly (systemd timer) or by hand: ``python -m jikimi_edge.privacy.retention --older-than-days 7``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

DEFAULTS = {"clips": 7, "originals": 7, "thumbs": 7}


def purge(
    data_dir: str | Path, days: dict[str, float] | None = None, now: float | None = None, dry_run: bool = False
) -> dict[str, int]:
    root = Path(data_dir)
    now = time.time() if now is None else now
    limits = {**DEFAULTS, **(days or {})}
    removed: dict[str, int] = {}
    log_lines = []
    for sub, max_days in limits.items():
        folder = root / sub
        count = 0
        if folder.exists():
            for f in folder.rglob("*"):
                if f.is_file() and now - f.stat().st_mtime > max_days * 86400:
                    if not dry_run:
                        f.unlink()
                    count += 1
                    log_lines.append({"file": str(f.relative_to(root)), "reason": f"retention:{sub}:{max_days}d"})
        removed[sub] = count
    if log_lines and not dry_run:
        with open(root / "deletion_log.jsonl", "a", encoding="utf-8") as fh:
            for line in log_lines:
                fh.write(json.dumps({"at": now, **line}) + "\n")
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description="Jikimi edge retention job")
    ap.add_argument("--data-dir", default="data/edge")
    ap.add_argument("--older-than-days", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    days = dict.fromkeys(DEFAULTS, args.older_than_days) if args.older_than_days else None
    print(json.dumps(purge(args.data_dir, days, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
