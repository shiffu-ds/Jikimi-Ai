"""Metrics from the evaluation protocol (plan Section 14.2), numpy-only."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

import numpy as np
from scipy.stats import rankdata


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Mann-Whitney AUC with tie correction."""
    y = np.asarray(labels, dtype=bool)
    s = np.asarray(scores, dtype=np.float64)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = rankdata(s)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def precision_at_recall(labels: Sequence[int], scores: Sequence[float], recall: float = 0.8) -> float:
    y = np.asarray(labels, dtype=bool)
    order = np.argsort(-np.asarray(scores, dtype=np.float64))
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(~y)
    rec = tp / max(int(y.sum()), 1)
    prec = tp / np.maximum(tp + fp, 1)
    ok = rec >= recall
    return float(prec[ok].max()) if ok.any() else 0.0


def expected_calibration_error(labels: Sequence[int], probs: Sequence[float], bins: int = 10) -> float:
    y = np.asarray(labels, dtype=np.float64)
    p = np.asarray(probs, dtype=np.float64)
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in pairwise(edges):
        m = (p >= lo) & (p < hi) if hi < 1 else (p >= lo) & (p <= hi)
        if m.any():
            ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)


def recall_at_k(ranked_ids: Sequence[Sequence[str]], relevant: Sequence[set[str]], k: int = 10) -> float:
    hits = [bool(set(r[:k]) & rel) for r, rel in zip(ranked_ids, relevant, strict=True) if rel]
    return float(np.mean(hits)) if hits else float("nan")


def mean_reciprocal_rank(ranked_ids: Sequence[Sequence[str]], relevant: Sequence[set[str]]) -> float:
    rr = []
    for r, rel in zip(ranked_ids, relevant, strict=True):
        if not rel:
            continue
        rank = next((i + 1 for i, x in enumerate(r) if x in rel), None)
        rr.append(0.0 if rank is None else 1.0 / rank)
    return float(np.mean(rr)) if rr else float("nan")


def fa_per_camera_hour(false_alarms: int, camera_hours: float) -> float:
    return false_alarms / camera_hours if camera_hours > 0 else float("nan")


def conformal_calibration_curve(
    normal_pvalues: Sequence[float], alphas: Sequence[float] = (0.005, 0.01, 0.02, 0.05, 0.1)
) -> list[tuple[float, float]]:
    """Empirical false-alarm rate vs alpha on held-out *normal* units (F7 acceptance: <= 1.5 alpha)."""
    p = np.asarray(normal_pvalues, dtype=np.float64)
    return [(a, float((p <= a).mean())) for a in alphas]
