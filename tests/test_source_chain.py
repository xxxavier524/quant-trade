"""多数据源故障切换取数层测试（用假适配器，不依赖真实网络/包）。"""

import time

import pandas as pd
import pytest

from alphapulse.utils.source_chain import fetch_daily, _std, STD_COLS


def _fake_df(dates=("2026-07-16", "2026-07-17")):
    n = len(dates)
    return pd.DataFrame({
        "date": list(dates), "open": [1.0] * n, "high": [1.1] * n,
        "low": [0.9] * n, "close": [1.05] * n, "volume": [100] * n,
        "amount": [105] * n,
    })


def _ok(name):
    return lambda sym, s, e, ctx: _fake_df()


def _raise(sym, s, e, ctx):
    raise RuntimeError("boom")


def _empty(sym, s, e, ctx):
    return pd.DataFrame()


def _slow(sym, s, e, ctx):
    time.sleep(3)
    return _fake_df()


def test_first_source_wins():
    chain = [("A", _ok("A"), True), ("B", _ok("B"), True)]
    stats = {}
    res = fetch_daily("600000", "2026-07-01", "2026-07-17", chain=chain, stats=stats)
    assert res.source == "A" and res.adjusted and len(res.df) == 2
    assert stats["src_A"] == 1 and "src_B" not in stats


def test_exception_falls_through():
    chain = [("A", _raise, True), ("B", _ok("B"), False)]
    res = fetch_daily("600000", "2026-07-01", "2026-07-17", chain=chain)
    assert res.source == "B" and res.adjusted is False


def test_empty_falls_through():
    chain = [("A", _empty, True), ("B", _ok("B"), True)]
    res = fetch_daily("600000", "2026-07-01", "2026-07-17", chain=chain)
    assert res.source == "B"


def test_timeout_falls_through():
    chain = [("slow", _slow, True), ("fast", _ok("fast"), True)]
    stats = {}
    res = fetch_daily("600000", "2026-07-01", "2026-07-17", chain=chain,
                      per_source_timeout=0.5, stats=stats)
    assert res.source == "fast"
    assert stats.get("timeout", 0) == 1


def test_all_fail_returns_empty():
    chain = [("A", _raise, True), ("B", _empty, True)]
    res = fetch_daily("600000", "2026-07-01", "2026-07-17", chain=chain)
    assert res.source == "none" and res.df.empty
    assert list(res.df.columns) == STD_COLS


def test_std_normalizes_turn_and_types():
    raw = pd.DataFrame({"date": ["2026-07-17T00:00:00"], "open": ["1"],
                        "high": ["2"], "low": ["0.5"], "close": ["1.5"],
                        "volume": ["100"], "turn": ["3.2"]})
    out = _std(raw)
    assert out["date"].iloc[0] == "2026-07-17"
    assert "turnover" in out.columns and out["turnover"].iloc[0] == 3.2
    assert out["close"].iloc[0] == 1.5


def test_timeout_does_not_block_on_hung_thread():
    """慢源(3s)在 0.3s 超时后应立刻切换，不被守护线程拖住（总耗时≈超时而非3s）。"""
    chain = [("slow", _slow, True), ("fast", _ok("fast"), True)]
    t0 = time.monotonic()
    res = fetch_daily("600000", "2026-07-01", "2026-07-17", chain=chain,
                      per_source_timeout=0.3)
    assert res.source == "fast"
    assert time.monotonic() - t0 < 1.5      # 远小于慢源的 3s


def test_circuit_breaker_skips_dead_source():
    """主源连续失败达阈值后被熔断，后续调用直接跳到次源。"""
    calls = {"A": 0}

    def a_fail(sym, s, e, ctx):
        calls["A"] += 1
        raise RuntimeError("dead")

    chain = [("A", a_fail, True), ("B", _ok("B"), True)]
    breaker, stats = {}, {}
    for _ in range(10):
        res = fetch_daily("600000", "2026-07-01", "2026-07-17",
                          chain=chain, breaker=breaker, stats=stats,
                          breaker_threshold=3)
        assert res.source == "B"
    assert calls["A"] == 3                    # 达阈值后不再调用A
    assert stats.get("tripped_A") == 1


def test_breaker_resets_on_success():
    """源恢复成功后熔断计数清零。"""
    state = {"fail": True}

    def flaky(sym, s, e, ctx):
        if state["fail"]:
            raise RuntimeError("x")
        return _fake_df()

    chain = [("A", flaky, True), ("B", _ok("B"), True)]
    breaker = {}
    fetch_daily("600000", "a", "b", chain=chain, breaker=breaker, breaker_threshold=5)
    assert breaker["A"] == 1
    state["fail"] = False
    res = fetch_daily("600000", "a", "b", chain=chain, breaker=breaker, breaker_threshold=5)
    assert res.source == "A" and breaker["A"] == 0


def test_std_drops_rows_without_close():
    raw = pd.DataFrame({"date": ["2026-07-16", "2026-07-17"],
                        "close": [None, 1.5], "open": [1, 1],
                        "high": [1, 1], "low": [1, 1], "volume": [1, 1]})
    out = _std(raw)
    assert len(out) == 1 and out["date"].iloc[0] == "2026-07-17"
