"""Position sizing.

Phase 1 uses fixed-fraction sizing (default: 100% of equity when long, 0% when
flat). Kelly, vol-targeting, and risk-parity are deferred to later phases.
"""

from __future__ import annotations


def fixed_fraction(equity: float, fraction: float = 1.0) -> float:
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be in [0, 1], got {fraction}")
    return equity * fraction
