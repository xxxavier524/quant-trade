"""Multi-source data fetcher with auto-fallback and rate limiting."""
import time
import random
import threading
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
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
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
        self._lock = threading.Lock()

    @property
    def is_open(self):
        with self._lock:
            if self.failures >= self.threshold:
                if time.monotonic() < self.open_until:
                    return True
                self.failures = 0
            return False

    def record_failure(self):
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = time.monotonic() + self.pause

    def record_success(self):
        with self._lock:
            self.failures = 0

class DataFetcher:
    """Fetch stock data with priority-ordered source fallback."""

    def __init__(self, sources=None, max_workers=3):
        if sources is None:
            sources = ["akshare", "baostock", "pytdx"]
        self.sources = sources
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
                            # Use get_security_bars: category=9(daily), market, code, start(0=latest), count
                            data = api.get_security_bars(9, market, symbol, 0, 800)
                            if data is None or len(data) == 0:
                                raise RuntimeError(f"pytdx empty data for {symbol}")
                            rows = []
                            for d in data:
                                rows.append({
                                    "date": f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}",
                                    "open": d["open"],
                                    "high": d["high"],
                                    "low": d["low"],
                                    "close": d["close"],
                                    "volume": d["vol"],
                                    "amount": d.get("amount", 0),
                                    "turnover": 0.0,
                                })
                            df = pd.DataFrame(rows)
                            # Filter by date range
                            df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
                            return df
                    finally:
                        api.disconnect()
                return _fetch
            except ImportError:
                logger.warning("pytdx not installed")
                return None

        if name == "yfinance":
            try:
                from alphapulse.utils.yfinance_adapter import YFinanceAdapter
                adapter = YFinanceAdapter()
                def _fetch(symbol, start_date, end_date):
                    df = adapter.fetch_history(symbol, start_date, end_date)
                    if df is None or df.empty:
                        return None
                    return df
                return _fetch
            except ImportError:
                logger.warning("yfinance adapter not available")
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
