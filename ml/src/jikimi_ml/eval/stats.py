"""Statistics for honest reporting (plan Sections 14.3 and 14.7).

Every number in the results table gets a confidence interval; comparisons use paired tests.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats as st


@dataclass(frozen=True)
class Interval:
    estimate: float
    low: float
    high: float
    level: float = 0.95

    def __str__(self) -> str:
        return f"{self.estimate:.3f} [{self.low:.3f}, {self.high:.3f}]"


def wilson(successes: int, n: int, level: float = 0.95) -> Interval:
    """Wilson score interval for a proportion (recall, precision).

    85/100 -> 0.85 [0.767, 0.907] (plan Section 14.7: "approx 0.77-0.91").
    """
    if n == 0:
        return Interval(float("nan"), 0.0, 1.0, level)
    z = st.norm.ppf(1 - (1 - level) / 2)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Interval(p, max(0.0, centre - half), min(1.0, centre + half), level)


def poisson_upper(events: int, level: float = 0.95) -> float:
    """One-sided upper bound on a Poisson mean: 0 -> 3.0 ("rule of three"), 1 -> 4.74, 2 -> 6.30."""
    return float(st.chi2.ppf(level, 2 * (events + 1)) / 2)


def fa_rate_upper(false_alarms: int, camera_hours: float, level: float = 0.95) -> float:
    """Upper bound on false alarms per camera-hour: 1 FA in 50 h -> 0.095 < 0.1 target."""
    return poisson_upper(false_alarms, level) / camera_hours


def bootstrap_ci(
    values: Sequence[float] | np.ndarray,
    statistic: Callable[[np.ndarray], float] = lambda x: float(np.mean(x)),
    n_resamples: int = 1000,
    level: float = 0.95,
    seed: int = 0,
) -> Interval:
    """Percentile bootstrap over units (clips, videos, queries)."""
    x = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_resamples, len(x)))
    boots = np.array([statistic(x[i]) for i in idx])
    lo, hi = np.quantile(boots, [(1 - level) / 2, 1 - (1 - level) / 2])
    return Interval(statistic(x), float(lo), float(hi), level)


def cluster_bootstrap_ci(
    labels: Sequence[int] | np.ndarray,
    scores: Sequence[float] | np.ndarray,
    groups: Sequence[object] | np.ndarray,
    statistic: Callable[[np.ndarray, np.ndarray], float],
    n_resamples: int = 1000,
    level: float = 0.95,
    seed: int = 0,
) -> Interval:
    """Percentile bootstrap that resamples whole groups (episodes, videos, sites).

    Windows cut from one episode are correlated; resampling windows instead of episodes gives a
    confidence interval that is too narrow.
    """
    y, s = np.asarray(labels), np.asarray(scores, dtype=np.float64)
    _, inv = np.unique(np.asarray(groups), return_inverse=True)
    members = [np.flatnonzero(inv == k) for k in range(int(inv.max()) + 1)]
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_resamples):
        idx = np.concatenate([members[k] for k in rng.integers(0, len(members), len(members))])
        v = statistic(y[idx], s[idx])
        if not math.isnan(v):
            boots.append(v)
    lo, hi = np.quantile(boots, [(1 - level) / 2, 1 - (1 - level) / 2])
    return Interval(statistic(y, s), float(lo), float(hi), level)


def paired_bootstrap(
    a: Sequence[float] | np.ndarray,
    b: Sequence[float] | np.ndarray,
    n_resamples: int = 2000,
    seed: int = 0,
) -> tuple[Interval, float]:
    """CI of mean(b - a) on the same units, and the two-sided bootstrap p-value."""
    d = np.asarray(b, dtype=np.float64) - np.asarray(a, dtype=np.float64)
    ci = bootstrap_ci(d, n_resamples=n_resamples, seed=seed)
    rng = np.random.default_rng(seed + 1)
    centred = d - d.mean()
    boots = np.array([centred[rng.integers(0, len(d), len(d))].mean() for _ in range(n_resamples)])
    p = float((np.abs(boots) >= abs(d.mean())).mean())
    return ci, p


def mcnemar(a_correct: Sequence[bool], b_correct: Sequence[bool]) -> tuple[int, int, float]:
    """Exact McNemar test on paired decisions: ``(b01, b10, p_value)``."""
    a = np.asarray(a_correct, dtype=bool)
    b = np.asarray(b_correct, dtype=bool)
    b01 = int(np.sum(~a & b))
    b10 = int(np.sum(a & ~b))
    n = b01 + b10
    p = 1.0 if n == 0 else float(min(1.0, 2 * st.binom.cdf(min(b01, b10), n, 0.5)))
    return b01, b10, p
