"""洗盘段模板(#6) + MACD面积背驰(#7) 测试。

构造场景直接测语义，合成随机数据测因果性，不依赖外接盘。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.factors import washout_template as wt  # noqa: E402
from alphapulse.factors import macd_divergence as md  # noqa: E402
from alphapulse.factors.macd_bull_dead import compute_macd  # noqa: E402


def _rand_ohlcv(n=300, seed=1):
    rng = np.random.default_rng(seed)
    c = pd.Series(20 + rng.standard_normal(n).cumsum() * 0.3).clip(lower=3)
    return pd.DataFrame({"open": c * 0.99, "high": c * 1.03, "low": c * 0.97,
                         "close": c, "volume": rng.integers(1e5, 2e6, n).astype(float)})


# ---------------------------------------------------------------- #6 washout

def _anchor_df():
    return pd.DataFrame({
        "open": [10] * 15, "high": [11] * 15, "low": [10.5] * 15, "close": [10.5] * 15,
        "volume": [500, 500, 500, 500, 500, 1000, 300, 300, 300, 500,
                   500, 500, 500, 500, 500]})


def test_washout_ok_valid():
    df = _anchor_df()  # 锚@5 vol=1000 open=10；6-8缩量300<0.5*1000且low10.5>10
    assert wt.washout_ok(df, 5, 0.5, "open", min_days=1) is True
    assert wt.washout_ok(df, 5, 0.5, "open", min_days=3) is True


def test_washout_ok_insufficient_days():
    df = _anchor_df()
    assert wt.washout_ok(df, 5, 0.5, "open", min_days=4) is False


def test_washout_ok_breaks_anchor():
    df = _anchor_df()
    df.loc[6, "low"] = 9.0   # 破锚定位10
    assert wt.washout_ok(df, 5, 0.5, "open", min_days=1) is False


def test_washout_ok_no_shrink():
    df = _anchor_df()
    df.loc[6, "volume"] = 900   # 900 > 0.5*1000 未缩量
    assert wt.washout_ok(df, 5, 0.5, "open", min_days=1) is False


def test_washout_ok_out_of_range():
    df = _anchor_df()
    assert wt.washout_ok(df, len(df) - 1, 0.5) is False


def test_washout_compute_bool_and_causal():
    df = _rand_ohlcv()
    sig = wt.compute(df)
    assert sig.dtype == bool
    full = wt.compute(df)
    part = wt.compute(df.iloc[:200])
    assert (full.iloc[:200].to_numpy() == part.to_numpy()).all()


def test_washout_max_vol_ratio_monotone():
    """更宽松的 max_vol_ratio 命中不少于更严格的（缩量门槛更松）。"""
    df = _rand_ohlcv(seed=5)
    loose = wt.compute(df, max_vol_ratio=0.75).sum()
    strict = wt.compute(df, max_vol_ratio=0.4).sum()
    assert loose >= strict


# ---------------------------------------------------------------- #7 MACD背驰

def _two_rally(strong_then_weak=True):
    """两段上涨：strong_then_weak=True → rally2价更高但面积更小(背驰)。"""
    if strong_then_weak:
        seg = ([20] * 40 + list(np.linspace(20, 30, 20)) +
               list(np.linspace(30, 25, 15)) + list(np.linspace(25, 32, 30)) + [32] * 10)
    else:
        seg = ([20] * 40 + list(np.linspace(20, 26, 20)) +
               list(np.linspace(26, 24, 10)) + list(np.linspace(24, 40, 25)) + [40] * 10)
    p = np.array(seg, dtype=float)
    return pd.DataFrame({"open": p, "high": p * 1.005, "low": p * 0.995,
                         "close": p, "volume": np.full(len(p), 1e6)})


def test_divergence_fires_on_shrinking_area():
    """价创新高 + 红柱面积缩 → 背驰信号触发。"""
    df = _two_rally(strong_then_weak=True)
    sig = md.compute(df, divergence_rate=0.9)
    assert sig.sum() == 1
    det = md.compute_detail(df, 0.9)
    fired = det[det["signal"]]
    assert (fired["higher_high"]).all()
    assert (fired["div_ratio"] < 0.9).all()


def test_no_divergence_on_growing_area():
    """价创新高但红柱面积更大（加速上涨）→ 不触发。"""
    df = _two_rally(strong_then_weak=False)
    assert md.compute(df, divergence_rate=1.0).sum() == 0


def test_divergence_rate_threshold_monotone():
    """更高 divergence_rate（更宽松）命中不少于更低阈值。"""
    df = _two_rally(strong_then_weak=True)
    assert md.compute(df, 1.0).sum() >= md.compute(df, 0.7).sum()


def test_divergence_causal():
    df = _rand_ohlcv(seed=9)
    full = md.compute(df, 0.9)
    part = md.compute(df.iloc[:200], 0.9)
    assert (full.iloc[:200].to_numpy() == part.to_numpy()).all()


def test_divergence_signal_on_dead_cross_day():
    """信号日 hist≤0 且前一日 hist>0（死叉日）。"""
    df = _two_rally(strong_then_weak=True)
    _, _, hist = compute_macd(df["close"])
    h = hist.to_numpy()
    for i in np.flatnonzero(md.compute(df, 0.9).to_numpy()):
        assert h[i] <= 0 and h[i - 1] > 0


def test_red_segment_area_matches_manual():
    """红柱段面积 = 段内 hist 之和（手算对齐）。"""
    df = _two_rally(strong_then_weak=True)
    _, _, hist = compute_macd(df["close"])
    h = hist.to_numpy()
    segs = md._red_segments(h, df["high"].to_numpy())
    # 手工找第一段红柱区间求和
    red = h > 0
    i = np.flatnonzero(red)[0]
    j = i
    while j < len(h) and red[j]:
        j += 1
    manual_area = h[i:j].sum()
    assert abs(segs[0][0] - manual_area) < 1e-9


# ---------------------------------------------------------------- 注册

def test_registry_wiring():
    from alphapulse.factors.factor_registry import compute_factor
    df = _rand_ohlcv()
    assert compute_factor("WASHOUT_SEGMENT", df).dtype == bool
    assert compute_factor("MACD_DIVERGENCE", df).dtype == bool
