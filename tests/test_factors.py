"""因子单元测试。

使用合成数据验证所有8个因子的输出格式和合理范围。
"""

import pandas as pd
import numpy as np
from alphapulse.factors import (
    n_struct,
    vol_red_green,
    abnormal_vol,
    vol_cont_shrink,
    kdj_j_low,
    weekly_ma_bull,
    macd_bull_dead,
    shrink_to_abnormal,
)
from alphapulse.factors.factor_registry import FACTOR_REGISTRY, compute_factor


def make_synthetic_data(n_days: int = 500) -> pd.DataFrame:
    """生成合成OHLCV数据，包含趋势、波动和成交量变化。"""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    # 模拟价格走势：趋势 + 随机波动
    trend = np.linspace(0, 2, n_days)  # 上涨趋势
    noise = np.random.randn(n_days) * 0.3
    close = 10 * np.exp(trend + noise)

    # 生成OHLC
    daily_range = close * 0.02 * np.abs(np.random.randn(n_days))
    high = close + daily_range
    low = close - daily_range
    open_ = close - daily_range * np.random.uniform(-1, 1, n_days)

    # 成交量：基础量 + 偶尔放量
    volume = 1000000 * np.exp(0.5 * np.abs(np.random.randn(n_days)))
    # 每50天加一个放量脉冲
    volume[::50] *= 3

    turnover = np.random.uniform(0.5, 3.0, n_days)
    amount = volume * close

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover": turnover,
    }, index=dates)


def test_n_struct():
    """测试N型结构识别因子。"""
    data = make_synthetic_data(500)
    result = n_struct.compute(data, min_leg_len=5, retrace_ratio=0.618)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.index.equals(data.index)
    # 返回值应为 'A','B','C','D' 或 NaN
    valid_labels = {"A", "B", "C", "D"}
    labels = result.dropna().unique()
    for label in labels:
        assert label in valid_labels, f"无效标签: {label}"


def test_vol_red_green():
    """测试红肥绿瘦因子。"""
    data = make_synthetic_data(250)
    result = vol_red_green.compute(data, N=20, ratio_threshold=1.3)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.dtype == bool
    # 前N-1天应为NaN或False（rolling window未满）

    # 测试不同阈值
    strict = vol_red_green.compute(data, N=20, ratio_threshold=3.0)
    assert strict.sum() <= result.sum() + 1  # 更高阈值应更严格（允许少量边界差异）


def test_abnormal_vol():
    """测试放量异动因子。"""
    data = make_synthetic_data(250)
    result = abnormal_vol.compute(data, M=60, P=20, K=2.0, X=3, Y=5)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.dtype == bool

    # 极端参数：K极大时应该几乎没有信号
    extreme = abnormal_vol.compute(data, M=60, P=20, K=100, X=3, Y=5)
    assert extreme.sum() <= 1


def test_vol_cont_shrink():
    """测试缩量因子。"""
    data = make_synthetic_data(250)
    result = vol_cont_shrink.compute(data, shrink_ratio=0.25, recent_period=5)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.dtype == bool


def test_kdj_j_low():
    """测试KDJ J值低位因子。"""
    data = make_synthetic_data(250)
    result = kdj_j_low.compute(data, j_threshold=13)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.dtype == bool

    # J值极低阈值时信号应很少
    extreme = kdj_j_low.compute(data, j_threshold=-999)
    assert extreme.sum() == 0


def test_weekly_ma_bull():
    """测试周线多头因子。"""
    data = make_synthetic_data(250)
    result = weekly_ma_bull.compute(data, ma_periods=[5, 10, 20])

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.dtype == bool


def test_macd_bull_dead():
    """测试MACD多头或零轴上死叉因子。"""
    data = make_synthetic_data(250)
    result = macd_bull_dead.compute(data, fast=12, slow=26, signal=9)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.dtype == bool


def test_shrink_to_abnormal():
    """测试缩量至异动量1/4因子。"""
    data = make_synthetic_data(250)
    result = shrink_to_abnormal.compute(data, ratio=0.25, M=60, K=2.0)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.dtype == bool


def test_factor_registry():
    """测试因子注册表完整性。"""
    data = make_synthetic_data(250)

    # 所有8个因子都应在注册表中
    expected = [
        "N_STRUCT", "VOL_RED_GREEN", "ABNORMAL_VOL",
        "VOL_CONT_SHRINK", "KDJ_J_LOW", "WEEKLY_MA_BULL",
        "MACD_BULL_DEAD", "SHRINK_TO_ABNORMAL",
    ]
    for name in expected:
        assert name in FACTOR_REGISTRY, f"因子 {name} 缺失"
        entry = FACTOR_REGISTRY[name]
        assert "module" in entry
        assert "default_params" in entry
        assert callable(entry["module"].compute)

    # 通过名称调用
    result = compute_factor("KDJ_J_LOW", data)
    assert isinstance(result, pd.Series)

    # 覆盖参数
    custom = compute_factor("KDJ_J_LOW", data, j_threshold=20)
    assert custom.sum() >= 0

    # 无效因子名
    try:
        compute_factor("INVALID", data)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_all_factors_no_error():
    """所有因子在合成数据上运行不报错。"""
    data = make_synthetic_data(500)

    # 这些因子返回非bool类型（实验性因子返回连续Z-Score值，
    # 指标类因子返回连续数值，N_STRUCT返回分类标签）
    NON_BOOL_FACTORS = {"N_STRUCT", "CHIP_CONCENTRATION", "KEY_K_ABC"}.union(
        name for name, entry in FACTOR_REGISTRY.items()
        if entry.get("type") in ("experimental", "indicator", "risk")
    )

    for name, entry in FACTOR_REGISTRY.items():
        # 跳过没有 compute 方法的模块（如部分两阶段模型）
        if not callable(getattr(entry["module"], "compute", None)):
            continue
        result = entry["module"].compute(data, **entry["default_params"])
        # 跳过返回 DataFrame 的因子（如 WAVE_IDENTIFIER, FLY_AWAY）
        if isinstance(result, pd.DataFrame):
            continue
        # 跳过返回标量值的因子（如 DYNAMIC_STOP_LOSS）
        if not isinstance(result, pd.Series):
            continue
        assert len(result) == len(data), f"{name}: 长度不匹配"
        # 大部分因子返回布尔型；实验性因子和N_STRUCT返回连续值
        if name not in NON_BOOL_FACTORS:
            assert result.dtype == bool, f"{name}: 非bool类型: {result.dtype}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
