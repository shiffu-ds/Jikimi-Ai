"""Create ``.env`` from ``.env.example`` with fresh random secrets (never overwrites)."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

GENERATED = {
    "JIKIMI_JWT_SECRET": lambda: secrets.token_urlsafe(48),
    "JIKIMI_DEMO_PASSWORD": lambda: "jk-" + secrets.token_urlsafe(9),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
}


def main() -> int:
    src, dst = Path(".env.example"), Path(".env")
    if dst.exists():
        print(".env already exists - left untouched")
        return 0
    lines = []
    for line in src.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key in GENERATED and not value.strip():
            line = f"{key}={GENERATED[key]()}"
        lines.append(line)
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dst.chmod(0o600)
    print("created .env with random secrets (demo password is JIKIMI_DEMO_PASSWORD in .env)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
