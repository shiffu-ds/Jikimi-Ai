"""PakSnatch loading, group-disjoint splits and augmentation (plan Sections 9.3 and 9.7).

Windows are stored as ``.npz``: ``x (N, 3, 32, 17, 2)``, ``y (N,)``, ``group (N,)``. For real data
``group`` is the actor/location id, so the test split is actor- and location-disjoint (the model
must not memorise actors' clothes). ``labels.jsonl`` rows follow Section 9.7.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from jikimi_contracts.detections import FLIP_PAIRS as FLIP


def load_npz(path: str | Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as d:
        return {k: d[k] for k in d.files}


def group_split(groups: np.ndarray, val: float = 0.15, test: float = 0.15, salt: str = "pakspl-v1") -> np.ndarray:
    """Deterministic group-disjoint split: ``0`` train, ``1`` val, ``2`` test for every row."""
    out = np.zeros(len(groups), dtype=np.int8)
    for g in np.unique(groups):
        h = int(hashlib.sha256(f"{salt}:{g}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        out[groups == g] = 2 if h < test else 1 if h < test + val else 0
    return out


def augment(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Horizontal flip (left/right keypoints swapped), time jitter, keypoint dropout (occlusion)."""
    x = x.copy()
    if rng.random() < 0.5:
        x[0] = -x[0]
        for a, b in FLIP:
            x[:, :, [a, b]] = x[:, :, [b, a]]
    shift = int(rng.integers(-2, 3))
    if shift:
        x = np.roll(x, shift, axis=1)
    drop = rng.random(x.shape[2]) < 0.08
    x[:, :, drop, :] = 0.0
    x[:2] += rng.normal(0, 0.01, x[:2].shape).astype(np.float32)
    return x


def batches(x: np.ndarray, y: np.ndarray, batch: int, rng: np.random.Generator | None = None, train: bool = False) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    idx = rng.permutation(len(y)) if rng is not None else np.arange(len(y))
    for i in range(0, len(idx), batch):
        sel = idx[i : i + batch]
        xb = np.stack([augment(x[j], rng) for j in sel]) if (train and rng is not None) else x[sel]
        yield xb.astype(np.float32), y[sel].astype(np.float32)


def read_labels(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not row.get("consent_ids"):
                raise ValueError(f"{row.get('clip_id')}: no consent ids - clip cannot enter the dataset")
            rows.append(row)
    return rows
