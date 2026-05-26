"""Multi-source data fetcher with auto-fallback and rate limiting."""
import time
import random
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable
import pandas as pd

logger = logging.getLogger(__name__)

class RateLimiter:
    """Token-bucket-like rate limiter with random jitter."""
    def __init__(self, min_interval=0.5, max_interval=1.5):
        self.min = min_interval
        self.max = max_interval
        self._last_call = 0

    def wait(self):
        elapsed = time.monotonic() - self._last_call
        target = random.uniform(self.min, self.max)
        if elapsed < target:
            time.sleep(target - elapsed)
        self._last_call = time.monotonic()

class CircuitBreaker:
    """Open after N consecutive failures, auto-recover after pause."""
    def __init__(self, fail_threshold=5, pause_sec=600):
        self.threshold = fail_threshold
        self.pause = pause_sec
        self.failures = 0
        self.open_until = 0

    @property
    def is_open(self):
        if self.failures >= self.threshold:
            if time.monotonic() < self.open_until:
                return True
            self.failures = 0
        return False

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = time.monotonic() + self.pause

    def record_success(self):
        self.failures = 0

class DataFetcher:
    """Fetch stock data with priority-ordered source fallback."""

    def __init__(self, sources=None, max_workers=3):
        self.sources = sources or ["akshare", "baostock", "pytdx"]
        self.max_workers = max_workers
        self.rate_limiter = RateLimiter()
        self.breakers = {s: CircuitBreaker() for s in self.sources}
        self._init_sources()

    def _init_sources(self):
        self._fetchers = {}
        for name in self.sources:
            fetcher = self._build_fetcher(name)
            if fetcher:
                self._fetchers[name] = fetcher

    def _build_fetcher(self, name: str) -> Optional[Callable]:
        if name == "akshare":
            try:
                import akshare as ak
                def _fetch(symbol, start_date, end_date):
                    code = symbol
                    df = ak.stock_zh_a_hist(
                        symbol=code, period="daily",
                        start_date=start_date, end_date=end_date, adjust="qfq"
                    )
                    df = df.rename(columns={
                        "日期": "date", "开盘": "open", "最高": "high",
                        "最低": "low", "收盘": "close", "成交量": "volume",
                        "成交额": "amount", "换手率": "turnover"
                    })
                    return df[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]]
                return _fetch
            except ImportError:
                logger.warning("akshare not installed")
                return None

        if name == "baostock":
            try:
                import baostock as bs
                def _fetch(symbol, start_date, end_date):
                    code = f"sh.{symbol}" if symbol.startswith(("6", "9")) else f"sz.{symbol}"
                    bs.login()
                    try:
                        rs = bs.query_history_k_data_plus(
                            code, "date,open,high,low,close,volume,amount,turn",
                            start_date=start_date, end_date=end_date,
                            frequency="d", adjustflag="2"
                        )
                        df = rs.get_data()
                        df.columns = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]
                        for col in ["open", "high", "low", "close", "volume", "amount", "turnover"]:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                        return df
                    finally:
                        bs.logout()
                return _fetch
            except ImportError:
                logger.warning("baostock not installed")
                return None

        if name == "pytdx":
            try:
                from pytdx.hq import TdxHq_API
                def _fetch(symbol, start_date, end_date):
                    market = 1 if symbol.startswith(("6", "9")) else 0
                    api = TdxHq_API()
                    try:
                        with api.connect("119.147.212.81", 7709):
                            data = api.get_k_data(symbol, start_date, end_date)
                            if data is None or len(data) == 0:
                                raise RuntimeError(f"pytdx empty data for {symbol}")
                            df = api.to_df(data)
                            df = df.rename(columns={
                                "date": "date", "open": "open", "high": "high",
                                "low": "low", "close": "close", "volume": "volume",
                                "amount": "amount"
                            })
                            df["turnover"] = 0.0
                            return df[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]]
                    finally:
                        api.disconnect()
                return _fetch
            except ImportError:
                logger.warning("pytdx not installed")
                return None

        if name == "yfinance":
            try:
                import yfinance as yf
                def _fetch(symbol, start_date, end_date):
                    ticker = yf.Ticker(symbol)
                    df = ticker.history(start=start_date, end=end_date)
                    df = df.reset_index()
                    df = df.rename(columns={
                        "Date": "date", "Open": "open", "High": "high",
                        "Low": "low", "Close": "close", "Volume": "volume"
                    })
                    df["amount"] = 0.0
                    df["turnover"] = 0.0
                    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
                    return df[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]]
                return _fetch
            except ImportError:
                logger.warning("yfinance not installed")
                return None

        return None

    def fetch_single(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Fetch one stock with fallback through source priority list."""
        for name in self.sources:
            breaker = self.breakers[name]
            if breaker.is_open:
                logger.debug(f"Circuit breaker open for {name}, skipping")
                continue
            fetcher = self._fetchers.get(name)
            if fetcher is None:
                continue
            self.rate_limiter.wait()
            try:
                df = fetcher(symbol, start_date, end_date)
                if df is not None and len(df) > 0:
                    breaker.record_success()
                    return df
            except Exception as e:
                logger.warning(f"{name} failed for {symbol}: {e}")
                breaker.record_failure()
        return None

    def fetch_batch(self, symbols: list, start_date: str, end_date: str) -> dict:
        """Fetch multiple symbols with thread pool (max_workers=3)."""
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {
                ex.submit(self.fetch_single, s, start_date, end_date): s
                for s in symbols
            }
            for f in as_completed(futures):
                sym = futures[f]
                try:
                    df = f.result(timeout=30)
                    if df is not None:
                        results[sym] = df
                except Exception as e:
                    logger.error(f"Batch fetch failed for {sym}: {e}")
        return results
