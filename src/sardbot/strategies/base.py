"""Strategy contract.

A Strategy turns OHLCV bars into a target-position series. Phase 1 only uses
{0, 1} (flat / long). The contract is intentionally narrow so the backtester
stays the only thing that knows about cash, fees, and equity.

CRITICAL: signal at index t means "the desired position from bar t+1 open
onward." The backtester enforces this — the strategy must not look ahead by
using close[t] to set position from open[t]. See engine/backtester.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    name: str = "abstract"

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return a pd.Series indexed like df with values in {-1, 0, 1}."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name})"
