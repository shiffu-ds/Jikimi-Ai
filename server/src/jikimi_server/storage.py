"""Object storage (clips, keyframes, thumbnails, snapshots, evidence PDFs).

Improvement over plan v2.3 (ADR-018): the plan used MinIO, whose community Docker images
stopped in Oct 2025 and whose repository was archived in Feb 2026. The laptop/pilot default is
a local filesystem store (0 MB extra RAM); tamper evidence does not depend on bucket object
lock because every file is hash-pinned in signed manifests, Merkle batches and OpenTimestamps.
An S3-compatible backend (AWS S3 with Object Lock, or a maintained self-hosted store) can be
added behind the same three methods for multi-site production.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class LocalStore:
    scheme = "local://"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("key escapes the storage root")
        return p

    def put_bytes(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(p)
        return self.scheme + key

    def put_file(self, key: str, src: str | Path) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, p)
        return self.scheme + key

    def path(self, uri_or_key: str) -> Path:
        key = uri_or_key[len(self.scheme) :] if uri_or_key.startswith(self.scheme) else uri_or_key
        return self._path(key)

    def exists(self, uri_or_key: str) -> bool:
        return self.path(uri_or_key).exists()

    def delete(self, uri_or_key: str) -> None:
        self.path(uri_or_key).unlink(missing_ok=True)
