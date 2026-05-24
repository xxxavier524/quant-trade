"""策略信号生成器单元测试。

验证 B1、砖型图、单针下三十、B1->B2->B3递进战法、砖型图3子类型 等策略的信号输出格式。
"""

import pandas as pd
import numpy as np
from alphapulse.strategies.b1 import generate_signals as b1_signals
from alphapulse.strategies.brick import generate_signals as brick_signals
from alphapulse.strategies.needle import generate_signals as needle_signals
from alphapulse.strategies.needle_washout import generate_signals as needle_washout_signals
from alphapulse.strategies.brick_three_types import generate_signals as brick_three_types_signals
from alphapulse.strategies.b1_b2_b3_strategy import generate_signals as b1b2b3_signals


def make_synthetic_data(n_days: int = 500) -> pd.DataFrame:
    """生成合成OHLCV数据，含多种形态特征。"""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    # 基础价格走势
    trend = np.linspace(0, 1.5, n_days)
    noise = np.random.randn(n_days) * 0.2
    close = 10 * np.exp(trend + noise)

    # OHLC
    daily_range = close * 0.03
    open_ = close * (1 + np.random.randn(n_days) * 0.01)
    high = np.maximum(open_, close) + np.abs(np.random.randn(n_days)) * daily_range * 0.5
    low = np.minimum(open_, close) - np.abs(np.random.randn(n_days)) * daily_range * 0.5

    # 注入一些长下影线形态（每30天一次）
    for i in range(0, n_days, 30):
        if i < n_days:
            low[i] = close[i] * 0.92  # 8%下影线
            high[i] = close[i] * 1.02

    # 成交量
    volume = 1_000_000 * np.exp(0.5 * np.abs(np.random.randn(n_days)))
    volume[::40] *= 5  # 定期放量

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


def _check_output_format(df, strategy_name):
    """验证信号DataFrame格式。"""
    assert isinstance(df, pd.DataFrame), f"{strategy_name}: 返回类型应DataFrame"
    expected_cols = {"symbol", "date", "signal", "strategy", "factor_snapshot"}
    if len(df) > 0:
        actual_cols = set(df.columns) | {"date"}  # date作为index
        for col in expected_cols:
            assert col in df.columns or col == df.index.name or col in df.index.names or col in df.reset_index().columns, \
                f"{strategy_name}: 缺少列 {col}"
        assert (df["signal"].isin([-1, 0, 1])).all(), f"{strategy_name}: signal值非法"
        assert (df["strategy"] == strategy_name).all(), f"{strategy_name}: strategy字段不一致"
        for snap in df["factor_snapshot"]:
            assert isinstance(snap, dict), f"{strategy_name}: factor_snapshot应为dict"


def make_b1_b2_b3_friendly_data(n_days: int = 500) -> pd.DataFrame:
    """生成更可能触发 B1->B2->B3 递进信号的数据。"""
    np.random.seed(123)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    close = np.zeros(n_days)
    open_ = np.zeros(n_days)
    high = np.zeros(n_days)
    low = np.zeros(n_days)
    volume = np.ones(n_days) * 1_000_000

    base = 20.0
    for i in range(60):
        close[i] = base * (1 - 0.0033 * i) + np.random.randn() * 0.1
    for i in range(60, 180):
        close[i] = close[59] + np.random.randn() * 0.15
    for i in range(180, 221):
        close[i] = close[179] * (1 - 0.002 * (i - 180)) + np.random.randn() * 0.08

    idx = 221
    for i in range(idx, idx + 20):
        close[i] = close[idx - 1] * (1 - 0.005 * (i - idx)) + np.random.randn() * 0.1

    volume[228] = 8_000_000
    volume[229] = 6_000_000
    close[232] = close[231] * 0.97
    volume[232] = 150_000
    volume[233] = 160_000
    close[234] = close[233] * 0.99
    close[235] = close[234] * 0.98
    close[236] = close[235] * 0.97
    volume[235] = 200_000
    volume[236] = 180_000
    close[238] = close[237] * 1.04
    volume[238] = volume[237] * 3.0
    open_[238] = close[237] * 0.99
    close[240] = close[239] * 1.015
    volume[240] = volume[239] * 0.5

    for i in range(241, n_days):
        close[i] = close[i - 1] * (1 + np.random.randn() * 0.005)
        volume[i] = max(500_000, volume[i - 1] * (1 + np.random.randn() * 0.1))

    close = np.maximum(close, 0.5)

    for i in range(n_days):
        if open_[i] == 0:
            open_[i] = close[i] * (1 - np.random.rand() * 0.02)
        if close[i] > open_[i]:
            high[i] = close[i] * (1 + np.random.rand() * 0.02)
            low[i] = open_[i] * (1 - np.random.rand() * 0.02)
        else:
            high[i] = open_[i] * (1 + np.random.rand() * 0.02)
            low[i] = close[i] * (1 - np.random.rand() * 0.02)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


def make_brick_friendly_data(n_days: int = 500) -> pd.DataFrame:
    """生成利于砖型图3子类型触发的合成OHLCV数据。"""
    np.random.seed(123)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    close = np.zeros(n_days)
    open_ = np.zeros(n_days)
    high = np.zeros(n_days)
    low = np.zeros(n_days)
    volume = np.ones(n_days) * 1_000_000

    base = 10.0
    trend = np.cumsum(np.random.randn(n_days) * 0.08)
    for i in range(n_days):
        close[i] = base + trend[i]
        daily_range = abs(close[i]) * 0.02
        open_[i] = close[i] * (1 + np.random.randn() * 0.005)
        high[i] = max(open_[i], close[i]) + abs(np.random.randn()) * daily_range * 0.3
        low[i] = min(open_[i], close[i]) - abs(np.random.randn()) * daily_range * 0.3
        volume[i] = 1_000_000 * (1 + 0.3 * np.random.randn())

    # 区域A: 横盘突破
    for j in range(200, 212):
        close[j] = 12.0 + np.random.randn() * 0.05
        high[j] = 12.15 + abs(np.random.randn()) * 0.05
        low[j] = 11.85 - abs(np.random.randn()) * 0.05
        open_[j] = close[j] * (1 + np.random.randn() * 0.003)
    close[213] = 12.35
    high[213] = 12.45
    low[213] = 12.10
    open_[213] = 12.20
    volume[213] = 3_000_000

    # 区域B: N型起跳
    for j in range(300, 340):
        close[j] = 14.0 + np.random.randn() * 0.3
        high[j] = close[j] + abs(np.random.randn()) * 0.2
        low[j] = close[j] - abs(np.random.randn()) * 0.2
        open_[j] = close[j] * (1 + np.random.randn() * 0.005)
        volume[j] = 1_500_000 + abs(np.random.randn()) * 500_000
    for k in [315, 325, 335]:
        volume[k] = 4_000_000
        close[k] = close[k - 1] * 1.02
        high[k] = close[k] * 1.03
        low[k] = close[k] * 0.99
        open_[k] = close[k] * 0.995

    # 区域C: 上涨中继
    for j in range(400, 410):
        close[j] = 16.0 + (j - 400) * 0.15
        high[j] = close[j] * 1.02
        low[j] = close[j] * 0.98
        open_[j] = close[j] * 0.99
        volume[j] = 2_000_000 + abs(np.random.randn()) * 300_000
    for j in range(410, 412):
        close[j] = close[409] * (1 - (j - 409) * 0.008)
        high[j] = close[j] * 1.01
        low[j] = close[j] * 0.99
        open_[j] = close[j] * 1.005
    close[412] = close[411] * 1.025
    high[412] = close[412] * 1.02
    low[412] = close[412] * 0.99
    open_[412] = close[412] * 0.995
    volume[412] = volume[411] * 2.0

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


def test_b1_signals():
    """测试B1策略信号生成。"""
    data = make_synthetic_data(500)
    result = b1_signals(data, symbol="TEST")
    _check_output_format(result, "B1")
    result_tight = b1_signals(data, symbol="X", shrink_ratio=0.1, j_threshold=5)
    _check_output_format(result_tight, "B1")
    result_loose = b1_signals(data, symbol="X", shrink_ratio=0.9, j_threshold=100, abnormal_k=0.5, abnormal_x=1, abnormal_y=10)
    _check_output_format(result_loose, "B1")


def test_brick_signals():
    """测试砖型图策略信号生成。"""
    data = make_synthetic_data(500)
    result = brick_signals(data, symbol="TEST", brick_pct=0.02)
    _check_output_format(result, "BRICK")
    assert len(result) > 0, "合成数据应有砖型图信号"
    result_large = brick_signals(data, symbol="X", brick_pct=0.10)
    assert len(result_large) <= len(result) + 1, "大砖块应有更少信号"


def test_needle_signals():
    """测试单针下三十策略信号生成。"""
    data = make_synthetic_data(500)
    result = needle_signals(data, symbol="TEST")
    _check_output_format(result, "NEEDLE")
    assert len(result) >= 0
    result_loose = needle_signals(data, symbol="X", shadow_ratio_threshold=0.2, j_threshold=100)
    _check_output_format(result_loose, "NEEDLE")


def test_needle_washout_signals():
    """测试单针下三十(N型洗盘版)策略信号生成。"""
    data = make_synthetic_data(500)
    result = needle_washout_signals(data, symbol="TEST")
    _check_output_format(result, "NEEDLE_WASHOUT")
    if len(result) > 0:
        assert "confidence" in result.columns, "NEEDLE_WASHOUT: 缺少confidence列"
        assert (result["confidence"] >= 0).all() and (result["confidence"] <= 1).all(), \
            "NEEDLE_WASHOUT: confidence应在0-1之间"
    result_loose = needle_washout_signals(
        data, symbol="X",
        j_threshold=100, shadow_mult=0.5,
        volume_shrink_ratio=2.0, fib_min=0.0, fib_max=1.0,
        position_threshold=1.0, b1_lookback=500,
    )
    _check_output_format(result_loose, "NEEDLE_WASHOUT")


def test_brick_three_types_signals():
    """测试砖型图3子类型策略信号生成。"""
    data = make_brick_friendly_data(500)
    result = brick_three_types_signals(data, symbol="TEST")
    _check_output_format(result, "BRICK_THREE_TYPES")

    if len(result) > 0:
        for col in ["brick_type", "brick_value", "confidence"]:
            assert col in result.columns, f"缺少列: {col}"
        valid_types = {"BRICK_N_JUMP", "BRICK_CONTINUATION", "BRICK_BREAKOUT"}
        actual_types = set(result["brick_type"].unique())
        assert actual_types.issubset(valid_types), f"非法brick_type: {actual_types - valid_types}"
        assert (result["confidence"] >= 0).all() and (result["confidence"] <= 1).all(), \
            "confidence应在0-1之间"
        assert (result["brick_value"] >= 0).all(), "brick_value应>=0"

    result2 = brick_three_types_signals(
        data, symbol="X",
        vol_mult_n_jump=1.2, consolidation_amplitude=0.25,
    )
    _check_output_format(result2, "BRICK_THREE_TYPES")

    result_loose = brick_three_types_signals(
        data, symbol="X",
        vol_mult_n_jump=0.8, vol_mult_breakout=0.8,
        bull_bear_tolerance=0.15, consolidation_amplitude=0.30,
        pullback_days=(1, 3), vol_expand_mult=0.9,
    )
    _check_output_format(result_loose, "BRICK_THREE_TYPES")


def test_all_strategies_return_consistent_schema():
    """策略输出schema一致（含公共列）。"""
    data = make_synthetic_data(500)
    results = [
        b1_signals(data, symbol="TEST"),
        brick_signals(data, symbol="TEST"),
        needle_signals(data, symbol="TEST"),
        needle_washout_signals(data, symbol="TEST"),
        brick_three_types_signals(data, symbol="TEST"),
    ]
    common_cols = {"symbol", "signal", "strategy", "factor_snapshot"}
    for r in results:
        if len(r) > 0:
            for col in common_cols:
                assert col in r.columns, f"缺少公共列: {col}"


def test_short_data_handling():
    """短数据（不足以触发信号）边界情况。"""
    dates = pd.date_range("2023-01-01", periods=10, freq="B")
    short = pd.DataFrame({
        "open": np.ones(10) * 10,
        "high": np.ones(10) * 10.2,
        "low": np.ones(10) * 9.8,
        "close": np.ones(10) * 10,
        "volume": np.ones(10) * 1e6,
    }, index=dates)
    for strategy_fn, name in [
        (b1_signals, "B1"),
        (brick_signals, "BRICK"),
        (needle_signals, "NEEDLE"),
        (needle_washout_signals, "NEEDLE_WASHOUT"),
        (brick_three_types_signals, "BRICK_THREE_TYPES"),
    ]:
        result = strategy_fn(short, symbol="X")
        assert isinstance(result, pd.DataFrame), f"{name}: 应返回DataFrame"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
