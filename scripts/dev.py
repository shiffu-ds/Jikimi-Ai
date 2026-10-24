"""One-command lite demo: API server + simulated edge in two child processes.

    uv run python scripts/dev.py demo        # server :8000 + edge (2 simulated cameras)
    uv run python scripts/dev.py live        # server :8000 + edge with this laptop's webcam too
    uv run python scripts/dev.py server      # only the API (+ dashboard if built)

Ctrl-C stops both. The edge's outbox survives restarts, so stopping the server is a valid
"internet cut" test: alerts queue up, go out by SMS (fake modem), and sync when it is back.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAN_HOST = "0.0.0.0"  # noqa: S104 - reachable from the guard phone on the same Wi-Fi


def wait_healthy(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 - fixed localhost URL
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    py = [sys.executable]
    procs: list[subprocess.Popen[bytes]] = []
    server = subprocess.Popen(
        [*py, "-m", "jikimi_server", "serve", "--host", LAN_HOST, "--port", "8000"], cwd=ROOT, env=env
    )
    procs.append(server)
    if not wait_healthy("http://127.0.0.1:8000/v1/health"):
        print("server did not start", file=sys.stderr)
        server.terminate()
        return 1
    print("\n  Jikimi AI  ->  http://localhost:8000   (API docs: /docs, guard app: /guard/)\n")
    if mode in ("demo", "live"):
        config = f"edge/config/site.{mode}.yaml"
        procs.append(subprocess.Popen([*py, "-m", "jikimi_edge", "--config", config, "run"], cwd=ROOT, env=env))

    def stop(*_: object) -> None:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    finally:
        stop()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
