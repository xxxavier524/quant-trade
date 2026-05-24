"""新增形态因子单元测试。

测试筹码集中、对称结构、填坑出坑、长阴短柱、波段识别、关键K线ABC。
"""

import pandas as pd
import numpy as np
from alphapulse.factors import (
    chip_concentration,
    symmetric_structure,
    fill_pit_exit_pit,
    long_yin_short_column,
    wave_identifier,
    key_k_abc,
)
from alphapulse.factors.factor_registry import FACTOR_REGISTRY, compute_factor


def make_synthetic_data(n_days: int = 500) -> pd.DataFrame:
    """生成合成 OHLCV 数据，包含趋势、波动和成交量变化。"""
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


def make_v_pattern_data(n_days: int = 120) -> pd.DataFrame:
    """生成含 V 型走势的合成数据。"""
    np.random.seed(123)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    close = np.zeros(n_days)
    close[:30] = np.linspace(10, 15, 30) + np.random.randn(30) * 0.05
    close[30:60] = np.linspace(15, 8, 30) + np.random.randn(30) * 0.1
    close[60:90] = np.linspace(8, 14.5, 30) + np.random.randn(30) * 0.08
    close[90:] = 15 + np.random.randn(30) * 0.2

    high = close + np.abs(np.random.randn(n_days)) * 0.15
    low = close - np.abs(np.random.randn(n_days)) * 0.15
    open_ = close - np.random.uniform(-0.1, 0.1, n_days)
    volume = 1_000_000 * np.exp(0.3 * np.abs(np.random.randn(n_days)))
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


def make_pit_pattern_data(n_days: int = 200) -> pd.DataFrame:
    """生成含填坑出坑形态的合成数据。"""
    np.random.seed(456)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    close = np.zeros(n_days)
    close[:30] = 20 + np.random.randn(30) * 0.1
    close[30:50] = np.linspace(20, 15, 20) + np.random.randn(20) * 0.08
    close[50:56] = 15.2 + np.random.randn(6) * 0.03
    close[56:80] = np.linspace(15.3, 18, 24) + np.random.randn(24) * 0.08
    close[80:] = 18.5 + np.random.randn(120) * 0.2

    high = close + np.abs(np.random.randn(n_days)) * 0.12
    low = close - np.abs(np.random.randn(n_days)) * 0.12
    open_ = close - np.random.uniform(-0.08, 0.08, n_days)

    volume = np.ones(n_days) * 1_000_000
    volume[30:50] *= 1.2
    volume[50:56] *= 0.6
    volume[56] *= 4.0
    volume[57:60] *= 1.8
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


# ============================================================
# 筹码集中因子测试
# ============================================================

class TestChipConcentration:
    """筹码集中度因子测试。"""

    def test_output_format(self):
        """输出为 pd.Series，长度一致，值在 [0,1] 范围。"""
        data = make_synthetic_data(500)
        result = chip_concentration.compute(data, window=20, amplitude_max=15.0)

        assert isinstance(result, pd.Series)
        assert len(result) == len(data)
        assert result.index.equals(data.index)
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_low_amplitude_high_score(self):
        """低振幅+换手率下降应产生较高得分。"""
        np.random.seed(99)
        n = 300
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = 10 + np.cumsum(np.random.randn(n) * 0.02)
        high = close * 1.005
        low = close * 0.995
        volume = np.ones(n) * 1_000_000
        turnover = np.linspace(3.0, 0.5, n)

        data = pd.DataFrame({
            "open": close, "high": high, "low": low, "close": close,
            "volume": volume, "amount": volume * close, "turnover": turnover,
        }, index=dates)

        result = chip_concentration.compute(data, window=20, amplitude_max=15.0)
        second_half_avg = result.iloc[n // 2:].mean()
        assert second_half_avg > 0.3, \
            f"低波动+趋势下降应 >0.3，实际: {second_half_avg:.3f}"

    def test_default_params(self):
        """默认参数运行不报错。"""
        data = make_synthetic_data(250)
        result = chip_concentration.compute(data)
        assert len(result) == len(data)

    def test_tighter_amplitude_lower_score(self):
        """更严格的振幅上限产生更低或相等的平均得分。"""
        data = make_synthetic_data(250)
        r1 = chip_concentration.compute(data, window=20, amplitude_max=15.0)
        r2 = chip_concentration.compute(data, window=20, amplitude_max=10.0)
        assert r2.mean() <= r1.mean() + 0.05

    def test_no_turnover_column(self):
        """无 turnover 列时应报错。"""
        data = make_synthetic_data(250).drop(columns=["turnover"])
        try:
            chip_concentration.compute(data)
            assert False, "应抛出 KeyError"
        except KeyError:
            pass


# ============================================================
# 对称结构因子测试
# ============================================================

class TestSymmetricStructure:
    """对称结构因子测试。"""

    def test_output_format(self):
        """输出为 pd.Series bool，长度一致。"""
        data = make_v_pattern_data(120)
        result = symmetric_structure.compute(data, tolerance=0.05, min_leg_len=5)

        assert isinstance(result, pd.Series)
        assert len(result) == len(data)
        assert result.dtype == bool
        assert result.index.equals(data.index)

    def test_default_params(self):
        """默认参数运行不报错。"""
        data = make_synthetic_data(250)
        result = symmetric_structure.compute(data)
        assert isinstance(result, pd.Series)
        assert len(result) == len(data)

    def test_random_data_low_false_positive(self):
        """纯随机数据假信号率应低（<10%）。"""
        np.random.seed(777)
        n = 200
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = 10 + np.cumsum(np.random.randn(n) * 0.3)
        high = close + np.abs(np.random.randn(n)) * 0.2
        low = close - np.abs(np.random.randn(n)) * 0.2

        data = pd.DataFrame({
            "open": close, "high": high, "low": low, "close": close,
            "volume": np.ones(n) * 1_000_000,
        }, index=dates)

        result = symmetric_structure.compute(data, tolerance=0.05, min_leg_len=5)
        fpr = result.sum() / len(result)
        assert fpr < 0.10, f"随机数据假信号率过高: {fpr:.2%}"

    def test_short_data_no_error(self):
        """数据过短时应返回全 False 不报错。"""
        data = make_synthetic_data(8)
        result = symmetric_structure.compute(data, tolerance=0.05, min_leg_len=5)
        assert isinstance(result, pd.Series)
        assert len(result) == 8
        assert result.sum() == 0

    def test_tolerance_effect(self):
        """放宽 tolerance 应产生 >= 原信号数。"""
        data = make_v_pattern_data(120)
        strict = symmetric_structure.compute(data, tolerance=0.02, min_leg_len=5)
        loose = symmetric_structure.compute(data, tolerance=0.20, min_leg_len=5)
        assert loose.sum() >= strict.sum()


# ============================================================
# 填坑出坑因子测试
# ============================================================

class TestFillPitExitPit:
    """填坑出坑因子测试。"""

    def test_output_format(self):
        """输出为 pd.Series bool，长度一致。"""
        data = make_pit_pattern_data(200)
        result = fill_pit_exit_pit.compute(
            data, drop_pct=15.0, consolidation_days=3, breakout_vol_mult=1.5
        )

        assert isinstance(result, pd.Series)
        assert len(result) == len(data)
        assert result.dtype == bool
        assert result.index.equals(data.index)

    def test_default_params(self):
        """默认参数运行不报错。"""
        data = make_synthetic_data(250)
        result = fill_pit_exit_pit.compute(data)
        assert isinstance(result, pd.Series)
        assert len(result) == len(data)

    def test_extreme_vol_mult_no_signal(self):
        """极高成交量倍数阈值应几乎无信号。"""
        data = make_pit_pattern_data(200)
        result = fill_pit_exit_pit.compute(
            data, drop_pct=15.0, consolidation_days=3, breakout_vol_mult=100.0
        )
        assert result.sum() < 5, f"极高阈值应几乎无信号，实际: {result.sum()}"

    def test_extreme_drop_pct_no_signal(self):
        """极高回落阈值应无信号（达不到）。"""
        data = make_synthetic_data(250)
        result = fill_pit_exit_pit.compute(
            data, drop_pct=90.0, consolidation_days=3, breakout_vol_mult=1.5
        )
        assert result.sum() == 0, f"90%回落阈值应无信号，实际: {result.sum()}"

    def test_short_data_no_error(self):
        """短数据不报错。"""
        data = make_synthetic_data(30)
        result = fill_pit_exit_pit.compute(
            data, drop_pct=15.0, consolidation_days=3, breakout_vol_mult=1.5
        )
        assert isinstance(result, pd.Series)
        assert len(result) == 30


# ============================================================
# 长阴短柱因子测试
# ============================================================

class TestLongYinShortColumn:
    """长阴短柱因子测试。"""

    def test_output_format(self):
        """输出为 pd.Series bool，长度一致。"""
        data = make_synthetic_data(250)
        result = long_yin_short_column.compute(data)

        assert isinstance(result, pd.Series)
        assert len(result) == len(data)
        assert result.dtype == bool
        assert result.index.equals(data.index)

    def test_handcrafted_pattern(self):
        """手工构造长阴短柱形态应被识别。"""
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")

        data = pd.DataFrame({
            "open": np.full(n, 10.0),
            "high": np.full(n, 10.2),
            "low": np.full(n, 9.8),
            "close": np.full(n, 10.1),
            "volume": np.full(n, 1_000_000.0),
        }, index=dates)

        # 第50天：阴线+实体3%+缩量至前日0.6倍
        data.loc[dates[50], "open"] = 10.0
        data.loc[dates[50], "close"] = 9.7
        data.loc[dates[50], "volume"] = 600_000

        result = long_yin_short_column.compute(data)
        assert result.iloc[50], "长阴短柱形态未被识别"

    def test_yang_line_excluded(self):
        """阳线不应触发信号。"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        data = pd.DataFrame({
            "open": np.full(n, 10.0),
            "high": np.full(n, 10.5),
            "low": np.full(n, 9.8),
            "close": np.full(n, 10.3),
            "volume": np.full(n, 500_000.0),
        }, index=dates)
        result = long_yin_short_column.compute(data)
        assert result.sum() == 0, "全阳线不应有信号"

    def test_large_vol_excluded(self):
        """放量阴线不应触发信号。"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        data = pd.DataFrame({
            "open": np.full(n, 10.0),
            "high": np.full(n, 10.2),
            "low": np.full(n, 9.8),
            "close": np.full(n, 9.5),
            "volume": np.full(n, 2_000_000.0),
        }, index=dates)
        result = long_yin_short_column.compute(data)
        assert result.sum() == 0, "放量阴线不应触发"

    def test_small_body_excluded(self):
        """小实体（<1%）不应触发信号。"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        data = pd.DataFrame({
            "open": np.full(n, 10.0),
            "high": np.full(n, 10.01),
            "low": np.full(n, 9.98),
            "close": np.full(n, 9.995),
            "volume": np.full(n, 500_000.0),
        }, index=dates)
        result = long_yin_short_column.compute(data, body_min_pct=1.0)
        assert result.sum() == 0, "小实体不应触发"


# ============================================================
# 波段识别因子测试
# ============================================================

class TestWaveIdentifier:
    """波段识别因子测试。"""

    def test_output_format(self):
        """输出为 pd.DataFrame，三列 bool。"""
        data = make_synthetic_data(250)
        result = wave_identifier.compute(data)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(data)
        assert list(result.columns) == ["accumulation", "lift", "sprint"]
        for col in result.columns:
            assert result[col].dtype == bool
        assert result.index.equals(data.index)

    def test_accumulation_detected(self):
        """平稳行情应识别建仓波。"""
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        data = pd.DataFrame({
            "open": np.full(n, 10.0),
            "high": np.full(n, 10.2),
            "low": np.full(n, 9.8),
            "close": np.linspace(10.0, 10.5, n),
            "volume": np.full(n, 1_000_000.0),
        }, index=dates)
        result = wave_identifier.compute(data, accumulation_max_return=0.10, vol_mild_ratio=1.5)
        valid = result.iloc[40:]
        assert valid["accumulation"].sum() > 0, "平稳行情应识别出建仓波"

    def test_lift_detected(self):
        """放量拉升应识别拉升波。"""
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.full(n, 10.0)
        close[80:] = np.linspace(10.0, 13.0, 20)
        volume = np.full(n, 1_000_000.0)
        volume[85:] = 2_000_000.0

        data = pd.DataFrame({
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": volume,
        }, index=dates)
        result = wave_identifier.compute(data, lift_min_return=0.15, vol_expand_ratio=1.5)
        assert result["lift"].iloc[85:].sum() > 0, "放量拉升应触发信号"

    def test_sprint_detected(self):
        """巨量冲顶应识别冲刺波。"""
        n = 150
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.full(n, 10.0)
        # 最后10天急涨40%
        close[140:] = np.linspace(10.0, 14.0, 10)
        volume = np.full(n, 1_000_000.0)
        # 末段10倍量（确保 > MA20*3）
        volume[145:] = 10_000_000.0

        data = pd.DataFrame({
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": volume,
        }, index=dates)
        result = wave_identifier.compute(data, sprint_min_return=0.20, vol_huge_ratio=3.0)
        assert result["sprint"].iloc[147:].sum() > 0, "巨量冲顶应触发信号"

    def test_default_params(self):
        """默认参数运行不报错。"""
        data = make_synthetic_data(250)
        result = wave_identifier.compute(data)
        for col in result.columns:
            assert result[col].sum() >= 0


# ============================================================
# 关键K线ABC节点因子测试
# ============================================================

def make_abc_pattern_data(n_days: int = 200) -> pd.DataFrame:
    """生成包含明确A-B-C模式的价格数据。"""
    np.random.seed(123)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    trend = np.zeros(n_days)
    trend[:50] = np.linspace(0, 0.2, 50)
    trend[50:60] = np.linspace(0.2, -1.0, 10)
    trend[60:65] = np.linspace(-1.0, 0.5, 5)
    trend[65:70] = np.linspace(0.5, 0.0, 5)
    trend[70:80] = np.linspace(0.0, 1.5, 10)
    trend[80:] = np.linspace(1.5, 2.5, n_days - 80)

    noise = np.random.randn(n_days) * 0.1
    close = 10 * np.exp(trend + noise)

    daily_range = close * 0.015
    high = close + daily_range * np.random.uniform(0.5, 1.0, n_days)
    low = close - daily_range * np.random.uniform(0.5, 1.0, n_days)
    open_ = close - daily_range * np.random.uniform(-0.5, 0.5, n_days)

    base_vol = np.ones(n_days) * 1_000_000
    base_vol[60:70] *= 2.0
    base_vol[70:80] *= 3.0
    volume = base_vol * np.exp(0.1 * np.random.randn(n_days))

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


class TestKeyKABC:
    """关键K线ABC节点因子测试。"""

    def test_output_format(self):
        """输出为 pd.Series int，值在 0-3 范围。"""
        data = make_synthetic_data(250)
        result = key_k_abc.compute(data)

        assert isinstance(result, pd.Series)
        assert len(result) == len(data)
        assert result.dtype == int
        assert result.index.equals(data.index)
        assert set(result.unique()).issubset({0, 1, 2, 3})

    def test_pattern_detection(self):
        """在明确ABC形态数据上应检测到A、B、C节点。"""
        data = make_abc_pattern_data(200)
        result = key_k_abc.compute(data, lookback=20, rebound_pct=3.0)

        a_signals = result[result == 1]
        b_signals = result[result == 2]
        c_signals = result[result == 3]

        assert len(a_signals) >= 1, "应检测到至少1个A节点"
        assert len(b_signals) >= 1, "应检测到至少1个B节点"
        assert len(c_signals) >= 1, "应检测到至少1个C节点"

        # 验证 A < B < C 顺序
        a_idx = a_signals.index[0]
        b_idx = b_signals.index[0]
        c_idx = c_signals.index[0]
        assert a_idx < b_idx < c_idx, f"A({a_idx}) < B({b_idx}) < C({c_idx})"

    def test_strict_rebound_fewer_signals(self):
        """更严格的反弹阈值应产生更少A信号。"""
        data = make_abc_pattern_data(200)
        loose = key_k_abc.compute(data, rebound_pct=3.0)
        strict = key_k_abc.compute(data, rebound_pct=10.0)
        assert (strict == 1).sum() <= (loose == 1).sum()

    def test_short_data_no_error(self):
        """短数据不报错，返回全0。"""
        data = make_synthetic_data(10)
        result = key_k_abc.compute(data)
        assert isinstance(result, pd.Series)
        assert len(result) == 10

    def test_default_params(self):
        """默认参数运行不报错。"""
        data = make_synthetic_data(250)
        result = key_k_abc.compute(data)
        assert len(result) == len(data)


# ============================================================
# 注册表测试
# ============================================================

class TestFactorRegistry:
    """因子注册表测试。"""

    def test_new_factors_in_registry(self):
        """新因子已在注册表中，type='core'。"""
        expected = [
            "CHIP_CONCENTRATION", "SYMMETRIC_STRUCTURE", "FILL_PIT_EXIT_PIT",
            "LONG_YIN_SHORT_COLUMN", "WAVE_IDENTIFIER", "KEY_K_ABC",
        ]
        for name in expected:
            assert name in FACTOR_REGISTRY, f"因子 {name} 缺失"
            entry = FACTOR_REGISTRY[name]
            assert entry.get("type") == "core", \
                f"{name} type 应为 core，实际: {entry.get('type')}"
            assert "module" in entry
            assert "default_params" in entry
            assert callable(entry["module"].compute)

    def test_compute_via_registry(self):
        """通过注册表调用新因子。"""
        data = make_synthetic_data(250)

        # CHIP_CONCENTRATION 返回 float
        r_cc = compute_factor("CHIP_CONCENTRATION", data)
        assert isinstance(r_cc, pd.Series)
        assert r_cc.dtype == float

        # SYMMETRIC_STRUCTURE 返回 bool
        r_ss = compute_factor("SYMMETRIC_STRUCTURE", data)
        assert isinstance(r_ss, pd.Series)
        assert r_ss.dtype == bool

        # FILL_PIT_EXIT_PIT 返回 bool
        r_fp = compute_factor("FILL_PIT_EXIT_PIT", data)
        assert isinstance(r_fp, pd.Series)
        assert r_fp.dtype == bool

        # LONG_YIN_SHORT_COLUMN 返回 bool
        r_ly = compute_factor("LONG_YIN_SHORT_COLUMN", data)
        assert isinstance(r_ly, pd.Series)
        assert r_ly.dtype == bool

        # WAVE_IDENTIFIER 返回 DataFrame
        r_wv = compute_factor("WAVE_IDENTIFIER", data)
        assert isinstance(r_wv, pd.DataFrame)
        assert list(r_wv.columns) == ["accumulation", "lift", "sprint"]

        # KEY_K_ABC 返回 int
        r_ka = compute_factor("KEY_K_ABC", data)
        assert isinstance(r_ka, pd.Series)
        assert r_ka.dtype == int

    def test_override_params_via_registry(self):
        """通过注册表覆盖参数。"""
        data = make_synthetic_data(200)
        custom = compute_factor("CHIP_CONCENTRATION", data, window=30)
        assert len(custom) == len(data)

    def test_invalid_factor_raises(self):
        """无效因子名抛出 ValueError。"""
        data = make_synthetic_data(100)
        try:
            compute_factor("NONEXISTENT_FACTOR", data)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


# ============================================================
# 集成测试
# ============================================================

class TestIntegration:
    """三个新因子在不同数据上不报错。"""

    def test_standard_data(self):
        """标准合成数据上全部运行通过。"""
        data = make_synthetic_data(300)
        for module, params in [
            (chip_concentration, {"window": 20, "amplitude_max": 15.0}),
            (symmetric_structure, {"tolerance": 0.05, "min_leg_len": 5}),
            (fill_pit_exit_pit, {"drop_pct": 15.0, "consolidation_days": 3, "breakout_vol_mult": 1.5}),
            (long_yin_short_column, {"vol_shrink": 0.7, "body_min_pct": 1.0}),
            (wave_identifier, {}),
            (key_k_abc, {"lookback": 20, "rebound_pct": 3.0}),
        ]:
            result = module.compute(data, **params)
            assert len(result) == len(data), f"{module.__name__}: 长度不匹配"

    def test_v_pattern_data(self):
        """V 型数据上全部运行通过。"""
        data = make_v_pattern_data(120)
        for module, params in [
            (chip_concentration, {"window": 20, "amplitude_max": 15.0}),
            (symmetric_structure, {"tolerance": 0.05, "min_leg_len": 5}),
            (long_yin_short_column, {}),
            (wave_identifier, {}),
            (key_k_abc, {}),
        ]:
            result = module.compute(data, **params)
            assert len(result) == len(data), f"{module.__name__} on V-data: 长度不匹配"

    def test_pit_pattern_data(self):
        """坑型数据上全部运行通过。"""
        data = make_pit_pattern_data(200)
        for module, params in [
            (fill_pit_exit_pit, {"drop_pct": 15.0, "consolidation_days": 3, "breakout_vol_mult": 1.5}),
            (long_yin_short_column, {}),
            (wave_identifier, {}),
            (key_k_abc, {}),
        ]:
            result = module.compute(data, **params)
            assert len(result) == len(data), f"{module.__name__} on pit-data: 长度不匹配"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
