"""Rule-based loitering score (F2 Tier 1, plan Section 8.3)."""

from __future__ import annotations


def loitering_score(passes: int, riders: int, slowdowns_near_ped: int, dwell_s: float) -> float:
    """0..1. Saturates at 3 passes in the window, a pillion, 2 slowdowns and 2 min dwell."""
    return (
        0.4 * min(passes / 3.0, 1.0)
        + 0.2 * (1.0 if riders >= 2 else 0.0)
        + 0.3 * min(slowdowns_near_ped / 2.0, 1.0)
        + 0.1 * min(dwell_s / 120.0, 1.0)
    )
