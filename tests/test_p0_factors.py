"""P0 因子包测试（docs/research_journal/12_* 缺口分析 P0 #1-#12）。"""

import numpy as np
import pandas as pd
import pytest

from alphapulse.factors import (
    bbi, sell_score_v14, macd_enhanced, turnover_signals,
    weekly_long_bull, b1_entry_filters, zuchongzhi_target,
)
from alphapulse.factors.factor_registry import FACTOR_REGISTRY, compute_factor
from alphapulse.strategies import zg_b1_brick


def _synth(n=400, seed=0, trend=0.0):
    rng = np.random.default_rng(seed)
    close = 20 + np.cumsum(rng.normal(trend, 0.25, n))
    close = np.abs(close) + 5
    high = close + np.abs(rng.normal(0, 0.2, n))
    low = close - np.abs(rng.normal(0, 0.2, n))
    open_ = close + rng.normal(0, 0.12, n)
    vol = np.abs(rng.normal(1e6, 3e5, n))
    turn = np.abs(rng.normal(3, 1.5, n))
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": vol, "turnover": turn}, index=idx)


# ---------------- BBI 套件 ----------------

def test_bbi_value_and_alignment():
    df = _synth()
    b = bbi.compute(df)
    manual = (df.close.rolling(3).mean() + df.close.rolling(6).mean()
              + df.close.rolling(12).mean() + df.close.rolling(24).mean()) / 4
    pd.testing.assert_series_equal(b, manual, check_names=False)


def test_luzhu_fires_on_two_big_yang_above_bbi():
    df = _synth(seed=1)
    # 人工制造：末两日站上BBI的连续大阳线
    df.iloc[-2, df.columns.get_loc("open")] = df.close.iloc[-3]
    df.iloc[-2, df.columns.get_loc("close")] = df.close.iloc[-3] * 1.06
    df.iloc[-1, df.columns.get_loc("open")] = df.close.iloc[-2]
    df.iloc[-1, df.columns.get_loc("close")] = df.close.iloc[-2] * 1.06
    df.iloc[-1, df.columns.get_loc("high")] = df.close.iloc[-1] * 1.01
    df.iloc[-2, df.columns.get_loc("high")] = df.close.iloc[-2] * 1.01
    sig = bbi.compute_luzhu(df)
    assert bool(sig.iloc[-1])


def test_bbi_break_two_days():
    df = _synth(seed=2)
    b = bbi.compute_bbi(df.close)
    df.iloc[-2, df.columns.get_loc("close")] = b.iloc[-2] * 0.9
    df.iloc[-1, df.columns.get_loc("close")] = b.iloc[-2] * 0.88
    sig = bbi.compute_bbi_break(df)
    assert bool(sig.iloc[-1])
    # 单日破位不触发
    df2 = _synth(seed=2)
    b2 = bbi.compute_bbi(df2.close)
    df2.iloc[-1, df2.columns.get_loc("close")] = b2.iloc[-1] * 0.9
    assert not bool(bbi.compute_bbi_break(df2).iloc[-1]) or df2.close.iloc[-2] < b2.iloc[-2]


# ---------------- 防卖飞 V1.4 ----------------

def test_sell_score_range_and_detail():
    df = _synth(seed=3)
    detail = sell_score_v14.compute_detail(df)
    score = detail["score"]
    assert score.between(0, 5).all()
    items = detail[["close_up", "bbi_hold", "no_fangliang_yin", "trend_up", "j_alive"]]
    pd.testing.assert_series_equal(items.sum(axis=1).astype(int), score, check_names=False)


def test_sell_score_registry():
    df = _synth(seed=3)
    s = compute_factor("SELL_SCORE_V14", df)
    assert s.between(0, 5).all()


# ---------------- MACD 增强包 ----------------

def test_macd_zero_axis_matches_dif_sign():
    df = _synth(seed=4, trend=0.05)
    dif, _, _ = macd_enhanced.compute_macd(df.close)
    za = macd_enhanced.compute_zero_axis(df)
    assert ((dif > 0) == za).all()


def test_macd_veto_blocks_below_zero_without_divergence():
    df = _synth(seed=5, trend=-0.08)  # 单边下跌：DIF<0 且大概率无底背离
    veto = macd_enhanced.compute_veto(df)
    dif, _, _ = macd_enhanced.compute_macd(df.close)
    # veto 为 True 的日子必然 DIF<0
    assert (dif[veto] < 0).all()


def test_macd_divergence_and_fake_cross_dtypes():
    df = _synth(seed=6)
    for fn in (macd_enhanced.compute_top_divergence,
               macd_enhanced.compute_bottom_divergence,
               macd_enhanced.compute_fake_gold_cross,
               macd_enhanced.compute_fake_dead_cross):
        s = fn(df)
        assert s.dtype == bool and s.index.equals(df.index)


# ---------------- 换手率信号 ----------------

def test_turnover_patch_passes_without_column():
    df = _synth(seed=7).drop(columns=["turnover"])
    assert turnover_signals.compute_b1_turnover_patch(df).all()


def test_turnover_patch_blocks_high_churn():
    df = _synth(seed=8)
    # 制造3根高换手中大阳线（各20%换手，累计60>38）
    for i in (-6, -4, -2):
        df.iloc[i, df.columns.get_loc("open")] = df.close.iloc[i - 1]
        df.iloc[i, df.columns.get_loc("close")] = df.close.iloc[i - 1] * 1.05
        df.iloc[i, df.columns.get_loc("turnover")] = 20.0
    sig = turnover_signals.compute_b1_turnover_patch(df)
    assert not bool(sig.iloc[-1])


def test_high_turnover_exit():
    df = _synth(seed=9)
    df.iloc[-4:, df.columns.get_loc("turnover")] = 45.0  # 4日累计180 ≥160
    assert bool(turnover_signals.compute_high_turnover_exit(df).iloc[-1])
    df2 = _synth(seed=9)  # 正常换手不触发
    assert not turnover_signals.compute_high_turnover_exit(df2).any()


# ---------------- 周线大多头 / 入场过滤 / 祖冲之 ----------------

def test_weekly_long_bull_insufficient_history_false():
    df = _synth(n=300, seed=10)  # 300日 < 233周
    assert not weekly_long_bull.compute(df).any()


def test_weekly_long_bull_uptrend_true():
    n = 1400  # ~5.5年
    idx = pd.date_range("2020-01-02", periods=n, freq="B")
    close = pd.Series(np.linspace(10, 80, n) + np.random.default_rng(0).normal(0, 0.3, n), index=idx)
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": 1e6}, index=idx)
    assert weekly_long_bull.compute(df).iloc[-1]


def test_yellow_distance_filter():
    df = _synth(n=300, seed=11)
    ok = b1_entry_filters.compute_yellow_distance_ok(df, max_dist=0.08)
    from alphapulse.factors.zhixing_trend import compute_bull_bear_line
    yellow = compute_bull_bear_line(df.close.astype(float))
    dist = (df.close - yellow) / df.close
    valid = dist.notna()
    assert ((dist[valid] <= 0.08) == ok[valid]).all()


def test_lift_wave_avoid():
    df = _synth(seed=12)
    df.iloc[-1, df.columns.get_loc("close")] = df.close.iloc[-11] * 1.30  # 10日+30%
    assert bool(b1_entry_filters.compute_lift_wave_avoid(df).iloc[-1])


def test_zuchongzhi_target_formula():
    df = _synth(seed=13)
    t = zuchongzhi_target.compute_target(df, lookback=60)
    manual = 2 * df.high.rolling(60).max() - df.low.rolling(60).min()
    pd.testing.assert_series_equal(t, manual, check_names=False)
    reached = zuchongzhi_target.compute_reached(df)
    assert reached.dtype == bool


# ---------------- ZG v2 ----------------

def test_zg_v2_is_subset_of_v1_positions():
    df = _synth(seed=14)
    v1 = zg_b1_brick.compute(df)                                   # 第1-2砖
    v2_pos = zg_b1_brick.compute(df, positions=[2])                # 仅第2砖
    assert (v1 | ~v2_pos).all()                                    # v2 ⊆ v1


def test_zg_v2_dif_gate_subset():
    df = _synth(seed=15)
    without = zg_b1_brick.compute(df, positions=[2])
    with_gate = zg_b1_brick.compute(df, positions=[2], require_dif_positive=True)
    assert (without | ~with_gate).all()                            # 加门后 ⊆ 不加门


def test_zg_v2_registry_entry():
    entry = FACTOR_REGISTRY["ZG_B1_BRICK_V2"]
    assert entry["default_params"]["positions"] == [2]
    assert entry["default_params"]["require_dif_positive"] is True


# ---------------- registry 完整性 ----------------

@pytest.mark.parametrize("name", [
    "BBI_INDICATOR", "LUZHU_TAKE_PROFIT", "BBI_BREAK_EXIT", "SELL_SCORE_V14",
    "MACD_VETO", "MACD_ZERO_AXIS", "MACD_TOP_DIVERGENCE", "MACD_FAKE_GOLD_CROSS",
    "B1_TURNOVER_PATCH", "HIGH_TURNOVER_EXIT", "WEEKLY_LONG_BULL",
    "YELLOW_DISTANCE_OK", "LIFT_WAVE_AVOID", "ZUCHONGZHI_TARGET",
])
def test_p0_registry_callable(name):
    df = _synth(seed=42)
    out = compute_factor(name, df)
    assert len(out) == len(df)
