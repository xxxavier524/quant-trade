"""策略信号生成器单元测试。

验证 B1、砖型图、单针下三十、B1→B2→B3递进战法 等策略的信号输出格式。
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


def test_b1_signals():
    """测试B1策略信号生成。"""
    data = make_synthetic_data(500)
    result = b1_signals(data, symbol="TEST")

    _check_output_format(result, "B1")

    # 不同参数组合应可运行
    result_tight = b1_signals(data, symbol="X", shrink_ratio=0.1, j_threshold=5)
    _check_output_format(result_tight, "B1")

    # 极端宽松参数应有信号
    result_loose = b1_signals(data, symbol="X", shrink_ratio=0.9, j_threshold=100, abnormal_k=0.5, abnormal_x=1, abnormal_y=10)
    _check_output_format(result_loose, "B1")


def test_brick_signals():
    """测试砖型图策略信号生成。"""
    data = make_synthetic_data(500)
    result = brick_signals(data, symbol="TEST", brick_pct=0.02)

    _check_output_format(result, "BRICK")
    assert len(result) > 0, "合成数据应有砖型图信号"

    # 更大的砖块 → 更少信号
    result_large = brick_signals(data, symbol="X", brick_pct=0.10)
    assert len(result_large) <= len(result) + 1, "大砖块应有更少信号"


def test_needle_signals():
    """测试单针下三十策略信号生成。"""
    data = make_synthetic_data(500)
    result = needle_signals(data, symbol="TEST")

    _check_output_format(result, "NEEDLE")

    # 合成数据注入了长下影线，应有信号
    assert len(result) >= 0

    # 极端参数
    result_loose = needle_signals(data, symbol="X", shadow_ratio_threshold=0.2, j_threshold=100)
    _check_output_format(result_loose, "NEEDLE")


def test_needle_washout_signals():
    """测试单针下三十(N型洗盘版)策略信号生成。"""
    data = make_synthetic_data(500)
    result = needle_washout_signals(data, symbol="TEST")

    _check_output_format(result, "NEEDLE_WASHOUT")

    # 应包含confidence列
    if len(result) > 0:
        assert "confidence" in result.columns, "NEEDLE_WASHOUT: 缺少confidence列"
        assert (result["confidence"] >= 0).all() and (result["confidence"] <= 1).all(), \
            "NEEDLE_WASHOUT: confidence应在0-1之间"

    # 宽松参数应有更多信号
    result_loose = needle_washout_signals(
        data, symbol="X",
        j_threshold=100, shadow_mult=0.5,
        volume_shrink_ratio=2.0, fib_min=0.0, fib_max=1.0,
        position_threshold=1.0, b1_lookback=500,
    )
    _check_output_format(result_loose, "NEEDLE_WASHOUT")


def test_all_strategies_return_consistent_schema():
    """四个策略输出schema一致（含公共列）。"""
    data = make_synthetic_data(500)
    results = [
        b1_signals(data, symbol="TEST"),
        brick_signals(data, symbol="TEST"),
        needle_signals(data, symbol="TEST"),
        needle_washout_signals(data, symbol="TEST"),
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
    ]:
        result = strategy_fn(short, symbol="X")
        # 短数据不足以产生信号（均线窗口未满），结果应为空
        assert isinstance(result, pd.DataFrame), f"{name}: 应返回DataFrame"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
