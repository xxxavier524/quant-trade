"""量能B1选股因子。

来源：量能B1选股.txt

完整翻译通达信量能B1选股公式到Python。
核心逻辑：
- 阳量/阴量比例（28日 1.65x, 14日 2.25x）
- J≤13, 市值≥40亿
- 28日高位(TOP15%)放量阴线≤0次
- 爆量阳/连续爆量阳/缩倍量阴 → 28日内≥3种
- 28日内最大量为阴线=0次
- 收盘 > 0.99*QL（QL=0.4*MA20+0.3*MA60+0.2*MA120+0.1*MA250）
"""

import pandas as pd
import numpy as np


def _real_yang(open_, close, prev_close):
    """真阳线: C>O 且 非假阳（C<REF(C,1)的假阳线排除）。"""
    return (close > open_) & ~(close < prev_close)


def _real_yin(open_, close, prev_close):
    """真阴线: C<O 且 非假阴。"""
    return (close < open_) & ~(close > prev_close)


def compute_kdj_j(high, low, close, n=9):
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = ((close - low_n) / (high_n - low_n).replace(0, np.nan)) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    return 3 * k - 2 * d


def compute(
    data: pd.DataFrame,
    yangyin_ratio_28: float = 1.65,
    yangyin_ratio_14: float = 2.25,
    j_threshold: float = 13.0,
    min_market_cap: float = 40e8,  # 元（流通市值，对应TDX MV:=C*CAPITAL ≥ 40亿）
    surge_ratio: float = 1.85,
    half_down_ratio: float = 0.5,
) -> pd.Series:
    """量能B1选股：复杂的多条件量能体系。

    Args:
        data: 含 open/high/low/close/volume 的DataFrame。
              可选: market_cap（流通市值，单位元，与 b1_formula 统一）
        yangyin_ratio_28: 28日阳量/阴量阈值
        yangyin_ratio_14: 14日阳量/阴量阈值
        j_threshold: KDJ J值阈值
        min_market_cap: 最小市值（亿）
        surge_ratio: 爆量倍率
        half_down_ratio: 缩倍量比例

    Returns:
        pd.Series[bool]
    """
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    volume = data["volume"].astype(float)
    prev_close = close.shift(1)

    n = len(data)
    result = pd.Series(False, index=data.index)
    if n < 60:
        return result

    # --- 真阳/真阴 ---
    real_yang = _real_yang(open_, close, prev_close)
    real_yin = _real_yin(open_, close, prev_close)

    # --- KDJ ---
    j = compute_kdj_j(high, low, close)
    j_ok = j <= j_threshold

    # --- 阳量/阴量比 ---
    vol_yang_28 = (volume * real_yang).rolling(28).sum()
    vol_yin_28 = (volume * real_yin).rolling(28).sum()
    yangyin_ok1 = vol_yang_28 > yangyin_ratio_28 * vol_yin_28.replace(0, np.nan)

    vol_yang_14 = (volume * real_yang).rolling(14).sum()
    vol_yin_14 = (volume * real_yin).rolling(14).sum()
    yangyin_ok2 = vol_yang_14 > yangyin_ratio_14 * vol_yin_14.replace(0, np.nan)

    # --- 市值检查 ---
    if "market_cap" in data.columns:
        mv_ok = data["market_cap"] >= min_market_cap
    else:
        mv_ok = pd.Series(True, index=data.index)

    # --- 28日高位放量阴线过滤 ---
    o85 = open_.rolling(28).min() + 0.95 * (open_.rolling(28).max() - open_.rolling(28).min())
    top15o = open_ >= o85
    fd15 = (close < prev_close) & (close <= open_) & (volume >= 1.15 * volume.shift(1))
    cnt28_bad = (top15o & fd15).rolling(28).sum()
    good28 = cnt28_bad <= 0

    # --- 爆量阳/连续爆量阳/缩倍量阴 ---
    avg40 = volume.rolling(40).mean()
    plry = (volume > surge_ratio * volume.shift(1)) & (close > open_) & (volume > avg40)
    plry_cnt = (plry.rolling(14).sum() >= 2) | (plry.rolling(28).sum() >= 3)
    plry_first = plry & ~plry.shift(1, fill_value=False)
    plry_cont = plry & plry.shift(1, fill_value=False)
    half_down = ~real_yin.shift(1, fill_value=False) & (close < prev_close) & (volume <= half_down_ratio * volume.shift(1))

    cnt_first = plry_first.rolling(28).sum()
    cnt_cont = plry_cont.rolling(28).sum()
    cnt_half = half_down.rolling(28).sum()
    three_sum_ok = (cnt_first + cnt_cont + cnt_half) >= 3

    # --- 28日最大量为阴线过滤 ---
    maxvol28 = volume.rolling(28).max()
    max28_bad = (volume == maxvol28) & real_yin
    max28_ok = max28_bad.rolling(28).sum() == 0

    # --- QL 加权均线 ---
    ql = 0.4 * close.rolling(20).mean() + 0.3 * close.rolling(60).mean() \
         + 0.2 * close.rolling(120).mean() + 0.1 * close.rolling(250).mean()
    price_above_ql = close > 0.99 * ql

    # --- 综合条件 ---
    a1 = (plry_cnt & yangyin_ok1 & j_ok & mv_ok & good28 & three_sum_ok & max28_ok) \
       | (plry_cnt & yangyin_ok2 & j_ok & mv_ok & good28 & max28_ok)

    result = a1 & price_above_ql
    return result.fillna(False).astype(bool)


def compute_detail(data: pd.DataFrame) -> pd.DataFrame:
    """返回量能B1各子条件的详细值。"""
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    volume = data["volume"].astype(float)
    prev_close = close.shift(1)

    real_yang = _real_yang(open_, close, prev_close)
    real_yin = _real_yin(open_, close, prev_close)
    j = compute_kdj_j(high, low, close)

    vol_yang_28 = (volume * real_yang).rolling(28).sum()
    vol_yin_28 = (volume * real_yin).rolling(28).sum()
    plry = (volume > 1.85 * volume.shift(1)) & (close > open_) & (volume > volume.rolling(40).mean())
    ql = 0.4 * close.rolling(20).mean() + 0.3 * close.rolling(60).mean() \
         + 0.2 * close.rolling(120).mean() + 0.1 * close.rolling(250).mean()

    return pd.DataFrame({
        "kdj_j": j.round(2),
        "j_ok": j <= 13,
        "yang_vol_28": vol_yang_28.round(0),
        "yin_vol_28": vol_yin_28.round(0),
        "yangyin_ratio_28": (vol_yang_28 / vol_yin_28.replace(0, np.nan)).round(2),
        "plry_count_28": plry.rolling(28).sum(),
        "ql": ql.round(2),
        "close_above_ql": close > 0.99 * ql,
    }, index=data.index)
