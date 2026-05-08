"""Command-line entry point.

Subcommands:
- `sardbot fetch`: download OHLCV from the configured exchange and cache it.
- `sardbot backtest`: run a strategy and (optionally) compare against benchmarks.
- `sardbot walkforward`: rolling-window evaluation per strategy.
- `sardbot paper-trade`: one paper-trading iteration (fetch + signal + log).
- `sardbot status`: show current paper-trading state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import click

from sardbot.config import load_config
from sardbot.data.loader import CCXTLoader, check_gaps
from sardbot.data.splits import split_by_fraction
from sardbot.engine.backtester import run_backtest
from sardbot.engine.costs import CostModel
from sardbot.engine.walkforward import walk_forward
from sardbot.metrics.performance import summary
from sardbot.reporting.compare import compare
from sardbot.reporting.tearsheet import format_table, plot_equity_curves
from sardbot.strategies.benchmarks import BuyAndHold
from sardbot.strategies.donchian import DonchianBreakout
from sardbot.strategies.sma_crossover import SMACrossover

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--symbol", default=None, help="e.g. BTC/USDT")
@click.option("--timeframe", default=None, help="e.g. 1d")
@click.option("--since", default=None, help="ISO date e.g. 2018-01-01")
@click.option("--exchange", default=None, help="ccxt exchange id")
def fetch(symbol: str | None, timeframe: str | None, since: str | None, exchange: str | None) -> None:
    cfg = load_config()
    symbol = symbol or cfg.market.symbol
    timeframe = timeframe or cfg.market.timeframe
    exchange = exchange or cfg.market.exchange
    since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if since else cfg.market.since_dt()

    loader = CCXTLoader(exchange_id=exchange)
    df = loader.fetch_ohlcv(symbol, timeframe, since_dt, cache_dir=cfg.paths.data_raw)
    gaps = check_gaps(df, timeframe)
    click.echo(f"rows={len(df)}  range={df.index[0]} -> {df.index[-1]}  gaps={gaps}")


def _make_strategy(name: str, fast: int, slow: int, entry: int, exit_: int,
                   trend_filter: int | None):
    if name == "sma_crossover":
        return SMACrossover(fast=fast, slow=slow)
    if name == "donchian_breakout":
        return DonchianBreakout(entry=entry, exit_=exit_, trend_filter_window=trend_filter)
    if name == "buy_and_hold":
        return BuyAndHold()
    raise click.BadParameter(f"unknown strategy '{name}'")


@cli.command()
@click.option("--strategy", "strategy_name", default=None)
@click.option("--fast", default=None, type=int, help="SMA fast window")
@click.option("--slow", default=None, type=int, help="SMA slow window")
@click.option("--entry", default=None, type=int, help="Donchian entry lookback")
@click.option("--exit", "exit_", default=None, type=int, help="Donchian exit lookback")
@click.option("--trend-filter", default=None, type=int,
              help="Donchian trend filter window (e.g. 200 for Faber-style gate)")
@click.option("--stop-atr", default=None, type=float,
              help="ATR stop-loss multiple (e.g. 2.0 for Turtle 2N rule)")
@click.option("--atr-window", default=None, type=int, help="ATR period (default 14)")
@click.option("--symbol", default=None)
@click.option("--timeframe", default=None)
@click.option("--start", default=None, help="ISO date filter (in-sample only by default)")
@click.option("--end", default=None, help="ISO date filter")
@click.option("--compare-benchmarks/--no-compare-benchmarks", default=True)
@click.option("--use-oos", is_flag=True, help="Include the out-of-sample slice. Use ONLY for the final eval.")
@click.option("--output", default=None, help="PNG path for equity-curve plot.")
def backtest(
    strategy_name: str | None,
    fast: int | None,
    slow: int | None,
    entry: int | None,
    exit_: int | None,
    trend_filter: int | None,
    stop_atr: float | None,
    atr_window: int | None,
    symbol: str | None,
    timeframe: str | None,
    start: str | None,
    end: str | None,
    compare_benchmarks: bool,
    use_oos: bool,
    output: str | None,
) -> None:
    cfg = load_config()
    strategy_name = strategy_name or cfg.strategy.default
    fast = fast if fast is not None else cfg.strategy.sma_crossover.fast
    slow = slow if slow is not None else cfg.strategy.sma_crossover.slow
    entry = entry if entry is not None else cfg.strategy.donchian_breakout.entry
    exit_ = exit_ if exit_ is not None else cfg.strategy.donchian_breakout.exit_
    trend_filter = trend_filter if trend_filter is not None else cfg.strategy.donchian_breakout.trend_filter_window
    stop_atr = stop_atr if stop_atr is not None else cfg.risk.stop_loss_atr_multiple
    atr_window = atr_window if atr_window is not None else cfg.risk.atr_window
    symbol = symbol or cfg.market.symbol
    timeframe = timeframe or cfg.market.timeframe

    loader = CCXTLoader(exchange_id=cfg.market.exchange)
    df = loader.fetch_ohlcv(symbol, timeframe, cfg.market.since_dt(), cache_dir=cfg.paths.data_raw)

    if start:
        df = df.loc[df.index >= datetime.fromisoformat(start).replace(tzinfo=timezone.utc)]
    if end:
        df = df.loc[df.index <= datetime.fromisoformat(end).replace(tzinfo=timezone.utc)]

    if not use_oos:
        sp = split_by_fraction(df, cfg.backtest.oos_fraction)
        df = sp.in_sample
        click.echo(f"In-sample: {df.index[0]} -> {df.index[-1]}  ({len(df)} bars)")
        click.echo(f"OOS reserved: {sp.out_of_sample.index[0]} -> {sp.out_of_sample.index[-1]}  ({len(sp.out_of_sample)} bars)")
    else:
        click.echo("WARNING: running on full dataset including out-of-sample.")

    cost_model = CostModel(fee_bps=cfg.backtest.fee_bps, slippage_bps=cfg.backtest.slippage_bps)
    strategy = _make_strategy(strategy_name, fast, slow, entry, exit_, trend_filter)

    if stop_atr is not None:
        click.echo(f"Risk overlay: stop-loss = {stop_atr} x ATR({atr_window})")

    if compare_benchmarks:
        table, results = compare(df, strategy, cost_model, cfg.backtest.initial_capital,
                                 stop_loss_atr_multiple=stop_atr, atr_window=atr_window)
        click.echo(format_table(table))
        if output:
            plot_equity_curves(results, output_path=output)
            click.echo(f"\nPlot: {output}")
    else:
        result = run_backtest(df, strategy, cost_model, cfg.backtest.initial_capital,
                              stop_loss_atr_multiple=stop_atr, atr_window=atr_window)
        s = summary(result)
        for k, v in s.items():
            click.echo(f"  {k:>14s} = {v}")


@cli.command()
@click.option("--strategy", "strategy_name", default=None)
@click.option("--fast", default=None, type=int)
@click.option("--slow", default=None, type=int)
@click.option("--entry", default=None, type=int)
@click.option("--exit", "exit_", default=None, type=int)
@click.option("--trend-filter", default=None, type=int)
@click.option("--stop-atr", default=None, type=float)
@click.option("--atr-window", default=None, type=int)
@click.option("--window-days", default=180, type=int, help="Test window length")
@click.option("--warmup-days", default=250, type=int, help="History before first window")
@click.option("--use-oos", is_flag=True, help="Include out-of-sample slice (final eval only).")
def walkforward(
    strategy_name: str | None,
    fast: int | None, slow: int | None,
    entry: int | None, exit_: int | None,
    trend_filter: int | None,
    stop_atr: float | None, atr_window: int | None,
    window_days: int, warmup_days: int, use_oos: bool,
) -> None:
    cfg = load_config()
    strategy_name = strategy_name or cfg.strategy.default
    fast = fast if fast is not None else cfg.strategy.sma_crossover.fast
    slow = slow if slow is not None else cfg.strategy.sma_crossover.slow
    entry = entry if entry is not None else cfg.strategy.donchian_breakout.entry
    exit_ = exit_ if exit_ is not None else cfg.strategy.donchian_breakout.exit_
    trend_filter = trend_filter if trend_filter is not None else cfg.strategy.donchian_breakout.trend_filter_window
    stop_atr = stop_atr if stop_atr is not None else cfg.risk.stop_loss_atr_multiple
    atr_window = atr_window if atr_window is not None else cfg.risk.atr_window

    loader = CCXTLoader(exchange_id=cfg.market.exchange)
    df = loader.fetch_ohlcv(cfg.market.symbol, cfg.market.timeframe, cfg.market.since_dt(),
                            cache_dir=cfg.paths.data_raw)
    if not use_oos:
        df = split_by_fraction(df, cfg.backtest.oos_fraction).in_sample

    cost_model = CostModel(fee_bps=cfg.backtest.fee_bps, slippage_bps=cfg.backtest.slippage_bps)
    strategy = _make_strategy(strategy_name, fast, slow, entry, exit_, trend_filter)
    r = walk_forward(df, strategy, cost_model, cfg.backtest.initial_capital,
                     test_window_days=window_days, warmup_days=warmup_days,
                     stop_loss_atr_multiple=stop_atr, atr_window=atr_window)

    click.echo(f"\n=== {strategy.name} — walk-forward ({window_days}-day windows) ===")
    click.echo(r.windows.to_string(index=False))
    click.echo("\nSummary:")
    for k, v in r.summary.items():
        if isinstance(v, float):
            if "return" in k or "dd" in k or "pct" in k:
                click.echo(f"  {k:>14s} = {v:.2%}")
            else:
                click.echo(f"  {k:>14s} = {v:.4f}")
        else:
            click.echo(f"  {k:>14s} = {v}")


@cli.command("paper-trade")
@click.option("--symbol", default=None)
@click.option("--initial-capital", default=None, type=float)
@click.option("--kill-switch-dd", default=-0.25, type=float,
              help="Kill switch drawdown threshold (default -25%)")
def paper_trade(symbol: str | None, initial_capital: float | None, kill_switch_dd: float) -> None:
    from sardbot.paper.notifier import make_notifier_from_env
    from sardbot.paper.storage import make_storage_from_env
    from sardbot.paper.trader import run_once

    cfg = load_config()
    sym = symbol or cfg.market.symbol
    cap = initial_capital if initial_capital is not None else cfg.backtest.initial_capital

    storage = make_storage_from_env()
    notifier = make_notifier_from_env()

    summary = run_once(
        storage=storage, notifier=notifier,
        symbol=sym, timeframe=cfg.market.timeframe,
        initial_capital=cap,
        fee_bps=cfg.backtest.fee_bps, slippage_bps=cfg.backtest.slippage_bps,
        kill_switch_dd=kill_switch_dd,
        cache_dir=cfg.paths.data_raw,
        strategy_params={
            "entry": cfg.strategy.donchian_breakout.entry,
            "exit": cfg.strategy.donchian_breakout.exit_,
            "trend_filter": cfg.strategy.donchian_breakout.trend_filter_window or 200,
            "stop_atr": cfg.risk.stop_loss_atr_multiple or 2.0,
            "atr_window": cfg.risk.atr_window,
        },
    )

    click.echo(f"bar:      {summary['bar']}")
    click.echo(f"signal:   {summary['signal']}")
    click.echo(f"is_long:  {summary['is_long']}")
    click.echo(f"equity:   ${summary['equity']:,.2f}")
    click.echo(f"drawdown: {summary['drawdown']:.2%}")
    if summary['events']:
        click.echo(f"events:   {len(summary['events'])} this run")
        for ev in summary['events']:
            click.echo(f"  - {ev['type']} @ ${ev['price']:,.2f} ({ev['reason']})")
    if summary['alert']:
        click.echo(f"ALERT:    {summary['alert']['message']}")


@cli.command("status")
def status() -> None:
    from sardbot.paper.state import State
    from sardbot.paper.storage import make_storage_from_env
    from sardbot.paper.trader import EQUITY_PATH, STATE_PATH, TRADES_PATH

    storage = make_storage_from_env()
    raw = storage.read_text(STATE_PATH)
    if raw is None:
        click.echo("No paper-trading state found. Run `sardbot paper-trade` first.")
        return

    state = State.from_json(raw)
    click.echo(f"strategy:    {state.strategy}")
    click.echo(f"symbol:      {state.symbol}")
    click.echo(f"last bar:    {state.last_processed_bar}")
    click.echo(f"last run:    {state.last_run}")
    click.echo(f"position:    {'LONG' if state.position.is_long else 'flat'}")
    if state.position.is_long:
        click.echo(f"  entry:     ${state.position.entry_price:,.2f} on {state.position.entry_time}")
        click.echo(f"  units:     {state.position.units:.6f}")
        click.echo(f"  stop:      ${state.position.stop_level:,.2f}" if state.position.stop_level else "  stop:      n/a")
    click.echo(f"equity:      ${state.equity.current:,.2f}  (initial: ${state.equity.initial_capital:,.2f})")
    click.echo(f"high water:  ${state.equity.high_watermark:,.2f}")
    click.echo(f"drawdown:    {state.drawdown():.2%}")
    click.echo(f"signal:      {state.last_signal}")
    if state.stopped_out_cooldown:
        click.echo("** in cooldown after stop-out (signal must hit 0 before re-entry) **")

    trades = storage.read_parquet(TRADES_PATH)
    if trades is not None and not trades.empty:
        click.echo(f"\ntrade log ({len(trades)} entries, last 5):")
        click.echo(trades.tail(5).to_string(index=False))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
