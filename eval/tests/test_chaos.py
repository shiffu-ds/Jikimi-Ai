"""Power-cut durability: an alert committed to the outbox survives kill -9 (plan F4 / FMEA #1)."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from jikimi_edge.outbox.db import Outbox

WRITER = """
import sys, time
from jikimi_edge.outbox.db import Outbox
ob = Outbox(sys.argv[1])
for i in range(10_000):
    ob.enqueue("alert", {"n": i}, severity="high", priority=0, dedupe_key=f"a{i}")
    print(i, flush=True)   # printed only after the commit returned
    time.sleep(0.002)
"""


@pytest.mark.chaos
@pytest.mark.parametrize("cut_after", [3, 40, 250])
def test_kill_minus_nine_loses_no_committed_alert(tmp_path: Path, cut_after: int) -> None:
    db = tmp_path / "outbox.db"
    proc = subprocess.Popen(
        [sys.executable, "-c", WRITER, str(db)],
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert proc.stdout is not None
    acknowledged: list[int] = []
    deadline = time.monotonic() + 60
    while len(acknowledged) < cut_after and time.monotonic() < deadline:
        line = proc.stdout.readline()
        if line.strip():
            acknowledged.append(int(line))
    os.kill(proc.pid, signal.SIGKILL)  # no flush, no atexit: like pulling the plug mid-write
    rest, _ = proc.communicate()
    acknowledged += [int(x) for x in rest.split()]
    assert len(acknowledged) >= cut_after, "writer did not start"
    ob = Outbox(db)
    stored = {item.payload["n"] for item in ob.due(limit=100_000)}
    missing = set(acknowledged) - stored
    assert not missing, f"lost {len(missing)} committed alerts"
    assert json.dumps(ob.counts())  # database still opens and is consistent
