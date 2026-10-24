"""Fetch / export the models a profile needs (plan Section 7.19 `scripts/download_models.py`).

Ultralytics is used only here (export time), never on the edge:

    uv run --with ultralytics python scripts/download_models.py --profile laptop

Every downloaded file is checked against a pinned SHA-256 when one is listed.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

MODELS = Path("models")
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_SHA256: str | None = None  # pin after the first verified download

EXPORTS = {
    "laptop": [
        ("yolo11n.pt", ["format=openvino", "int8=True", "imgsz=640"]),
        ("yolo11n-pose.pt", ["format=openvino", "int8=True", "imgsz=640"]),
    ],
    "laptop-yolo26": [("yolo26n.pt", ["format=openvino", "int8=True", "imgsz=640"])],
    "onnx-cpu": [("yolo11n.pt", ["format=onnx", "imgsz=640", "simplify=True"])],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: Path, expected: str | None) -> None:
    if dest.exists():
        print(f"ok      {dest}")
        return
    print(f"fetch   {url}")
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as fh:  # noqa: S310 - pinned https URL
        shutil.copyfileobj(r, fh)
    digest = sha256(dest)
    if expected and digest != expected:
        dest.unlink()
        sys.exit(f"checksum mismatch for {dest}: {digest}")
    print(f"sha256  {digest}  {dest.name}")


def export(profile: str) -> None:
    if shutil.which("yolo") is None:
        print("Ultralytics CLI not found: run with `uv run --with ultralytics python scripts/download_models.py ...`")
        return
    for weights, args in EXPORTS.get(profile, []):
        print(f"export  {weights} {' '.join(args)}")
        subprocess.run(["yolo", "export", f"model={weights}", *args], cwd=MODELS, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="laptop")
    ap.add_argument("--with-yunet", action="store_true", help="also fetch the YuNet face detector")
    args = ap.parse_args()
    MODELS.mkdir(exist_ok=True)
    if args.with_yunet:
        fetch(YUNET_URL, MODELS / "face_detection_yunet_2023mar.onnx", YUNET_SHA256)
    export(args.profile)


if __name__ == "__main__":
    main()
