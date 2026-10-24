"""Two-sample Kolmogorov-Smirnov drift test (Section 10.6), numpy-only."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class KSResult:
    statistic: float
    p_value: float
    drift: bool


def _kolmogorov_q(lam: float) -> float:
    """Survival function of the Kolmogorov distribution."""
    if lam < 1e-3:
        return 1.0
    total = 0.0
    for j in range(1, 101):
        term = 2 * (-1) ** (j - 1) * math.exp(-2 * j * j * lam * lam)
        total += term
        if abs(term) < 1e-10:
            break
    return min(max(total, 0.0), 1.0)


def ks_2samp(a: Sequence[float], b: Sequence[float], alpha: float = 0.01) -> KSResult:
    x = np.sort(np.asarray(a, dtype=np.float64))
    y = np.sort(np.asarray(b, dtype=np.float64))
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return KSResult(0.0, 1.0, False)
    grid = np.concatenate([x, y])
    cdf1 = np.searchsorted(x, grid, side="right") / n1
    cdf2 = np.searchsorted(y, grid, side="right") / n2
    d = float(np.max(np.abs(cdf1 - cdf2)))
    en = math.sqrt(n1 * n2 / (n1 + n2))
    p = _kolmogorov_q((en + 0.12 + 0.11 / en) * d)
    return KSResult(d, p, p < alpha)
