from __future__ import annotations

import shutil
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import pytest
import yaml
from jikimi_contracts import Detection
from jikimi_edge.onboarding.site_file import Polygon, add_camera, camera_id, env_var, set_env
from jikimi_edge.onboarding.wizard import Wizard, WizardError, make_handler
from jikimi_edge.settings import load_settings

REPO = Path(__file__).resolve().parents[3]
PIN = "482913"


def test_camera_is_added_to_site_yaml_with_its_comments_kept(tmp_path: Path) -> None:
    site = tmp_path / "site.yaml"
    shutil.copy(REPO / "edge/config/site.example.yaml", site)
    before = site.read_text(encoding="utf-8")
    cid = camera_id({"cam-gate-01"}, "Gate")
    assert (cid, env_var(cid)) == ("cam-gate-02", "CAM_GATE_02_RTSP")
    zone = {"id": "gate", "name": "Gate", "name_ur": "گیٹ", "polygon": Polygon([[0.1, 0.2], [0.6, 0.2], [0.6, 0.9]])}
    add_camera(
        site, {"id": cid, "name": "Gate: main #1", "name_ur": "گیٹ", "rtsp_url_env": env_var(cid), "zones": [zone]}
    )
    after = site.read_text(encoding="utf-8")
    assert all(line in after for line in before.splitlines())  # nothing removed, comments included
    assert "polygon: [[0.1, 0.2], [0.6, 0.2], [0.6, 0.9]]" in after
    s = load_settings(site, repo_root=REPO)
    new = next(c for c in s.cameras if c.id == "cam-gate-02")
    assert new.name == "Gate: main #1" and new.zones[0].polygon == [[0.1, 0.2], [0.6, 0.2], [0.6, 0.9]]
    with pytest.raises(ValueError, match="already exists"):
        add_camera(site, {"id": "cam-gate-02", "name": "x"})
    empty = tmp_path / "empty.yaml"
    empty.write_text("site_id: s\ncameras: []  # none yet\nplugins: {}\n", encoding="utf-8")
    add_camera(empty, {"id": "cam-a-01", "name": "A"})
    assert [c["id"] for c in yaml.safe_load(empty.read_text())["cameras"]] == ["cam-a-01"]


def test_rtsp_url_goes_to_env_only(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# secrets\nJIKIMI_JWT_SECRET=x\nCAM_GATE_02_RTSP=old\n", encoding="utf-8")
    set_env(env, "CAM_GATE_02_RTSP", "rtsp://admin:p%40ss@192.168.1.64:554/Streaming/Channels/102")
    set_env(env, "CAM_YARD_01_RTSP", "rtsp://192.168.1.65/stream2")
    text = env.read_text(encoding="utf-8")
    assert text.startswith("# secrets\nJIKIMI_JWT_SECRET=x\n") and "old" not in text
    assert text.count("CAM_GATE_02_RTSP=") == 1 and "CAM_YARD_01_RTSP=rtsp://192.168.1.65/stream2" in text
    assert env.stat().st_mode & 0o077 == 0  # owner only
    with pytest.raises(ValueError):
        set_env(env, "BAD KEY", "x")


def _clip(path: Path) -> Path:
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (320, 240))
    for i in range(20):
        w.write(np.full((240, 320, 3), 40 + i * 5, np.uint8))
    w.release()
    return path


class _Detector:
    def __call__(self, frame: Any) -> list[Detection]:
        return [
            Detection(cls="person", conf=0.9, bbox=(0.1, 0.1, 0.3, 0.9)),
            Detection(cls="motorcycle", conf=0.8, bbox=(0.5, 0.5, 0.9, 0.9)),
        ]


@pytest.fixture
def wizard(tmp_path: Path) -> Iterator[tuple[str, Wizard, Path]]:
    site = tmp_path / "site.yaml"
    shutil.copy(REPO / "edge/config/site.example.yaml", site)
    wz = Wizard(site, tmp_path / ".env", detector=_Detector(), allow_files=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(wz, PIN))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", wz, tmp_path
    httpd.shutdown()
    httpd.server_close()


def test_wizard_adds_a_camera_end_to_end(wizard: tuple[str, Wizard, Path]) -> None:
    base, _, tmp = wizard
    pin = {"X-Setup-Pin": PIN}
    page = httpx.get(base + "/")
    assert (
        page.status_code == 200
        and "کیمرہ" in page.text
        and "default-src 'self'" in page.headers["content-security-policy"]
    )
    assert httpx.get(base + "/api/state").status_code == 401
    state = httpx.get(base + "/api/state", headers=pin).json()
    assert (
        state["site_id"] == "society-gate-north"
        and state["detector"]
        and "hikvision" in [b["id"] for b in state["brands"]]
    )

    src = {"kind": "file", "path": str(_clip(tmp / "gate.avi"))}
    probe = httpx.post(base + "/api/probe", json=src, headers=pin, timeout=30).json()
    assert (
        probe["report"]["ok"] and probe["size"] == [320, 240] and probe["preview"].startswith("data:image/jpeg;base64,")
    )
    assert probe["advice_ur"] == ["ٹھیک ہے: کیمرہ تیار ہے"]
    det = httpx.post(base + "/api/detect", json=src, headers=pin, timeout=30).json()
    assert det["counts"] == {"person": 1, "motorcycle": 1} and det["picture"].startswith("data:image/jpeg")

    bad = httpx.post(
        base + "/api/save", json={"source": src, "camera": {"name": "Gate"}, "zone": {"polygon": [[0, 0]]}}, headers=pin
    )
    assert bad.status_code == 400 and "3 points" in bad.json()["error"]
    body = {
        "source": src,
        "camera": {"name": "Back gate", "name_ur": "پچھلا گیٹ", "name_roman": "Back gate"},
        "zone": {"name": "Gate", "name_ur": "گیٹ", "polygon": [[0.1, 0.2], [0.9, 0.2], [1.4, 0.95]]},
    }
    saved = httpx.post(base + "/api/save", json=body, headers=pin).json()
    assert saved["camera_id"] == "cam-back-gate-01" and saved["env_var"] is None  # a file needs no secret
    cams = yaml.safe_load((tmp / "site.yaml").read_text(encoding="utf-8"))["cameras"]
    new = cams[-1]
    assert new["source"].startswith("file:") and new["zones"][0]["polygon"][2] == [1.0, 0.95]  # clamped
    assert new["name_ur"] == "پچھلا گیٹ" and len(saved["backups"]) == 1


def test_wizard_keeps_rtsp_passwords_in_env_and_off_the_page(wizard: tuple[str, Wizard, Path]) -> None:
    base, wz, tmp = wizard
    src = {
        "kind": "template",
        "brand": "hikvision",
        "ip": "192.168.1.64",
        "channel": 2,
        "user": "admin",
        "password": "p@ss#1",
    }
    assert wz.source_url(src) == "rtsp://admin:p%40ss%231@192.168.1.64:554/Streaming/Channels/202"
    assert wz.source_url({**src, "stream": "main"}).endswith("/Streaming/Channels/201")
    url = {"kind": "url", "uri": "rtsp://192.168.1.70:554/live", "user": "u", "password": "p w"}
    assert wz.source_url(url) == "rtsp://u:p%20w@192.168.1.70:554/live"
    assert wz.source_url({"kind": "webcam", "index": 0}) == "webcam:0"  # the laptop's own camera
    for bad in (
        {**src, "ip": "1.2.3.4/x?"},
        {**src, "brand": "acme"},
        {"kind": "url", "uri": "http://x"},
        {"kind": "webcam", "index": 12},
    ):
        with pytest.raises(WizardError):
            wz.source_url(bad)
    body = {"source": src, "camera": {"name": "Gate"}, "zone": {"polygon": [[0, 0], [1, 0], [1, 1]]}}
    saved = httpx.post(base + "/api/save", json=body, headers={"X-Setup-Pin": PIN}).json()
    assert saved["env_var"] == "CAM_GATE_02_RTSP" == env_var(saved["camera_id"])  # cam-gate-01 exists
    assert (
        "CAM_GATE_02_RTSP=rtsp://admin:p%40ss%231@192.168.1.64:554/Streaming/Channels/202" in (tmp / ".env").read_text()
    )
    site_text = (tmp / "site.yaml").read_text(encoding="utf-8")
    assert "p%40ss" not in site_text and "rtsp_url_env: CAM_GATE_02_RTSP" in site_text
    probe = httpx.post(
        base + "/api/probe", json={**src, "ip": "127.0.0.1", "port": 9}, headers={"X-Setup-Pin": PIN}, timeout=60
    )
    assert "p%40ss" not in probe.text and "p@ss" not in probe.text  # masked in the report


def test_wrong_pins_lock_the_wizard_for_a_minute(wizard: tuple[str, Wizard, Path]) -> None:
    base, _, _ = wizard
    codes = [httpx.get(base + "/api/state", headers={"X-Setup-Pin": "000000"}).status_code for _ in range(5)]
    assert codes == [401] * 5
    assert httpx.get(base + "/api/state", headers={"X-Setup-Pin": PIN}).status_code == 429


def test_webcam_sources_open_the_local_camera_at_720p(monkeypatch: pytest.MonkeyPatch) -> None:
    from jikimi_edge.ingest import sources

    opened: list[Any] = []

    class FakeCapture:
        def __init__(self, *args: Any) -> None:
            opened.append(args)
            self.props: dict[int, float] = {}

        def set(self, prop: int, value: float) -> bool:
            self.props[prop] = value
            return True

    monkeypatch.setattr(sources.cv2, "VideoCapture", FakeCapture)
    cap = sources.open_capture("webcam:1")
    assert opened[-1] == (1,) and cap.props[cv2.CAP_PROP_FRAME_WIDTH] == 1280
    sources.open_capture("rtsp://192.168.1.64/stream2")
    url, backend, params = opened[-1]
    assert url.startswith("rtsp://")
    assert backend == cv2.CAP_FFMPEG and cv2.CAP_PROP_OPEN_TIMEOUT_MSEC in params  # no 30 s hang
