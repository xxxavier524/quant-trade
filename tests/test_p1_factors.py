"""P1 形态战法/筹码因子测试（dtype·对齐·registry 可调用）。"""

import numpy as np
import pandas as pd
import pytest

from alphapulse.factors import zg_advanced_patterns as zap
from alphapulse.factors import chip_laws
from alphapulse.factors.factor_registry import compute_factor
from alphapulse.utils.top_tax import top_tax_cut, max_position_for_drawdown


def _synth(n=300, seed=0):
    rng = np.random.default_rng(seed)
    close = 20 + np.cumsum(rng.normal(0.02, 0.3, n))
    close = np.abs(close) + 5
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.15, n),
        "high": close + np.abs(rng.normal(0, 0.25, n)),
        "low": close - np.abs(rng.normal(0, 0.25, n)),
        "close": close,
        "volume": np.abs(rng.normal(1e6, 4e5, n)),
        "turnover": np.abs(rng.normal(3, 1.5, n)),
    }, index=idx)


ALL_FNS = [
    zap.compute_dual_cannon, zap.compute_changan, zap.compute_nana,
    zap.compute_restless, zap.compute_rebuild, zap.compute_super_b1,
    zap.compute_sb1_reclaim, zap.compute_centipede,
    chip_laws.compute_low_density, chip_laws.compute_locked_lift,
    chip_laws.compute_high_density_forbid,
]


@pytest.mark.parametrize("fn", ALL_FNS, ids=lambda f: f.__name__)
def test_bool_series_aligned(fn):
    df = _synth()
    s = fn(df)
    assert s.dtype == bool and s.index.equals(df.index)


def test_dual_cannon_synthetic_trigger():
    df = _synth(seed=1)
    v = df.volume.rolling(20).mean()
    for i in (-8, -1):                                   # 两枪，间隔7天
        df.iloc[i, df.columns.get_loc("open")] = df.close.iloc[i - 1]
        df.iloc[i, df.columns.get_loc("close")] = df.close.iloc[i - 1] * 1.05
        df.iloc[i, df.columns.get_loc("volume")] = v.iloc[i] * 3
    for i in range(-7, -1):                              # 中间缩量
        df.iloc[i, df.columns.get_loc("volume")] = v.iloc[i] * 0.3
    assert bool(zap.compute_dual_cannon(df).iloc[-1])


def test_chip_detail_ranges():
    df = _synth(seed=2)
    d = chip_laws.compute_detail(df)
    assert d["profit_ratio"].between(0, 1).all()
    assert d["peak_concentration"].between(0, 1).all()
    assert (d["avg_cost"].iloc[100:] > 0).all()


def test_top_tax_utils():
    assert top_tax_cut(0.4, 0.3) == pytest.approx(0.12)
    assert top_tax_cut(-0.1) == 0.0
    assert max_position_for_drawdown(0.05, 0.10, 2) == pytest.approx(0.25)


@pytest.mark.parametrize("name", [
    "DUAL_CANNON", "CHANGAN", "NANA_PATTERN", "RESTLESS_BREAKOUT",
    "REBUILD_AFTER_DISASTER", "SUPER_B1", "SB1_RECLAIM", "CENTIPEDE_FILTER",
    "CHIP_LOW_DENSITY", "CHIP_LOCKED_LIFT", "CHIP_HIGH_DENSITY_FORBID",
])
def test_p1_registry_callable(name):
    df = _synth(seed=42)
    out = compute_factor(name, df)
    assert len(out) == len(df)
