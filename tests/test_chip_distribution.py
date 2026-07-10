"""筹码分布因子测试（路线图#5 验收）。

1. 向量化 == 逐日递归参考（金标准对拍，机器精度）
2. 截断因果性（固定网格下，截尾不改前段值 → 无未来泄漏）
3. 性质：profit_ratio∈[0,1]、上涨→获利盘升、单峰→conc90 低
4. 注册表接线

合成数据，不依赖外接盘。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.factors import chip_distribution as cd  # noqa: E402


def _make(n=400, seed=11, low=2.0):
    rng = np.random.default_rng(seed)
    c = pd.Series(20 + rng.standard_normal(n).cumsum() * 0.3).clip(lower=low)
    hi = c * (1 + np.abs(rng.normal(0, 0.02, n)))
    lo = c * (1 - np.abs(rng.normal(0, 0.02, n)))
    return pd.DataFrame({"open": c, "high": hi, "low": lo, "close": c,
                         "volume": rng.integers(1e5, 1e6, n).astype(float),
                         "turnover": rng.uniform(0.5, 8, n)})


@pytest.fixture(scope="module")
def df():
    return _make()


def test_vectorized_matches_sequential(df):
    """向量化 exp-cumsum 必须逐点等于逐日递归参考（金标准）。"""
    vec = cd.compute_chips(df)
    seq = cd._compute_chips_sequential(df)
    for col in ["profit_ratio", "avg_cost", "conc90"]:
        a, b = vec[col].to_numpy(), seq[col].to_numpy()
        m = ~(np.isnan(a) | np.isnan(b))
        assert np.allclose(a[m], b[m], atol=1e-9, rtol=1e-9), \
            f"{col} 向量化≠逐日 maxdiff={np.max(np.abs(a[m]-b[m])):.2e}"


def test_vectorized_matches_sequential_various(df):
    """多组随机数据（含高换手）对拍。"""
    for seed in (1, 7, 99):
        d = _make(n=300, seed=seed)
        d["turnover"] = np.random.default_rng(seed).uniform(5, 25, len(d))  # 高换手
        vec = cd.compute_chips(d)
        seq = cd._compute_chips_sequential(d)
        assert np.allclose(vec.to_numpy(), seq.to_numpy(),
                           atol=1e-8, rtol=1e-8, equal_nan=True)


def test_causality_fixed_grid():
    """截断因果性：价格限定在固定区间（截断不改全局网格）→ 前段每点必须不变。"""
    rng = np.random.default_rng(5)
    n = 400
    # 均值回归价格，全程限定在 [10, 30]，使截断不改变 min(low)/max(high)
    c = pd.Series(20 + 5 * np.sin(np.arange(n) / 15) + rng.normal(0, 0.5, n)).clip(10.5, 29.5)
    # 强制首尾锚定全局极值，确保任意截断(>2)网格一致
    c.iloc[0], c.iloc[1] = 10.0, 30.0
    df = pd.DataFrame({"open": c, "high": c + 0.2, "low": c - 0.2, "close": c,
                       "volume": rng.integers(1e5, 1e6, n).astype(float),
                       "turnover": rng.uniform(1, 5, n)})
    cut = 300
    full = cd.compute_chips(df)
    part = cd.compute_chips(df.iloc[:cut])
    for col in ["profit_ratio", "avg_cost", "conc90"]:
        a = full[col].iloc[:cut].to_numpy()
        b = part[col].to_numpy()
        m = ~(np.isnan(a) | np.isnan(b))
        assert np.allclose(a[m], b[m], atol=1e-9), \
            f"{col} 截断改变前段值（未来泄漏）maxdiff={np.max(np.abs(a[m]-b[m])):.2e}"


def test_profit_ratio_bounds(df):
    pr = cd.compute_chips(df)["profit_ratio"].to_numpy()
    pr = pr[~np.isnan(pr)]
    assert pr.min() >= -1e-9 and pr.max() <= 1 + 1e-9


def test_rising_price_raises_profit_ratio():
    """长期上涨：绝大多数筹码沉在下方 → 末日获利盘应接近 1。"""
    n = 300
    c = pd.Series(np.linspace(10, 30, n))
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                       "volume": np.full(n, 5e5), "turnover": np.full(n, 3.0)})
    pr = cd.compute_chips(df)["profit_ratio"]
    assert pr.iloc[-1] > 0.85, f"上涨末日获利盘仅 {pr.iloc[-1]:.2f}"


def test_falling_price_lowers_profit_ratio():
    """长期下跌：多数筹码在上方套牢 → 末日获利盘应很低。"""
    n = 300
    c = pd.Series(np.linspace(30, 10, n))
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                       "volume": np.full(n, 5e5), "turnover": np.full(n, 3.0)})
    pr = cd.compute_chips(df)["profit_ratio"]
    assert pr.iloc[-1] < 0.15, f"下跌末日获利盘高达 {pr.iloc[-1]:.2f}"


def test_single_peak_tighter_than_dispersed():
    """横盘密集段的 conc90 应低于宽幅震荡段。"""
    n = 300
    rng = np.random.default_rng(3)
    tight = pd.Series(np.full(n, 20.0) + rng.normal(0, 0.1, n))
    wide = pd.Series(20 + 8 * np.sin(np.arange(n) / 10) + rng.normal(0, 0.3, n))
    def mk(c):
        return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                             "volume": np.full(n, 5e5), "turnover": np.full(n, 3.0)})
    c_tight = cd.compute_chips(mk(tight))["conc90"].iloc[-1]
    c_wide = cd.compute_chips(mk(wide))["conc90"].iloc[-1]
    assert c_tight < c_wide, f"横盘 conc90 {c_tight:.3f} 不低于震荡 {c_wide:.3f}"


def test_factors_are_bool(df):
    assert cd.compute(df).dtype == bool
    assert cd.compute_single_peak(df).dtype == bool


def test_one_word_bar_degenerate():
    """一字板（high==low）不应崩溃，筹码落到收盘价桶。"""
    n = 150
    c = pd.Series(np.linspace(10, 12, n))
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                       "volume": np.full(n, 5e5), "turnover": np.full(n, 1.0)})
    out = cd.compute_chips(df)
    assert out["profit_ratio"].notna().any()


def test_registry_wiring(df):
    from alphapulse.factors.factor_registry import compute_factor
    assert compute_factor("CHIP_PROFIT_LOW", df).dtype == bool
    assert compute_factor("CHIP_SINGLE_PEAK", df).dtype == bool
    ind = compute_factor("CHIP_DISTRIBUTION", df)
    assert list(ind.columns) == ["profit_ratio", "avg_cost", "conc90"]


def test_threshold_param(df):
    strict = cd.compute(df, profit_threshold=0.05)
    loose = cd.compute(df, profit_threshold=0.5)
    assert loose.sum() >= strict.sum()  # 更宽阈值命中更多
