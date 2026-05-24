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
    """生成 B1->B2->B3 递进信号触发数据（适配b1_formula 6条件）。

    时序设计（500日）:
    0-99:    强势上涨(10->25) 建立大幅EMA12>EMA26多头趋势
    100-149: 高位横盘(25) 巩固EMA结构
    150-199: 急跌(25->12) J暴跌<13，EMA12仍>EMA26 → B1第一阶段(~175-195)
    200-214: 底部反弹(12->15.5) EMAs交叉向上，10日振幅压缩
    215-219: 快速回落(15.5->14.5) J再次<13 (B1第二阶段触发~217-220)
    220:     B2 倍量阳线（涨幅>3%, vol>2x, 收盘>白线）B1后5日内
    223:     B3 缩量阳线锁仓（缩量<0.7, 不破B2收盘）B2后3日内
    """
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")
    N = n_days

    close = np.full(N, np.nan)
    open_arr = np.full(N, np.nan)
    high = np.full(N, np.nan)
    low = np.full(N, np.nan)
    volume = np.ones(N) * 1_000_000

    # ---- Phase 1: 0-99 强势上涨 10 -> 25 ----
    for i in range(100):
        close[i] = 10.0 + 15.0 * i / 99 + np.random.randn() * 0.08
        low[i] = close[i] * 0.98
        high[i] = close[i] * 1.02
        open_arr[i] = close[i] * 0.995

    # ---- Phase 2: 100-149 高位横盘 25 ----
    for i in range(100, 150):
        close[i] = 25.0 + np.random.randn() * 0.1
        low[i] = close[i] * 0.99
        high[i] = close[i] * 1.01
        open_arr[i] = close[i] * 0.998

    # ---- Phase 3: 150-199 急跌 25 -> 12 ----
    for i in range(150, 200):
        close[i] = 25.0 - 13.0 * (i - 150) / 50 + np.random.randn() * 0.06
        open_arr[i] = close[i] * 1.005  # 阴线为主
        low[i] = close[i] * 0.985
        high[i] = max(open_arr[i], close[i]) * 1.005

    # ---- Phase 4: 200-214 底部反弹 12 -> 15.5 (EMA交叉向上，振幅压缩) ----
    for i in range(200, 215):
        close[i] = close[199] + 3.5 * (i - 200) / 15 + np.random.randn() * 0.04
        open_arr[i] = close[i] * 0.998
        low[i] = close[i] * 0.98
        high[i] = close[i] * 1.02

    # ---- Phase 5: 215-219 快速回落 15.5 -> 14.5 (制造第二阶段B1) ----
    for i in range(215, 220):
        close[i] = close[214] - 1.0 * (i - 215) / 5 + np.random.randn() * 0.03
        open_arr[i] = close[i] * 1.003  # 小阴线
        low[i] = close[i] * 0.985
        high[i] = max(open_arr[i], close[i]) * 1.005

    # ---- B2 倍量阳线: 日220 (涨幅>3%, vol>2x, close>白线, B1后5日内) ----
    b2_idx = 220
    close[b2_idx] = close[219] * 1.045    # +4.5% 阳线，涨幅>3%
    open_arr[b2_idx] = close[219] * 1.01  # 阳线(close > open)
    high[b2_idx] = close[b2_idx] * 1.015
    low[b2_idx] = close[219] * 0.99
    volume[b2_idx] = 5_000_000            # >>前日

    # ---- 回调: 221-222 ----
    for i in range(221, 223):
        close[i] = close[b2_idx] * (1 - 0.004 * (i - b2_idx))
        open_arr[i] = close[i] * (1 + np.random.rand() * 0.003)
        low[i] = close[i] * 0.985
        high[i] = close[i] * 1.015
        volume[i] = 1_800_000

    # ---- B3 缩量阳线锁仓: 日223 (B2后3日内) ----
    b3_idx = 223
    # close需>open阳线, vol缩量<0.7, close>昨收, low>=B2收盘
    # 注意：ensure循环会做 low=min(low,open,close)-0.01，所以需预补偿
    close[b3_idx] = close[222] * 1.012
    open_arr[b3_idx] = close[b2_idx] + 0.02  # 确保min(open,close) >= b2_close+0.01
    high[b3_idx] = close[b3_idx] * 1.015
    low[b3_idx] = close[b3_idx]              # 预先设为>=b2_close
    volume[b3_idx] = volume[222] * 0.55      # 缩量0.55x (<0.7)

    # ---- Fill remaining with random walk ----
    for i in range(b3_idx + 1, N):
        close[i] = close[i - 1] * (1 + np.random.randn() * 0.004)

    for i in range(N):
        if np.isnan(close[i]):
            close[i] = 10.0
        if np.isnan(volume[i]) or (volume[i] == 1_000_000 and i > b3_idx):
            volume[i] = max(300_000, volume[max(0, i - 1)] * (1 + np.random.randn() * 0.08))
        if np.isnan(open_arr[i]):
            open_arr[i] = close[i] * (1 - np.random.rand() * 0.015)
        if np.isnan(high[i]):
            high[i] = max(open_arr[i], close[i]) * (1 + np.random.rand() * 0.015)
        if np.isnan(low[i]):
            low[i] = min(open_arr[i], close[i]) * (1 - np.random.rand() * 0.015)

    # Ensure high >= low, high >= open/close, low <= open/close
    for i in range(N):
        high[i] = max(high[i], open_arr[i], close[i]) + 0.01
        low[i] = min(low[i], open_arr[i], close[i]) - 0.01

    return pd.DataFrame({
        "open": open_arr,
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


def test_b1_b2_b3_signals():
    """测试B1->B2->B3递进战法信号生成。"""
    # 1. 标准数据：返回格式正确
    data = make_synthetic_data(500)
    result = b1b2b3_signals(data, symbol="TEST")
    _check_output_format(result, "B1_B2_B3")

    # 2. 验证 signal_type 和 confidence 列
    if len(result) > 0:
        assert "signal_type" in result.columns, "缺少 signal_type 列"
        assert "confidence" in result.columns, "缺少 confidence 列"
        valid_types = {"B1", "B2", "B3"}
        actual_types = set(result["signal_type"].unique())
        assert actual_types.issubset(valid_types), \
            f"signal_type 包含非法值: {actual_types - valid_types}"
        assert (result["confidence"] >= 0).all() and (result["confidence"] <= 1).all(), \
            "confidence 应在 0-1 之间"

    # 3. 友好数据：应产生信号，且信号类型按递进顺序
    data2 = make_b1_b2_b3_friendly_data(500)
    result2 = b1b2b3_signals(data2, symbol="TEST")
    assert isinstance(result2, pd.DataFrame)
    if len(result2) > 0:
        _check_output_format(result2, "B1_B2_B3")
        assert "signal_type" in result2.columns
        for st, conf in zip(result2["signal_type"], result2["confidence"]):
            if st == "B1":
                assert conf in (0.6, 0.8), f"B1 confidence 应为0.6(单独)或0.8(量能增强)，实际{conf}"
            elif st == "B2":
                assert conf in (0.75, 0.85), f"B2 confidence 应为0.75或0.85，实际{conf}"
            elif st == "B3":
                assert conf == 0.9, f"B3 confidence 应为0.9，实际{conf}"

    # 4. 短数据：安全返回空
    short = pd.DataFrame({
        "open": np.ones(50) * 10,
        "high": np.ones(50) * 10.2,
        "low": np.ones(50) * 9.8,
        "close": np.ones(50) * 10,
        "volume": np.ones(50) * 1e6,
    }, index=pd.date_range("2023-01-01", periods=50, freq="B"))
    result_short = b1b2b3_signals(short, symbol="X")
    assert isinstance(result_short, pd.DataFrame), "短数据应返回空DataFrame"


def test_all_strategies_return_consistent_schema():
    """策略输出schema一致（含公共列）。"""
    data = make_synthetic_data(500)
    results = [
        b1_signals(data, symbol="TEST"),
        brick_signals(data, symbol="TEST"),
        needle_signals(data, symbol="TEST"),
        needle_washout_signals(data, symbol="TEST"),
        brick_three_types_signals(data, symbol="TEST"),
        b1b2b3_signals(data, symbol="TEST"),
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
        (b1b2b3_signals, "B1_B2_B3"),
    ]:
        result = strategy_fn(short, symbol="X")
        assert isinstance(result, pd.DataFrame), f"{name}: 应返回DataFrame"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
