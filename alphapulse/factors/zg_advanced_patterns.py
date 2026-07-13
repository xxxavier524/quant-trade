"""Z哥高级战法因子包（P1 #13-#20，docs/research_journal/12_* 缺口分析）。

来源：zettaranc 社区语料 advanced-patterns / trading-core。
全部为日线可计算的近似实现；胜率数字（长安75%等）来自粉丝笔记转述，
**必须先过事件研究（scripts/p1_event_study.py）再决定是否进评分链**。

约定：compute_* 返回与 data.index 对齐的 bool Series，True=信号日。
"""

import numpy as np
import pandas as pd

from alphapulse.factors.b1_formula import compute as b1_compute, compute_kdj_j
from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line


def _vol_ma(volume: pd.Series, n: int = 20) -> pd.Series:
    return volume.rolling(n).mean()


# ---------------------------------------------------------------- #13 双枪/平行重炮

def compute_dual_cannon(
    data: pd.DataFrame,
    gap_min: int = 3,
    gap_max: int = 10,
    cannon_vol_mult: float = 1.5,
    cannon_pct: float = 3.0,
) -> pd.Series:
    """双枪：今日第二枪（放量阳，量>1.5×MA20、涨幅≥3%），gap_min~gap_max 日前有第一枪，
    两枪之间全部缩量（量 < 两枪较小者）→ True。「箭在弦上，不得不发」。"""
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)
    pct = close.pct_change() * 100
    vma = _vol_ma(volume)

    is_cannon = (close > open_) & (pct >= cannon_pct) & (volume > cannon_vol_mult * vma)
    can = is_cannon.to_numpy()
    vol = volume.to_numpy()
    n = len(data)
    out = np.zeros(n, dtype=bool)
    for i in range(gap_min, n):
        if not can[i]:
            continue
        for g in range(gap_min, gap_max + 1):
            j = i - g
            if j < 0 or not can[j]:
                continue
            between = vol[j + 1: i]
            if len(between) and between.max() < min(vol[i], vol[j]):
                out[i] = True
                break
    return pd.Series(out, index=data.index)


# ---------------------------------------------------------------- #14 长安战法

def compute_changan(
    data: pd.DataFrame,
    j_threshold: float = -13.0,
    yang_pct: float = 5.0,
    yang_vol_mult: float = 1.3,
    calm_pct: float = 2.0,
    calm_amp: float = 7.0,
    half_vol: float = 0.6,
) -> pd.Series:
    """长安战法（宣称75%胜率、低频）：
    D-2 为 B1（J<j_threshold）；D-1 放量长阳（涨幅≥5%、量≥1.3×前日、上影短）且J拐头；
    D0 分歧转一致：缩半量（≤0.6×D-1量）、|涨跌幅|<2%、振幅<7% → D0 触发。"""
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)
    pct = close.pct_change() * 100
    amp = (high - low) / close.shift(1).replace(0, np.nan) * 100
    j = compute_kdj_j(high, low, close)

    b1 = b1_compute(data, j_threshold=j_threshold)
    long_yang = (close > open_) & (pct >= yang_pct) & (volume >= yang_vol_mult * volume.shift(1))
    short_upper = (high - close) <= (close - open_) * 0.35
    j_turn = j > j.shift(1)
    d1 = long_yang & short_upper & j_turn

    calm = (pct.abs() < calm_pct) & (amp < calm_amp) & (volume <= half_vol * volume.shift(1))
    sig = b1.shift(2, fill_value=False) & d1.shift(1, fill_value=False) & calm
    return sig.fillna(False).astype(bool)


# ---------------------------------------------------------------- #15 娜娜图

def compute_nana(
    data: pd.DataFrame,
    up_days: int = 3,
    up_vol_mult: float = 1.2,
    top_yin_vol_mult: float = 2.0,
    shrink_days: int = 3,
    lookback: int = 15,
) -> pd.Series:
    """娜娜图：①近期有连续放量上涨段 ②顶部无巨量阴线 ③连续缩量回调≥shrink_days
    ④当日 J<0 → True。"""
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)
    vma = _vol_ma(volume)
    j = compute_kdj_j(high, low, close)

    up_day = (close > close.shift(1)) & (volume > up_vol_mult * vma)
    up_run = up_day.rolling(up_days).sum() == up_days           # 连续放量上涨
    had_up_run = up_run.rolling(lookback, min_periods=1).max().astype(bool)

    big_yin = (close < open_) & (volume > top_yin_vol_mult * vma)
    no_top_yin = big_yin.rolling(lookback, min_periods=1).sum() == 0

    shrink = (volume < vma) & (close <= close.shift(1))
    shrink_run = shrink.rolling(shrink_days).sum() == shrink_days

    sig = had_up_run & no_top_yin & shrink_run & (j < 0)
    return sig.fillna(False).astype(bool)


# ---------------------------------------------------------------- #16 跃跃欲试

def compute_restless(
    data: pd.DataFrame,
    window: int = 20,
    max_amplitude: float = 15.0,
    surge_vol_mult: float = 2.0,
    min_surges: int = 3,
) -> pd.Series:
    """跃跃欲试：横盘（window日振幅≤15%）期间出现≥3次巨量阳（量≥2×MA20）
    且窗口内红肥绿瘦 → True=蓄势（越多次突破概率越大）。仅牛市/未出货前提使用。"""
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)
    vma = _vol_ma(volume)

    hh = close.rolling(window).max()
    ll = close.rolling(window).min()
    flat = (hh - ll) / ll.replace(0, np.nan) * 100 <= max_amplitude

    surge_yang = (close > open_) & (volume >= surge_vol_mult * vma)
    surges = surge_yang.rolling(window).sum() >= min_surges

    yang_vol = (volume * (close > open_)).rolling(window).sum()
    yin_vol = (volume * (close < open_)).rolling(window).sum()
    red_fat = yang_vol > yin_vol

    return (flat & surges & red_fat).fillna(False).astype(bool)


# ---------------------------------------------------------------- #17 灾后重建

def compute_rebuild(
    data: pd.DataFrame,
    cross_lookback: int = 5,
    cross_vol_mult: float = 1.3,
    near_yellow: float = 0.02,
    shrink_mult: float = 0.8,
) -> pd.Series:
    """灾后重建：近 cross_lookback 日内白线放量上穿黄线（金叉），
    今日缩量（<0.8×MA5）回踩至黄线附近（|close-黄线|/close≤2%）→ True=最后震仓。"""
    close = data["close"].astype(float)
    volume = data["volume"].astype(float)
    white = compute_short_trend(close)
    yellow = compute_bull_bear_line(close)

    cross = (white > yellow) & (white.shift(1) <= yellow.shift(1))
    cross_vol = volume > cross_vol_mult * _vol_ma(volume, 5).shift(1)
    gold = cross & cross_vol
    recent_gold = gold.rolling(cross_lookback, min_periods=1).max().astype(bool)

    near = (close - yellow).abs() / close <= near_yellow
    shrink = volume < shrink_mult * volume.rolling(5).mean()
    above = white > yellow                                      # 金叉未失效

    return (recent_gold & near & shrink & above).fillna(False).astype(bool)


# ---------------------------------------------------------------- #18 超级B1

def compute_super_b1(
    data: pd.DataFrame,
    uptrend_gain: float = 0.10,
    uptrend_window: int = 40,
    smash_vol_mult: float = 1.5,
    smash_pct_floor: float = -9.5,
    star_body: float = 1.0,
) -> pd.Series:
    """超级B1：N型上涨背景（40日前→10日前涨幅≥10%）→ 缩量回调中放量下杀阴线（非跌停）
    → 1~3日内缩量企稳 + J负值 + 反转小十字星（实体≤1%）→ True（十字星日）。
    纪律：只赌一次，止损=放量阴线最低价。"""
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)
    pct = close.pct_change() * 100
    vma5 = volume.rolling(5).mean()
    j = compute_kdj_j(high, low, close)

    uptrend = (close.shift(10) / close.shift(uptrend_window) - 1) >= uptrend_gain
    smash = (close < open_) & (pct > smash_pct_floor) & (volume > smash_vol_mult * vma5.shift(1))
    recent_smash = smash.rolling(3, min_periods=1).max().astype(bool).shift(1, fill_value=False)

    star = (close - open_).abs() / close * 100 <= star_body
    shrink = volume < vma5

    sig = uptrend & recent_smash & star & shrink & (j < 0)
    return sig.fillna(False).astype(bool)


# ---------------------------------------------------------------- #19 SB1假摔反包

def compute_sb1_reclaim(
    data: pd.DataFrame,
    flat_days: int = 3,
    flat_amp: float = 8.0,
    break_vol_mult: float = 1.2,
) -> pd.Series:
    """SB1假摔：横盘≥flat_days（振幅≤8%）→ 放量阴线跌破平台低点（吓走跟风盘）
    → 次日收盘收回平台低点之上 → True（收回日；体系为次日开盘买）。"""
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)

    hh = close.rolling(flat_days + 2).max().shift(2)
    ll = close.rolling(flat_days + 2).min().shift(2)
    flat = (hh - ll) / ll.replace(0, np.nan) * 100 <= flat_amp

    broke = (close.shift(1) < ll) & (close.shift(1) < open_.shift(1)) \
        & (volume.shift(1) > break_vol_mult * volume.rolling(5).mean().shift(2))
    reclaim = close > ll

    return (flat & broke & reclaim).fillna(False).astype(bool)


# ---------------------------------------------------------------- #20 蜈蚣图排除

def compute_centipede(
    data: pd.DataFrame,
    window: int = 20,
    messy_ratio: float = 0.45,
    vol_hot: float = 1.2,
    flat_gain: float = 3.0,
) -> pd.Series:
    """蜈蚣图（呼吸紊乱，负面过滤 True=排除）：window 日内
    ①长影/十字星占比≥45% ②量堆高（MA5/MA20≥1.2）③涨幅<3%（堆量不涨）。"""
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)

    body = (close - open_).abs()
    upper = high - close.where(close > open_, open_)
    lower = close.where(close < open_, open_) - low
    messy = (upper > 2 * body) | (lower > 2 * body) | (body / close * 100 <= 0.3)
    messy_pct = messy.rolling(window).mean()

    vol_ratio = volume.rolling(5).mean() / volume.rolling(window).mean()
    gain = (close / close.shift(window) - 1) * 100

    sig = (messy_pct >= messy_ratio) & (vol_ratio >= vol_hot) & (gain.abs() < flat_gain)
    return sig.fillna(False).astype(bool)


def compute(data: pd.DataFrame, **params) -> pd.Series:
    """registry 默认入口 = 双枪。"""
    return compute_dual_cannon(data, **params)
