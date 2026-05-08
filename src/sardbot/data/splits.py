"""In-sample / out-of-sample split.

The OOS slice is sacred: do not iterate against it. See data/README.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Split:
    in_sample: pd.DataFrame
    out_of_sample: pd.DataFrame

    @property
    def in_sample_range(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.in_sample.index[0], self.in_sample.index[-1]

    @property
    def out_of_sample_range(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.out_of_sample.index[0], self.out_of_sample.index[-1]


def split_by_fraction(df: pd.DataFrame, oos_fraction: float = 0.2) -> Split:
    if not 0 < oos_fraction < 1:
        raise ValueError(f"oos_fraction must be in (0, 1), got {oos_fraction}")
    if df.empty:
        raise ValueError("Cannot split empty dataframe")

    cutoff = int(len(df) * (1 - oos_fraction))
    if cutoff == 0 or cutoff == len(df):
        raise ValueError(f"Split would yield empty partition (n={len(df)}, frac={oos_fraction})")

    return Split(in_sample=df.iloc[:cutoff], out_of_sample=df.iloc[cutoff:])
