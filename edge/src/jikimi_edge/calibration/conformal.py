"""Split-conformal p-values (F7, plan Section 8.7).

For normal-footage calibration scores ``s_1..s_n`` and a new score ``s``::

    p(s) = (1 + #{s_i >= s}) / (n + 1)

Alerting only when ``p <= alpha`` keeps the false-alarm rate on normal footage <= alpha under
exchangeability. The guarantee is *marginal* and breaks under distribution shift, hence weekly
recalibration, KS drift checks and separate sets per event mode (Ramadan, Chand raat, ...).
The smallest possible p-value is ``1 / (n + 1)``: alpha = 0.01 needs n >= 99 (Section 14.7).
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable


class SplitConformal:
    def __init__(self, cal_scores: Iterable[float]) -> None:
        self.cal = sorted(float(s) for s in cal_scores)
        self.n = len(self.cal)

    def p_value(self, s: float) -> float:
        n_ge = self.n - bisect.bisect_left(self.cal, s)  # count of cal scores >= s
        return (1 + n_ge) / (self.n + 1)

    @property
    def min_p(self) -> float:
        return 1.0 / (self.n + 1)

    def threshold(self, alpha: float) -> float:
        """Smallest score whose p-value is <= alpha (``inf`` if alpha < 1/(n+1))."""
        k = int(alpha * (self.n + 1)) - 1  # need #{s_i >= s} <= k
        if k < 0:
            return float("inf")
        if k >= self.n:
            return float("-inf")
        return self.cal[self.n - k - 1] + 1e-12
