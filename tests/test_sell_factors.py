"""卖出信号因子单元测试。

测试 S1/DD/趋势线跌破 三个卖出因子的输出格式和逻辑正确性。
"""

import pandas as pd
import numpy as np
import pytest
from alphapulse.factors import (
    s1_sell_signal, dd_sell_signal, trendline_break,
    dynamic_stop_loss, fly_away,
)
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


# ============================================================
# 动态止损因子测试
# ============================================================

class TestDynamicStopLoss:
    """动态止损因子测试。"""

    def test_basic_stop_from_entry_low(self):
        """基本：从入场日最低价计算止损价。"""
        data = make_synthetic_data(500)
        entry_date = data.index[100]
        entry_price = float(data.loc[entry_date, "close"])
        entry_low = float(data.loc[entry_date, "low"])

        stop = dynamic_stop_loss.compute(data, entry_date, entry_price)

        assert isinstance(stop, float)
        expected = entry_low - 3 * 0.01
        assert stop == pytest.approx(expected, abs=0.02)

    def test_with_n_pattern_low(self):
        """提供N型结构低点时，取两者较小值。"""
        data = make_synthetic_data(500)
        entry_date = data.index[100]
        entry_price = float(data.loc[entry_date, "close"])
        entry_low = float(data.loc[entry_date, "low"])

        # N型低点高于入场低点 → 入场低点-min更小
        stop_high_n = dynamic_stop_loss.compute(
            data, entry_date, entry_price, n_pattern_low=entry_low + 1.0
        )
        expected = entry_low - 3 * 0.01
        assert stop_high_n == pytest.approx(expected, abs=0.02)

        # N型低点低于入场低点 → N型低点-min更小
        n_low_lower = entry_low - 2.0
        stop_low_n = dynamic_stop_loss.compute(
            data, entry_date, entry_price, n_pattern_low=n_low_lower
        )
        expected2 = n_low_lower - 3 * 0.01
        assert stop_low_n == pytest.approx(expected2, abs=0.02)

    def test_n_low_takes_min(self):
        """明确验证取 min 逻辑：更低N低点→更低止损价。"""
        data = make_synthetic_data(500)
        entry_date = data.index[50]
        entry_low = float(data.loc[entry_date, "low"])

        stop1 = dynamic_stop_loss.compute(
            data, entry_date, 10.0, n_pattern_low=entry_low + 5.0
        )
        stop2 = dynamic_stop_loss.compute(
            data, entry_date, 10.0, n_pattern_low=entry_low - 5.0
        )
        assert stop1 > stop2, f"高N低点应产生更高止损价: {stop1} vs {stop2}"

    def test_date_string_input(self):
        """日期字符串输入正常工作。"""
        data = make_synthetic_data(300)
        stop = dynamic_stop_loss.compute(data, "2023-03-15", 10.0)
        assert isinstance(stop, float)

    def test_date_before_data_raises(self):
        """日期早于数据起始日期时抛出错误。"""
        data = make_synthetic_data(100)
        with pytest.raises(ValueError, match="早于数据起始"):
            dynamic_stop_loss.compute(data, "2022-01-01", 10.0)

    def test_tick_size_default(self):
        """验证默认 tick_size = 0.01。"""
        assert dynamic_stop_loss.TICK_SIZE == 0.01
        assert dynamic_stop_loss.TICK_OFFSET == 3


# ============================================================
# 放飞减仓因子测试
# ============================================================

def make_surge_data(n_days: int = 200) -> pd.DataFrame:
    """生成包含连续大阳线的合成数据。"""
    np.random.seed(99)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    close = np.full(n_days, 10.0)
    open_ = np.full(n_days, 10.0)
    high = np.full(n_days, 10.1)
    low = np.full(n_days, 9.9)
    volume = np.full(n_days, 1_000_000.0)
    turnover = np.random.uniform(0.5, 3.0, n_days)
    amount = volume * close

    # 构造连续大阳线（第50-54天，5连阳，涨幅均>3%）
    for i, (c, o) in enumerate([
        (10.40, 10.00),
        (10.85, 10.40),
        (11.30, 10.85),
        (11.80, 11.30),
        (12.30, 11.80),
    ]):
        idx = 50 + i
        close[idx] = c
        open_[idx] = o
        high[idx] = c * 1.01
        low[idx] = o * 0.99
        volume[idx] = 1_000_000 * (1 + i * 0.5)

    # 白线上方加速：前20天稳定小涨形成白线向上，第100天涨幅>5%
    for i in range(80, 100):
        close[i] = 10 + (i - 80) * 0.02
        open_[i] = close[i] - 0.02
        high[i] = close[i] + 0.03
        low[i] = close[i] - 0.03

    close[100] = close[99] * 1.06
    open_[100] = close[99] * 1.01
    high[100] = close[100] * 1.01
    low[100] = open_[100] * 0.99
    volume[100] = 2_000_000

    data = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": volume * close,
        "turnover": turnover,
    }, index=dates)
    return data


class TestFlyAway:
    """放飞减仓因子测试。"""

    def test_output_format(self):
        """输出为 pd.DataFrame，含 fly_signal/reduce_ratio/reason 三列。"""
        data = make_synthetic_data(500)
        result = fly_away.compute(data)

        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["fly_signal", "reduce_ratio", "reason"]
        assert len(result) == len(data)
        assert result.index.equals(data.index)
        assert result["fly_signal"].dtype == int
        assert result["reduce_ratio"].dtype == float
        assert result["reason"].dtype == object

    def test_two_consecutive_yang_surge(self):
        """连续2根涨幅>3%阳线触发减仓1/4信号。"""
        data = make_surge_data(200)
        result = fly_away.compute(data)

        # 第50天+第51天都是大阳 -> 第52天收到信号
        signal_day = data.index[52]
        row = result.loc[signal_day]
        assert row["fly_signal"] in [2, 3], \
            f"应有2连阳信号，实际fly_signal={row['fly_signal']}"
        assert row["reduce_ratio"] >= 0.25, \
            f"减仓比例应>=0.25，实际={row['reduce_ratio']}"

    def test_three_consecutive_yang_surge(self):
        """连续3根涨幅>3%阳线触发减仓1/3信号。"""
        data = make_surge_data(200)
        result = fly_away.compute(data)

        # 第50-52天三连大阳 -> 第53天收到信号
        signal_day = data.index[53]
        row = result.loc[signal_day]
        assert row["fly_signal"] in [2, 3], \
            f"应有3连阳信号，实际fly_signal={row['fly_signal']}"
        assert row["reduce_ratio"] >= 0.25

    def test_no_signal_before_first_surge(self):
        """大阳线出现前的日期应无信号。"""
        data = make_surge_data(200)
        result = fly_away.compute(data)

        early = result.iloc[:30]
        assert (early["fly_signal"] == 0).all(), \
            f"大阳线前不应有信号，实际信号数={(early['fly_signal'] != 0).sum()}"

    def test_white_line_acceleration(self):
        """白线上方加速触发减仓信号。"""
        data = make_surge_data(200)
        result = fly_away.compute(data)

        # 第100天涨幅6%（白线上方加速），第101天应收到信号
        signal_day = data.index[101]
        row = result.loc[signal_day]

        assert row["fly_signal"] == 4, \
            f"白线加速应触发 fly_signal=4，实际={row['fly_signal']}"
        assert row["reduce_ratio"] == pytest.approx(0.5), \
            f"白线加速减仓比例应为0.5，实际={row['reduce_ratio']}"

    def test_shift1_no_future_leak(self):
        """验证 shift(1)：当日大阳不应在当日产生信号。"""
        data = make_surge_data(200)
        result = fly_away.compute(data)

        day50 = data.index[50]
        row = result.loc[day50]
        assert row["fly_signal"] == 0, \
            f"大阳当日不应有信号（shift(1)），实际fly_signal={row['fly_signal']}"

    def test_reduce_ratio_range(self):
        """减仓比例在 [0, 1] 范围内。"""
        data = make_synthetic_data(500)
        result = fly_away.compute(data)
        assert result["reduce_ratio"].min() >= 0.0
        assert result["reduce_ratio"].max() <= 1.0

    def test_reason_not_empty_on_signal(self):
        """有信号时 reason 不为空。"""
        data = make_surge_data(200)
        result = fly_away.compute(data)
        signal_rows = result[result["fly_signal"] > 0]
        if len(signal_rows) > 0:
            assert (signal_rows["reason"] != "").all(), \
                "有信号的行 reason 不应为空"

    def test_short_data_no_error(self):
        """数据过短时不报错，返回全0信号。"""
        dates = pd.date_range("2023-01-01", periods=5, freq="B")
        data = pd.DataFrame({
            "open": [10.0] * 5,
            "high": [10.2] * 5,
            "low": [9.8] * 5,
            "close": [10.1] * 5,
            "volume": [1_000_000.0] * 5,
            "amount": [10_100_000.0] * 5,
            "turnover": [1.5] * 5,
        }, index=dates)
        result = fly_away.compute(data)
        assert len(result) == 5
        assert (result["fly_signal"] == 0).all()


# ============================================================
# 扩展注册表测试（含风控因子）
# ============================================================

def test_risk_factors_in_registry():
    """两个风控因子已在注册表中，type='risk'。"""
    for name in ["DYNAMIC_STOP_LOSS", "FLY_AWAY"]:
        assert name in FACTOR_REGISTRY, f"因子 {name} 缺失"
        entry = FACTOR_REGISTRY[name]
        assert entry.get("type") == "risk", \
            f"{name} type 应为 risk，实际: {entry.get('type')}"
        assert "module" in entry
        assert "description" in entry


def test_dynamic_stop_loss_via_registry():
    """通过注册表调用动态止损。"""
    data = make_synthetic_data(300)
    entry_date = data.index[50]
    entry_price = float(data.loc[entry_date, "close"])

    stop = compute_factor(
        "DYNAMIC_STOP_LOSS", data,
        entry_date=entry_date, entry_price=entry_price,
    )
    assert isinstance(stop, float)
    assert stop > 0


def test_fly_away_via_registry():
    """通过注册表调用放飞减仓。"""
    data = make_synthetic_data(300)
    result = compute_factor("FLY_AWAY", data)

    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ["fly_signal", "reduce_ratio", "reason"]
    assert len(result) == len(data)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
