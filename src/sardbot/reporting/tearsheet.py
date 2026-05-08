"""Equity curve + drawdown plotting."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from sardbot.engine.backtester import BacktestResult


def plot_equity_curves(
    results: dict[str, BacktestResult],
    output_path: Path | str | None = None,
    title: str = "Equity curves",
) -> plt.Figure:
    fig, (ax_eq, ax_dd) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 1]})

    for name, r in results.items():
        eq = r.equity_curve
        ax_eq.plot(eq.index, eq.values, label=name, linewidth=1.5)
        running_max = eq.cummax()
        dd = eq / running_max - 1.0
        ax_dd.fill_between(dd.index, dd.values, 0, alpha=0.4, label=name)

    ax_eq.set_ylabel("Equity ($)")
    ax_eq.set_title(title)
    ax_eq.legend(loc="upper left")
    ax_eq.grid(True, alpha=0.3)

    ax_dd.set_ylabel("Drawdown")
    ax_dd.set_xlabel("Date")
    ax_dd.grid(True, alpha=0.3)

    fig.tight_layout()
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
    return fig


def format_table(table: pd.DataFrame) -> str:
    fmt = table.copy()
    for col in ("total_return", "cagr", "max_drawdown", "win_rate"):
        if col in fmt:
            fmt[col] = fmt[col].map(lambda x: f"{x:.2%}")
    if "sharpe" in fmt:
        fmt["sharpe"] = fmt["sharpe"].map(lambda x: f"{x:.2f}")
    if "final_equity" in fmt:
        fmt["final_equity"] = fmt["final_equity"].map(lambda x: f"${x:,.0f}")
    if "num_trades" in fmt:
        fmt["num_trades"] = fmt["num_trades"].map(lambda x: f"{int(x)}")
    return fmt.to_string()
