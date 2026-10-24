"""F20 setup wizard: a small Urdu-first web page served by the edge itself, opened from a phone
on the same Wi-Fi.

    uv run python -m jikimi_edge --config edge/config/site.yaml setup     # prints the address + a PIN

Find the camera (ONVIF discovery, or brand + IP through the RTSP templates) -> connection test
with a preview (heads blurred) -> draw the watched zone on the preview -> detector test -> save:
the RTSP URL, password included, goes into ``.env``; the camera and its zone into ``site.yaml``
(both backed up first). The page works without internet and lives only while the command runs,
behind a one-time PIN. Nothing goes to the server: RTSP passwords never leave the edge.

Plain ``http.server`` keeps the edge free of a web framework. On a shared Wi-Fi the PIN and the
camera password cross the LAN unencrypted: prefer a cable, or run it on the edge box itself with
``--host 127.0.0.1``.
"""

from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import cv2
import numpy as np
import yaml
from jikimi_contracts import TWO_WHEELERS

from ..ingest.sources import open_capture
from .discovery import discover
from .onvif import OnvifClient, OnvifError
from .probe import probe
from .site_file import Polygon, add_camera, backup, camera_id, camera_ids, env_var, set_env, slug
from .templates import TEMPLATES, mask, urls

log = logging.getLogger(__name__)
MAX_BODY = 64_000
PREVIEW_W = 960
_HOST = re.compile(r"[A-Za-z0-9.\-]{1,253}|\[[0-9A-Fa-f:]+\]")
# probe.advise() text -> Urdu for the page (English stays alongside)
ADVICE_UR = {
    "stream did not open": "اسٹریم نہیں کھلی: IP، پورٹ 554، یوزر/پاس ورڈ اور چینل دیکھیں؛ دوسرا برانڈ/اسٹریم آزمائیں",
    "opened but no frames": "کنکشن ہوا مگر تصویر نہیں آئی: چینل غلط ہے یا ریکارڈر مزید کنکشن نہیں دے رہا",
    "heavier than 720p": "720p سے بھاری اسٹریم: سب اسٹریم استعمال کریں",
    "of reads failed": "کچھ فریم ضائع ہوئے: تار / وائی فائی دیکھیں یا سب اسٹریم لیں",
    "frames/s arrive": "فریم کم آ رہے ہیں: ریکارڈر میں سب اسٹریم کے فریم 5-10 کریں",
    "ok: ready": "ٹھیک ہے: کیمرہ تیار ہے",
}


class WizardError(ValueError):
    """A problem the installer can fix; shown on the page as is."""


def _host(value: Any) -> str:
    host = str(value or "").strip()
    if not _HOST.fullmatch(host):
        raise WizardError("enter the recorder's IP address, e.g. 192.168.1.64")
    return host


def _with_auth(uri: str, user: str, password: str) -> str:
    parts = urlsplit(uri)
    if parts.scheme not in ("rtsp", "rtsps") or not parts.hostname:
        raise WizardError("an rtsp:// address is needed")
    if not user:
        return uri
    netloc = parts.netloc.rpartition("@")[2]
    return urlunsplit(parts._replace(netloc=f"{quote(user, safe='')}:{quote(password, safe='')}@{netloc}"))


class Wizard:
    def __init__(self, site_file: Path, env_file: Path, detector: Any = None, allow_files: bool = False) -> None:
        from ..privacy.face_blur import PrivacyBlur

        self.site_file = site_file
        self.env_file = env_file
        self.detector = detector
        self.allow_files = allow_files
        blur = PrivacyBlur("auto")
        self.blur = blur if blur.method != "head" else PrivacyBlur("haar")  # no YuNet: OpenCV's own faces
        self.lock = threading.Lock()  # one camera operation at a time (and one detector user)

    # --- what the page asks for -------------------------------------------------------------
    def state(self, _: dict[str, Any] | None = None) -> dict[str, Any]:
        site = yaml.safe_load(self.site_file.read_text(encoding="utf-8")) or {}
        return {
            "site_id": site.get("site_id"),
            "site_name": site.get("site_name"),
            "cameras": [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "name_ur": c.get("name_ur"),
                    "zones": len(c.get("zones") or []),
                }
                for c in site.get("cameras") or []
            ],
            "brands": [{"id": k, "note": t.note} for k, t in TEMPLATES.items()],
            "detector": self.detector is not None,
            "files": self.allow_files,
        }

    def discover(self, _: dict[str, Any]) -> dict[str, Any]:
        found = discover(3.0)
        return {
            "devices": [
                {"ip": d.ip, "name": d.name, "hardware": d.hardware, "brand": d.brand, "xaddr": d.xaddrs[0]}
                for d in found
            ]
        }

    def streams(self, b: dict[str, Any]) -> dict[str, Any]:
        xaddr = str(b.get("xaddr") or "")
        host = urlsplit(xaddr).hostname or ""
        try:
            local = ipaddress.ip_address(host).is_private
        except ValueError:
            local = False
        if not xaddr.startswith(("http://", "https://")) or not local:
            raise WizardError("ONVIF works only with a recorder on this network")
        client = OnvifClient(xaddr, str(b.get("user") or ""), str(b.get("password") or ""))
        try:
            profiles = sorted(client.streams(), key=lambda s: s.pixels)  # sub-stream first
        finally:
            client.close()
        return {
            "streams": [
                {"name": s.name, "width": s.width, "height": s.height, "encoding": s.encoding, "uri": mask(s.uri or "")}
                for s in profiles
                if s.uri
            ]
        }

    def source_url(self, b: dict[str, Any]) -> str:
        """The stream address with credentials; it never goes back to the page."""
        kind = b.get("kind")
        user, password = str(b.get("user") or ""), str(b.get("password") or "")
        if kind == "template":
            brand = str(b.get("brand") or "")
            if brand not in TEMPLATES:
                raise WizardError("choose the recorder's brand")
            port, channel = int(b.get("port") or 554), int(b.get("channel") or 1)
            main, sub = urls(brand, _host(b.get("ip")), channel, user, password, port)
            return main if b.get("stream") == "main" else sub
        if kind == "url":
            return _with_auth(str(b.get("uri") or ""), user, password)
        if kind == "webcam":  # the laptop's own / a USB camera: no address, no password
            index = int(b.get("index") or 0)
            if not 0 <= index < 10:
                raise WizardError("camera number 0-9")
            return f"webcam:{index}"
        if kind == "file" and self.allow_files:
            path = Path(str(b.get("path") or "")).expanduser()
            if not path.is_file():
                raise WizardError("file not found")
            return str(path.resolve())
        raise WizardError("choose a camera first")

    def probe(self, b: dict[str, Any]) -> dict[str, Any]:
        url = self.source_url(b)
        report = probe(url, seconds=4.0, live=b.get("kind") != "file")
        if b.get("kind") == "webcam":  # a USB camera has no sub-stream; it is resized on the edge
            report.advice = [a for a in report.advice if "720p" not in a] or ["ok: ready for site.yaml"]
        advice_ur = [next((ur for key, ur in ADVICE_UR.items() if key in a), a) for a in report.advice]
        out: dict[str, Any] = {"report": report.as_dict(), "advice_ur": advice_ur}
        frames = self._grab(url) if report.ok else []
        if frames:
            out["preview"], out["size"] = self._picture(frames[0]), [frames[0].shape[1], frames[0].shape[0]]
        return out

    def detect(self, b: dict[str, Any]) -> dict[str, Any]:
        if self.detector is None:
            raise WizardError("no detector model on this edge yet (models/README.md); the camera can still be saved")
        frames = self._grab(self.source_url(b), n=10, seconds=8.0)
        if not frames:
            raise WizardError("no picture from the camera")
        counts: Counter[str] = Counter()
        best: tuple[int, np.ndarray, list[Any]] = (-1, frames[0], [])
        t0 = time.perf_counter()
        for f in frames[::2]:
            dets = self.detector(f)
            for cls, k in Counter(d.cls for d in dets).items():
                counts[cls] = max(counts[cls], k)
            if len(dets) > best[0]:
                best = (len(dets), f, dets)
        ms = (time.perf_counter() - t0) * 1000 / len(frames[::2])
        return {
            "counts": dict(counts.most_common()),
            "ms_per_frame": round(ms),
            "picture": self._picture(best[1], best[2], boxes=True),
        }

    def save(self, b: dict[str, Any]) -> dict[str, Any]:
        cam, zone, src = b.get("camera") or {}, b.get("zone") or {}, b.get("source") or {}
        name, name_ur, name_roman = (str(cam.get(k) or "").strip()[:60] for k in ("name", "name_ur", "name_roman"))
        if not (name or name_ur):
            raise WizardError("give the camera a name")
        try:
            pts = [
                [round(min(max(float(x), 0.0), 1.0), 3), round(min(max(float(y), 0.0), 1.0), 3)]
                for x, y in zone.get("polygon") or []
            ]
        except (TypeError, ValueError) as exc:
            raise WizardError("the zone drawing is not valid") from exc
        if len(pts) < 3:
            raise WizardError("tap at least 3 points around the area to watch")
        url = self.source_url(src)
        cid = camera_id(camera_ids(self.site_file.read_text(encoding="utf-8")), name_roman or name or "camera")
        zone_name, zone_ur = str(zone.get("name") or "").strip()[:60], str(zone.get("name_ur") or "").strip()[:60]
        z: dict[str, Any] = {"id": slug(zone_name or zone_ur, "zone-1"), "name": zone_name or zone_ur or "Zone 1"}
        if zone_ur:
            z["name_ur"] = zone_ur
        z["polygon"] = Polygon(pts)
        entry: dict[str, Any] = {"id": cid, "name": name or name_ur}
        entry.update({k: v for k, v in (("name_ur", name_ur), ("name_roman", name_roman)) if v})
        backups = [p for p in (backup(self.site_file), backup(self.env_file)) if p]
        var = None
        if src.get("kind") == "file":
            entry["source"] = f"file:{url}"
        elif src.get("kind") == "webcam":
            entry["source"] = url
        else:
            var = env_var(cid)
            entry["rtsp_url_env"] = var
            set_env(self.env_file, var, url)  # first: a camera in site.yaml without its URL would not start
        entry["zones"] = [z]
        add_camera(self.site_file, entry)
        log.info("setup: camera %s added (%s)", cid, mask(url))
        return {
            "camera_id": cid,
            "env_var": var,
            "site_file": str(self.site_file),
            "backups": [str(p) for p in backups],
        }

    # --- pictures ---------------------------------------------------------------------------
    def _grab(self, url: str, n: int = 1, seconds: float = 6.0) -> list[np.ndarray]:
        cap = open_capture(url)
        frames: list[np.ndarray] = []
        t0 = time.monotonic()
        while cap.isOpened() and len(frames) < n and time.monotonic() - t0 < seconds:
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
        cap.release()
        return frames

    def _picture(self, frame: np.ndarray, dets: list[Any] | None = None, boxes: bool = False) -> str:
        """JPEG data URL, at most 960 px wide, every head blurred (and boxes drawn if asked)."""
        from ..privacy.face_blur import rider_head_proxy

        h, w = frame.shape[:2]
        if w > PREVIEW_W:
            frame = cv2.resize(frame, (PREVIEW_W, round(h * PREVIEW_W / w)), interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]
        if dets is None:
            dets = self.detector(frame) if self.detector is not None else []
        heads = [d.bbox for d in dets if d.cls == "person"]
        heads += [rider_head_proxy(d.bbox) for d in dets if d.cls in TWO_WHEELERS]
        out, _ = self.blur.apply(frame, heads)
        if boxes:
            colours = {"person": (80, 220, 80), "motorcycle": (0, 200, 255), "bicycle": (0, 200, 255)}
            for d in dets:
                x1, y1, x2, y2 = (int(d.bbox[0] * w), int(d.bbox[1] * h), int(d.bbox[2] * w), int(d.bbox[3] * h))
                cv2.rectangle(out, (x1, y1), (x2, y2), colours.get(d.cls, (255, 160, 0)), 2)
        ok, jpg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise WizardError("could not encode the picture")
        return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode("ascii")


def make_handler(wizard: Wizard, pin: str) -> type[BaseHTTPRequestHandler]:
    page = resources.files(__package__).joinpath("wizard.html").read_bytes()
    failures = {"n": 0, "until": 0.0}
    routes = {
        "/api/state": wizard.state,
        "/api/discover": wizard.discover,
        "/api/streams": wizard.streams,
        "/api/probe": wizard.probe,
        "/api/detect": wizard.detect,
        "/api/save": wizard.save,
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "jikimi-setup"

        def log_message(self, fmt: str, *args: Any) -> None:  # paths only; bodies hold passwords
            log.debug("setup %s", fmt % args)

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
            self.send_response(code)
            for k, v in (
                ("Content-Type", ctype),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
                ("Referrer-Policy", "no-referrer"),
                (
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
                ),
            ):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _authorized(self) -> bool:
            now = time.monotonic()
            if now < failures["until"]:
                self._json(429, {"error": "too many wrong PINs: wait a minute"})
                return False
            if hmac.compare_digest(self.headers.get("X-Setup-Pin", "").encode(), pin.encode()):
                failures["n"] = 0
                return True
            failures["n"] += 1
            if failures["n"] >= 5:
                failures["n"], failures["until"] = 0, now + 60.0
            self._json(401, {"error": "wrong PIN"})
            return False

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, page, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                if self._authorized():
                    self._json(200, wizard.state())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            route = routes.get(self.path)
            if route is None:
                self._json(404, {"error": "not found"})
                return
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_BODY:
                self._json(413, {"error": "request too large"})
                return
            try:
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("expected a JSON object")
                with wizard.lock:
                    self._json(200, route(body))
            except (WizardError, OnvifError, ValueError, OSError, yaml.YAMLError) as exc:
                self._json(400, {"error": str(exc)})

    return Handler


def lan_addresses() -> list[str]:
    """This machine's address on the LAN (the one a phone on the same Wi-Fi can reach)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outgoing interface
        return [s.getsockname()[0]]
    except OSError:
        return []
    finally:
        s.close()


ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - a phone on the LAN must reach the page; the PIN guards it


def serve(wizard: Wizard, host: str = ALL_INTERFACES, port: int = 8090, pin: str | None = None) -> None:
    pin = pin or f"{secrets.randbelow(10**6):06d}"
    httpd = ThreadingHTTPServer((host, port), make_handler(wizard, pin))
    where = lan_addresses() if host in (ALL_INTERFACES, "") else [host]
    print("Jikimi setup wizard (F20) - کیمرہ سیٹ اپ", flush=True)
    for ip in where or ["127.0.0.1"]:
        print(f"  open  http://{ip}:{port}   (a phone on the same Wi-Fi)", flush=True)
    print(f"  PIN   {pin}", flush=True)
    print("  stop  Ctrl+C, then restart the edge so it picks up the new cameras", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
