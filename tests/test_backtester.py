import math

import numpy as np
import pandas as pd

from sardbot.engine.backtester import run_backtest
from sardbot.engine.costs import CostModel
from sardbot.strategies.benchmarks import BuyAndHold
from sardbot.strategies.sma_crossover import SMACrossover


def _make_ohlcv(closes, opens=None):
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    opens = opens if opens is not None else closes
    return pd.DataFrame({"open": opens, "high": closes, "low": closes, "close": closes,
                         "volume": [1.0] * n}, index=idx)


def test_zero_cost_buy_and_hold_equals_price_return():
    """Sanity: with zero costs, BuyAndHold equity = capital * (close[-1] / open[1]).

    The convention is: signal[0]=1 -> fill at open[1]. Last MTM at close[-1].
    """
    closes = [100, 105, 110, 120, 130]
    opens = [99, 102, 108, 115, 125]
    df = _make_ohlcv(closes, opens)

    r = run_backtest(df, BuyAndHold(), CostModel(fee_bps=0, slippage_bps=0), 10_000)
    expected = 10_000 * (closes[-1] / opens[1])
    assert math.isclose(r.equity_curve.iloc[-1], expected, rel_tol=1e-9)


def test_costs_reduce_equity():
    df = _make_ohlcv(np.linspace(100, 110, 50))
    free = run_backtest(df, BuyAndHold(), CostModel(fee_bps=0, slippage_bps=0), 10_000)
    paid = run_backtest(df, BuyAndHold(), CostModel(fee_bps=10, slippage_bps=5), 10_000)
    assert paid.equity_curve.iloc[-1] < free.equity_curve.iloc[-1]


def test_no_lookahead_signal_t_fills_at_open_t_plus_1():
    """Engineer a price spike: huge jump on day 5 close, drop next open.

    A look-ahead engine would catch the spike. We must not.
    """
    closes = [100] * 4 + [500] + [100] * 5  # spike on bar index 4
    opens = [100] * 4 + [100] + [100] * 5
    df = _make_ohlcv(closes, opens)

    class GreedyOnSpike:
        name = "spike"
        def generate_signals(self, df):
            sig = (df["close"] > 200).astype(int)
            return sig

    r = run_backtest(df, GreedyOnSpike(), CostModel(fee_bps=0, slippage_bps=0), 10_000)
    # Signal fires at t=4 (close=500). Fill happens at t=5 open=100.
    # Then signal goes back to 0 at t=5; fill at t=6 open=100.
    # So we bought at 100 and sold at 100: ~0 PnL, no spike capture.
    assert math.isclose(r.equity_curve.iloc[-1], 10_000, rel_tol=1e-9)


def test_sma_crossover_runs_endtoend():
    # Random walk with drift, long enough to give signals work to do.
    rng = np.random.default_rng(0)
    closes = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 500))
    df = _make_ohlcv(closes)
    r = run_backtest(df, SMACrossover(fast=10, slow=50), CostModel(), 10_000)
    assert len(r.equity_curve) == len(df)
    assert r.equity_curve.iloc[0] == 10_000
    assert (r.equity_curve > 0).all()


class _LongFromBar(BuyAndHold):
    """Helper strategy: signal=0 until `start_bar`, then signal=1 forever."""
    name = "long_from_bar"
    def __init__(self, start_bar: int):
        self.start_bar = start_bar
    def generate_signals(self, df):
        sig = pd.Series(0, index=df.index, dtype=int, name="signal")
        sig.iloc[self.start_bar:] = 1
        return sig


def test_stop_loss_caps_loss_on_crash():
    """With a tight ATR stop, a crash bar should trigger exit at the stop level
    rather than ride all the way down. ATR needs ~14 bars of warmup, so we
    enter only after warmup is done.
    """
    n = 50
    closes = [100.0] * 30 + [50.0] + [55.0] * (n - 31)
    highs = [101.0] * 30 + [101.0] + [56.0] * (n - 31)
    lows = [99.0] * 30 + [50.0] + [54.0] * (n - 31)
    opens = [99.5] * n
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                       "volume": [1.0] * n}, index=idx)
    strat = _LongFromBar(start_bar=20)  # enter at bar 21 open, ATR is defined

    no_stop = run_backtest(df, strat, CostModel(0, 0), 10_000)
    with_stop = run_backtest(df, strat, CostModel(0, 0), 10_000,
                             stop_loss_atr_multiple=2.0, atr_window=14)
    # Stop should fire on the crash bar; final equity well above the no-stop run.
    assert with_stop.equity_curve.iloc[-1] > no_stop.equity_curve.iloc[-1] * 1.3


def test_stop_out_suppresses_re_entry_until_signal_cycles():
    """After a stop-out, we must not immediately re-enter while signal is still 1.
    Wait until signal flips to 0, then back to 1.
    """
    n = 50
    closes = [100.0] * 30 + [50.0] + [55.0] * (n - 31)
    highs = [101.0] * 30 + [101.0] + [56.0] * (n - 31)
    lows = [99.0] * 30 + [50.0] + [54.0] * (n - 31)
    opens = [99.5] * n
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                       "volume": [1.0] * n}, index=idx)
    strat = _LongFromBar(start_bar=20)
    r = run_backtest(df, strat, CostModel(0, 0), 10_000,
                     stop_loss_atr_multiple=2.0, atr_window=14)
    # After stop-out at bar 30, signal stays 1 forever — we must stay flat.
    final_units = r.positions.iloc[-1]
    assert final_units == 0.0


def test_equity_never_negative_under_long_only():
    closes = np.linspace(100, 1, 100)  # 99% drawdown
    df = _make_ohlcv(closes)
    r = run_backtest(df, BuyAndHold(), CostModel(), 10_000)
    assert (r.equity_curve >= 0).all()
