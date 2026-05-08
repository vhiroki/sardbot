"""Download and cache OHLCV data via ccxt.

OHLCV = Open, High, Low, Close, Volume — the standard candlestick representation.
One row per bar (e.g. one row per day for "1d" timeframe).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

log = logging.getLogger(__name__)

_TIMEFRAME_TO_DELTA = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}


class CCXTLoader:
    def __init__(self, exchange_id: str = "binance"):
        exchange_cls = getattr(ccxt, exchange_id)
        self.exchange = exchange_cls({"enableRateLimit": True})
        self.exchange_id = exchange_id

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime | None = None,
        cache_dir: Path | str = "data/raw",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        cache_path = Path(cache_dir) / self._cache_filename(symbol, timeframe)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        cached = self._load_cache(cache_path) if use_cache and cache_path.exists() else None
        if cached is not None and not cached.empty:
            last_cached = cached.index[-1].to_pydatetime()
            if until is not None and last_cached >= self._aware(until):
                return self._slice(cached, since, until)
            fetch_since = last_cached + _TIMEFRAME_TO_DELTA[timeframe]
        else:
            fetch_since = self._aware(since)

        new_rows = self._fetch_paginated(symbol, timeframe, fetch_since, until)
        if cached is not None and not new_rows.empty:
            df = pd.concat([cached, new_rows])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        elif cached is not None:
            df = cached
        else:
            df = new_rows

        if not df.empty:
            df.to_parquet(cache_path)
            log.info("Cached %d rows to %s", len(df), cache_path)

        return self._slice(df, since, until)

    def _fetch_paginated(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime | None,
    ) -> pd.DataFrame:
        delta = _TIMEFRAME_TO_DELTA[timeframe]
        rows: list[list[float]] = []
        cursor = int(self._aware(since).timestamp() * 1000)
        until_ms = int(self._aware(until).timestamp() * 1000) if until else None
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        end_ms = until_ms or now_ms
        page = 0

        while cursor < end_ms:
            chunk = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
            if not chunk:
                break
            rows.extend(chunk)
            last_ts = chunk[-1][0]
            cursor = last_ts + int(delta.total_seconds() * 1000)
            page += 1
            time.sleep(self.exchange.rateLimit / 1000)
            if len(chunk) < 1000:
                break

        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        log.info("Fetched %d rows across %d pages", len(df), page)
        return df

    @staticmethod
    def _cache_filename(symbol: str, timeframe: str) -> str:
        return f"{symbol.replace('/', '')}_{timeframe}.parquet"

    @staticmethod
    def _load_cache(path: Path) -> pd.DataFrame:
        df = pd.read_parquet(path)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    @staticmethod
    def _aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def _slice(df: pd.DataFrame, since: datetime, until: datetime | None) -> pd.DataFrame:
        if df.empty:
            return df
        since_aware = CCXTLoader._aware(since)
        if until is None:
            return df.loc[df.index >= since_aware]
        until_aware = CCXTLoader._aware(until)
        return df.loc[(df.index >= since_aware) & (df.index <= until_aware)]


def check_gaps(df: pd.DataFrame, timeframe: str) -> int:
    """Return the number of bars where the gap to the previous bar is not exactly one period."""
    if df.empty or len(df) < 2:
        return 0
    expected = _TIMEFRAME_TO_DELTA[timeframe]
    gaps = df.index.to_series().diff().dropna()
    return int((gaps != expected).sum())
