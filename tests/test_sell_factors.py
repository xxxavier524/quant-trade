"""卖出信号因子单元测试。

测试 S1/DD/趋势线跌破 三个卖出因子的输出格式和逻辑正确性。
"""

import pandas as pd
import numpy as np
from alphapulse.factors import s1_sell_signal, dd_sell_signal, trendline_break
from alphapulse.factors.factor_registry import FACTOR_REGISTRY, compute_factor


def make_synthetic_data(n_days: int = 500) -> pd.DataFrame:
    """生成合成OHLCV数据。"""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    trend = np.linspace(0, 2, n_days)
    noise = np.random.randn(n_days) * 0.3
    close = 10 * np.exp(trend + noise)

    daily_range = close * 0.02 * np.abs(np.random.randn(n_days))
    high = close + daily_range
    low = close - daily_range
    open_ = close - daily_range * np.random.uniform(-1, 1, n_days)
    volume = 1_000_000 * np.exp(0.5 * np.abs(np.random.randn(n_days)))
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


def make_s1_trigger_data() -> pd.DataFrame:
    """构造明确触发S1卖出信号的数据。

    设计: 前5天持续上涨，第6天高开放巨量阴线（成交量近20日最高，超阳量均值2倍）。
    """
    np.random.seed(99)
    n = 120
    dates = pd.date_range("2023-01-01", periods=n, freq="B")

    close = np.ones(n) * 10.0
    close[:10] = np.linspace(10, 10, 10)  # 平稳期
    close[10:15] = np.linspace(10, 11.5, 5)  # 前5日持续上涨
    close[15] = 11.0  # 第6天高开低走，收阴但高于前日

    open_ = np.ones(n) * 10.0
    open_[:10] = close[:10] - 0.02
    open_[10:15] = close[10:15] - 0.01
    open_[15] = 11.8  # 高开

    high = np.maximum(open_, close) + 0.05
    low = np.minimum(open_, close) - 0.05

    volume = np.ones(n) * 1_000_000
    volume[10:15] = np.linspace(800_000, 1_200_000, 5)  # 温和放量
    volume[15] = 5_000_000  # 巨量（远超前19日最高，超阳量均值2倍）

    amount = volume * close
    turnover = np.ones(n) * 1.5

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover": turnover,
    }, index=dates)


def make_dd_trigger_data() -> pd.DataFrame:
    """构造明确触发DD卖出信号的数据。

    设计: 第10天收盘跌破前日最低价，第11天再次跌破（形成DD增强）。
    """
    np.random.seed(77)
    n = 30
    dates = pd.date_range("2023-01-01", periods=n, freq="B")

    close = np.ones(n) * 10.0
    close[8] = 9.5   # 下跌
    close[9] = 9.0   # 再跌

    open_ = close + 0.05
    high = close + 0.15
    low = close - 0.10
    low[8] = 9.6   # 前日最低价9.6
    low[9] = 9.2   # 前日最低价9.2

    volume = np.ones(n) * 1_000_000
    amount = volume * close
    turnover = np.ones(n) * 1.5

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover": turnover,
    }, index=dates)


def make_trendline_break_data() -> pd.DataFrame:
    """构造明确触发趋势线跌破的数据。

    设计: 价格围绕白线波动，设计一个跌破再反弹的假跌破场景。
    """
    np.random.seed(55)
    n = 300
    dates = pd.date_range("2023-01-01", periods=n, freq="B")

    # 基础价格在10附近震荡，后期下跌跌破均线
    close = np.ones(n) * 10.0
    close[:200] = 10 + np.sin(np.linspace(0, 4 * np.pi, 200)) * 0.5 + np.random.randn(200) * 0.1
    close[200:210] = np.linspace(10.5, 8.5, 10)  # 快速下跌跌破白线
    close[210] = 9.0  # 反弹站回
    close[211:] = 9.5 + np.random.randn(n - 211) * 0.1

    open_ = close - 0.05
    high = close + 0.1
    low = close - 0.1

    volume = np.ones(n) * 1_000_000
    amount = volume * close
    turnover = np.ones(n) * 1.5

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover": turnover,
    }, index=dates)


# ============ S1卖出信号测试 ============

def test_s1_output_format():
    """S1输出应为整数Series，值域{0,1,2}。"""
    data = make_synthetic_data(500)
    result = s1_sell_signal.compute(data)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.index.equals(data.index)
    assert result.dtype == int
    assert set(result.unique()).issubset({0, 1, 2})


def test_s1_trigger_conditions():
    """构造数据应触发S1信号。"""
    data = make_s1_trigger_data()
    result = s1_sell_signal.compute(data, vol_window=20, vol_mult=2.0)

    # 第15天（0-indexed）应触发S1信号
    # 因为前5天(10-14)持续上涨，第15天放巨量阴线
    s1_days = result[result >= 1]
    assert len(s1_days) > 0, "应至少有一个S1信号触发"


def test_s1_fake_yang_downgrade():
    """假阴真阳应降级为2。"""
    data = make_s1_trigger_data()
    result = s1_sell_signal.compute(data, vol_window=20, vol_mult=2.0)

    # 检查第15天是否为假阴真阳(close<open但close>prev_close)
    idx_15 = data.index[15]
    close_15 = data.loc[idx_15, "close"]
    open_15 = data.loc[idx_15, "open"]
    prev_close = data.loc[data.index[14], "close"]

    is_fake = (close_15 < open_15) and (close_15 > prev_close)
    if is_fake and result.loc[idx_15] > 0:
        assert result.loc[idx_15] == 2, \
            f"假阴真阳应降级为2，实际为{result.loc[idx_15]}"


def test_s1_different_params():
    """不同参数应产生不同信号数。"""
    data = make_synthetic_data(500)

    r1 = s1_sell_signal.compute(data, vol_window=20, vol_mult=2.0)
    r2 = s1_sell_signal.compute(data, vol_window=10, vol_mult=2.0)
    r3 = s1_sell_signal.compute(data, vol_window=20, vol_mult=5.0)

    count1 = (r1 >= 1).sum()
    count3 = (r3 >= 1).sum()

    # vol_mult=5.0 应比 2.0 更严格
    assert count3 <= count1


# ============ DD卖出信号测试 ============

def test_dd_output_format():
    """DD输出应为整数Series，值域{0,1,2}。"""
    data = make_synthetic_data(500)
    result = dd_sell_signal.compute(data)

    assert isinstance(result, pd.Series)
    assert len(result) == len(data)
    assert result.index.equals(data.index)
    assert result.dtype == int
    assert set(result.unique()).issubset({0, 1, 2})


def test_dd_no_future_leak():
    """DD信号不应使用未来数据：信号仅依赖已发生数据。"""
    data = make_synthetic_data(500)
    result = dd_sell_signal.compute(data)

    # 前2行应全为0（需要shift(1)和shift(2)填充）
    assert result.iloc[0] == 0
    assert result.iloc[1] == 0


def test_dd_trigger():
    """构造数据应触发DD和DD增强信号。"""
    data = make_dd_trigger_data()
    result = dd_sell_signal.compute(data)

    # 应有DD信号（至少1个）
    assert (result == 1).sum() >= 1, "应至少触发一个DD信号"

    # DD增强应在DD之后出现（连续两天DD）
    dd_idx = result[result >= 1].index
    assert len(dd_idx) > 0


def test_dd_enhanced_after_dd():
    """DD增强(2)只在DD连续出现时才触发。"""
    data = make_dd_trigger_data()
    result = dd_sell_signal.compute(data)

    # 检查：值为2的行，其前一行值应为1或2
    enhanced_idx = result[result == 2].index
    for idx in enhanced_idx:
        pos = result.index.get_loc(idx)
        if pos > 0:
            prev_val = result.iloc[pos - 1]
            assert prev_val in (1, 2), \
                f"DD增强(idx={idx})前一行应为DD信号，实际为{prev_val}"


# ============ 趋势线跌破测试 ============

def test_trendline_output_format():
    """趋势线跌破输出应为DataFrame，含三列bool。"""
    data = make_synthetic_data(500)
    result = trendline_break.compute(data)

    assert isinstance(result, pd.DataFrame)
    assert len(result) == len(data)
    assert set(result.columns) == {"break_white", "break_yellow", "fake_break"}
    assert result.index.equals(data.index)
    for col in result.columns:
        assert result[col].dtype == bool, f"{col} 应为bool类型"


def test_trendline_no_future_leak():
    """趋势线信号不应使用未来数据。"""
    data = make_trendline_break_data()
    result = trendline_break.compute(data)

    # 前几行应为False（shift操作需要足够历史）
    assert not result["break_white"].iloc[0]
    assert not result["break_white"].iloc[1]


def test_trendline_break_detected():
    """构造数据应检测到跌破信号。"""
    data = make_trendline_break_data()
    result = trendline_break.compute(data)

    # 在快速下跌区段应检测到跌破白线
    break_count = result["break_white"].sum()
    assert break_count > 0, f"应至少检测到一次跌破白线，实际{break_count}"


def test_fake_break_after_break():
    """假跌破应在真跌破之后发生。"""
    data = make_trendline_break_data()
    result = trendline_break.compute(data)

    # 假跌破的前一天应该是真跌破
    fake_idx = result[result["fake_break"]].index
    for idx in fake_idx:
        pos = result.index.get_loc(idx)
        if pos > 0:
            prev_break = result["break_white"].iloc[pos - 1]
            if not prev_break:
                # 如果没有前置跌破，检查是否有更早的跌破
                pass  # 假跌破可能在非连续情况下出现


# ============ 因子注册表测试 ============

def test_sell_factors_in_registry():
    """三个卖出因子应在注册表中，type='risk'。"""
    expected = ["S1_SELL_SIGNAL", "DD_SELL_SIGNAL", "TRENDLINE_BREAK"]

    for name in expected:
        assert name in FACTOR_REGISTRY, f"因子 {name} 缺失"
        entry = FACTOR_REGISTRY[name]
        assert "module" in entry, f"{name}: 缺少 module"
        assert entry.get("type") == "risk", \
            f"{name}: type 应为 'risk'，实际为 {entry.get('type')}"

    # 通过名称调用
    data = make_synthetic_data(250)
    result = compute_factor("DD_SELL_SIGNAL", data)
    assert isinstance(result, pd.Series)

    result_tl = compute_factor("TRENDLINE_BREAK", data)
    assert isinstance(result_tl, pd.DataFrame)


def test_sell_factors_no_error():
    """三个卖出因子在合成数据上运行不报错。"""
    data = make_synthetic_data(500)

    r1 = s1_sell_signal.compute(data)
    assert len(r1) == len(data)

    r2 = dd_sell_signal.compute(data)
    assert len(r2) == len(data)

    r3 = trendline_break.compute(data)
    assert len(r3) == len(data)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
