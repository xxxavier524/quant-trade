import pandas as pd
import pytest
from alphapulse.utils.data_fetcher import DataFetcher, RateLimiter, CircuitBreaker

def test_rate_limiter_waits():
    rl = RateLimiter(min_interval=0.01, max_interval=0.02)
    t0 = pd.Timestamp.now()
    rl.wait()
    rl.wait()
    elapsed = (pd.Timestamp.now() - t0).total_seconds()
    assert elapsed >= 0.01

def test_circuit_breaker_opens():
    cb = CircuitBreaker(fail_threshold=3, pause_sec=60)
    for _ in range(3):
        assert not cb.is_open
        cb.record_failure()
    assert cb.is_open

def test_circuit_breaker_recovers():
    cb = CircuitBreaker(fail_threshold=3, pause_sec=0.01)
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open
    import time
    time.sleep(0.02)
    assert not cb.is_open

def test_data_fetcher_init():
    df = DataFetcher(sources=["akshare"])
    assert "akshare" in df._fetchers

def test_data_fetcher_returns_none_for_no_sources():
    df = DataFetcher(sources=[])
    result = df.fetch_single("999999", "2024-01-01", "2024-01-05")
    assert result is None
