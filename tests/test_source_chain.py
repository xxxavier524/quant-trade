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


def test_std_drops_rows_without_close():
    raw = pd.DataFrame({"date": ["2026-07-16", "2026-07-17"],
                        "close": [None, 1.5], "open": [1, 1],
                        "high": [1, 1], "low": [1, 1], "volume": [1, 1]})
    out = _std(raw)
    assert len(out) == 1 and out["date"].iloc[0] == "2026-07-17"
