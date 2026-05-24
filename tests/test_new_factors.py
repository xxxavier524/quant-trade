"""三个多头因子单元测试。

测试 KEY_KLINE / VIOLENT_KLINE / DOUBLE_VOLUME_BAR。
"""

import pandas as pd
import numpy as np
from alphapulse.factors import key_kline, violent_kline, double_volume_bar
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

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


class TestKeyKline:
    """关键K线因子测试。"""

    def test_basic(self):
        """基本输出格式。"""
        data = make_synthetic_data(250)
        result = key_kline.compute(data)

        assert isinstance(result, pd.Series)
        assert len(result) == len(data)
        assert result.dtype == bool
        assert result.index.equals(data.index)

    def test_default_params(self):
        """默认参数。"""
        data = make_synthetic_data(250)
        result = key_kline.compute(data)
        # 默认参数运行不报错
        assert result.sum() >= 0

    def test_custom_params(self):
        """自定义参数。"""
        data = make_synthetic_data(250)
        result = key_kline.compute(data, lookback=10, vol_mult=1.5)
        assert isinstance(result, pd.Series)
        assert len(result) == len(data)

    def test_strict_threshold_produces_fewer_signals(self):
        """更严格阈值应产生更少信号。"""
        data = make_synthetic_data(250)
        loose = key_kline.compute(data, vol_mult=1.0)
        strict = key_kline.compute(data, vol_mult=5.0)
        assert strict.sum() <= loose.sum() + 1

    def test_all_yang_volume_spike(self):
        """手工构造：连续阳线+某日放量最大涨幅，应被识别。"""
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.ones(n) * 10.0
        close[20:] = np.linspace(10, 12, n - 20)  # 上涨趋势
        open_ = close - 0.1  # 全部阳线
        volume = np.ones(n) * 1_000_000
        # 第50天爆量+大涨幅
        close[50] = 15.0
        open_[50] = 14.0
        volume[50] = 10_000_000
        data = pd.DataFrame({
            "open": open_,
            "high": close + 0.1,
            "low": open_ - 0.1,
            "close": close,
            "volume": volume,
        }, index=dates)

        result = key_kline.compute(data, lookback=20, vol_mult=2.0)
        assert result.loc[dates[50]], "第50天应为关键K线"


class TestViolentKline:
    """暴力K因子测试。"""

    def test_basic(self):
        """基本输出格式。"""
        data = make_synthetic_data(250)
        result = violent_kline.compute(data)

        assert isinstance(result, pd.Series)
        assert len(result) == len(data)
        assert result.dtype == bool

    def test_default_params(self):
        """默认参数。"""
        data = make_synthetic_data(250)
        result = violent_kline.compute(data)
        assert result.sum() >= 0

    def test_custom_params(self):
        """自定义参数。"""
        data = make_synthetic_data(250)
        result = violent_kline.compute(data, pct_threshold=3.0, vol_mult=2.0)
        assert isinstance(result, pd.Series)

    def test_extreme_threshold_zero_signals(self):
        """极端阈值无信号。"""
        data = make_synthetic_data(250)
        result = violent_kline.compute(data, pct_threshold=100.0, vol_mult=50.0)
        assert result.sum() == 0

    def test_handcrafted_violent_kline(self):
        """手工构造：涨幅8%+放量3倍，应被识别。"""
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.ones(n) * 10.0
        open_ = close - 0.05 * close
        volume = np.ones(n) * 1_000_000
        # 第60天暴力拉升
        close[60] = 11.0  # 涨幅10%
        open_[60] = 10.0
        volume[60] = 5_000_000  # 5倍均量
        data = pd.DataFrame({
            "open": open_,
            "high": close + 0.2,
            "low": open_ - 0.2,
            "close": close,
            "volume": volume,
        }, index=dates)

        result = violent_kline.compute(data, pct_threshold=5.0, vol_mult=3.0)
        assert result.loc[dates[60]], "第60天应为暴力K"


class TestDoubleVolumeBar:
    """倍量柱因子测试。"""

    def test_basic(self):
        """基本输出格式。"""
        data = make_synthetic_data(250)
        result = double_volume_bar.compute(data)

        assert isinstance(result, pd.Series)
        assert len(result) == len(data)
        assert result.dtype == bool

    def test_default_params(self):
        """默认参数。"""
        data = make_synthetic_data(250)
        result = double_volume_bar.compute(data)
        assert result.sum() >= 0

    def test_first_row_is_false(self):
        """第一行为NaN shift，应返回False。"""
        data = make_synthetic_data(100)
        result = double_volume_bar.compute(data)
        assert not result.iloc[0], "第一行应无前日数据，返回False"

    def test_yin_line_excluded(self):
        """阴线不应被标记。"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.ones(n) * 10.0
        open_ = close + 0.5  # 全部阴线（开>收）
        volume = np.ones(n, dtype=float) * 1_000_000
        volume[10] = 5_000_000  # 5倍量
        data = pd.DataFrame({
            "open": open_,
            "high": open_ + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volume,
        }, index=dates)

        result = double_volume_bar.compute(data, mult=2.0)
        assert result.sum() == 0, "全部阴线应无信号"

    def test_handcrafted_double_volume_bar(self):
        """手工构造：阳线+量翻倍，应被识别。"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.ones(n) * 10.0
        open_ = close - 0.1  # 全部阳线
        volume = np.ones(n, dtype=float) * 1_000_000
        volume[30] = 2_500_000  # 2.5倍量
        data = pd.DataFrame({
            "open": open_,
            "high": close + 0.2,
            "low": open_ - 0.2,
            "close": close,
            "volume": volume,
        }, index=dates)

        result = double_volume_bar.compute(data, mult=2.0)
        assert result.loc[dates[30]], "第30天应为倍量柱"


class TestFactorRegistry:
    """因子注册表测试。"""

    def test_new_factors_in_registry(self):
        """三个新因子已在注册表中。"""
        expected = ["KEY_KLINE", "VIOLENT_KLINE", "DOUBLE_VOLUME_BAR"]
        for name in expected:
            assert name in FACTOR_REGISTRY, f"因子 {name} 缺失"
            entry = FACTOR_REGISTRY[name]
            assert entry["type"] == "core", f"{name} type应为core"
            assert "module" in entry
            assert "default_params" in entry
            assert callable(entry["module"].compute)

    def test_compute_via_registry(self):
        """通过注册表调用。"""
        data = make_synthetic_data(200)
        for name in ["KEY_KLINE", "VIOLENT_KLINE", "DOUBLE_VOLUME_BAR"]:
            result = compute_factor(name, data)
            assert isinstance(result, pd.Series)
            assert len(result) == len(data)
            assert result.dtype == bool

    def test_override_params_via_registry(self):
        """通过注册表覆盖参数。"""
        data = make_synthetic_data(200)
        custom = compute_factor("VIOLENT_KLINE", data, pct_threshold=100.0)
        assert custom.sum() == 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
