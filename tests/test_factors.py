"""因子单元测试。

使用合成数据验证所有8个因子的输出格式和合理范围。
"""

import pandas as pd
import numpy as np
import pytest
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

    import inspect

    for name, entry in FACTOR_REGISTRY.items():
        # 按 registry 声明的 compute_func 分派（缺省 compute），忠实反映实际调用路径；
        # compute_factor 路径另有参数化测试 test_compute_factor_compute_func 覆盖
        func_name = entry.get("compute_func", "compute")
        func = getattr(entry["module"], func_name, None)
        if not callable(func):
            continue
        # default_params 过滤到该函数真实签名（丢弃仅供分派器用的键，如 knowledge_points 的 factor_name）
        sig = inspect.signature(func)
        if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            params = entry["default_params"]
        else:
            params = {k: v for k, v in entry["default_params"].items()
                      if k in sig.parameters}
        result = func(data, **params)
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


# 所有在 registry 中通过 compute_func 精确指向具体函数的因子
# （7大知识点 + 指标类 BRICK_INDICATOR / ZHIXING_LINES）
COMPUTE_FUNC_FACTORS = sorted(
    name for name, entry in FACTOR_REGISTRY.items() if "compute_func" in entry
)


@pytest.mark.parametrize("name", COMPUTE_FUNC_FACTORS)
def test_compute_factor_compute_func(name):
    """compute_factor 对所有含 compute_func 的注册因子返回正确的 Series/DataFrame。

    回归测试：这些条目的 compute_func 精确指向 compute_pull_rope(data) 这类
    只接受 data 的具体函数。compute_factor 必须按目标函数签名过滤参数，
    不能把 default_params 里仅供基础分派器使用的键（如 factor_name）透传导致
    TypeError。覆盖7大知识点因子及指标类 BRICK_INDICATOR / ZHIXING_LINES。
    """
    data = make_synthetic_data(500)
    result = compute_factor(name, data)

    assert isinstance(result, (pd.Series, pd.DataFrame)), \
        f"{name}: 返回类型异常 {type(result)}"
    assert len(result) == len(data), f"{name}: 长度不匹配"
    assert result.index.equals(data.index), f"{name}: 索引与输入不一致"


def test_compute_factor_filters_unexpected_params():
    """回归：compute_factor 传入目标函数不接受的多余参数时应静默过滤而非抛错。

    精确复现报告的既有缺陷——factor_name 本是给 knowledge_points.compute()
    基础分派器用的，透传给只接受 data 的 compute_pull_rope 会抛
    TypeError: got an unexpected keyword argument 'factor_name'。
    """
    data = make_synthetic_data(500)

    # 精确复现报告的失败调用，修复后应正常返回
    result = compute_factor("PULL_ROPE", data, factor_name="PULL_ROPE")
    assert isinstance(result, pd.Series)
    assert len(result) == len(data)

    # 任意未知键同样应被过滤（DataFrame 输出因子）
    df_result = compute_factor("DISTRIBUTION_PATTERNS", data, bogus_param=999)
    assert isinstance(df_result, pd.DataFrame)
    assert len(df_result) == len(data)

    # 过滤不能误删有效参数：ZHIXING_LINES 的 compute_indicator 接受 n1/n2
    lines = compute_factor("ZHIXING_LINES", data, n1=10, n2=40, unknown_key=1)
    assert len(lines) == len(data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
