"""B1选股公式因子 — 来自通达信B1选股公式.txt。

6个条件（全部满足=买入信号）：
1. 当日涨幅在±3%以内
2. 当日振幅 < 9%
3. 市值 > 10亿（需外部传入或从数据估算）
4. KDJ J < 13
5. 知行短期趋势线 > 知行多空线（EMA12 > EMA26 近似）
6. MACD DIF > -0.1
"""

import pandas as pd
import numpy as np


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_macd_dif(close: pd.Series, fast: int = 12, slow: int = 26) -> pd.Series:
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    return ema_fast - ema_slow


def compute_kdj_j(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9) -> pd.Series:
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = ((close - low_n) / (high_n - low_n).replace(0, np.nan)) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    return 3 * k - 2 * d


def compute(
    data: pd.DataFrame,
    pct_change_range: float = 3.0,
    amplitude_max: float = 9.0,
    j_threshold: float = 13.0,
    dif_threshold: float = -0.1,
    trend_fast: int = 12,
    trend_slow: int = 26,
) -> pd.Series:
    """B1选股公式：6条件全部满足返回True。

    Args:
        data: 含 open/high/low/close/volume 的DataFrame。
              可选列：pct_change（涨跌幅%），amplitude（振幅%），market_cap（市值）
        pct_change_range: 涨幅范围 ±N%
        amplitude_max: 振幅上限 %
        j_threshold: KDJ J值阈值
        dif_threshold: MACD DIF阈值
        trend_fast: 短期趋势线EMA周期（近似知行短期趋势线）
        trend_slow: 多空线EMA周期（近似知行多空线）

    Returns:
        pd.Series[bool]
    """
    close = data["close"]
    open_ = data["open"]
    high = data["high"]
    low = data["low"]

    n = len(data)
    result = pd.Series(False, index=data.index)

    if n < max(trend_fast, trend_slow, 26) + 5:
        return result

    # 条件1: 当日涨幅在±3%以内
    if "pct_change" in data.columns:
        pct = data["pct_change"]
    else:
        prev_close = close.shift(1)
        pct = (close - prev_close) / prev_close.replace(0, np.nan) * 100
    cond1 = pct.abs() <= pct_change_range

    # 条件2: 当日振幅 < 9%
    if "amplitude" in data.columns:
        amp = data["amplitude"]
    else:
        amp = (high - low) / close.shift(1).replace(0, np.nan) * 100
    cond2 = amp < amplitude_max

    # 条件3: 市值 > 10亿（如无market_cap列，默认通过）
    if "market_cap" in data.columns:
        cond3 = data["market_cap"] > 1e9  # 10亿
    else:
        cond3 = pd.Series(True, index=data.index)  # 数据不足时默认通过

    # 条件4: KDJ J < 13
    j = compute_kdj_j(high, low, close)
    cond4 = j < j_threshold

    # 条件5: 知行短期趋势线 > 知行多空线（EMA12 > EMA26 近似）
    ema_fast = compute_ema(close, trend_fast)
    ema_slow = compute_ema(close, trend_slow)
    cond5 = ema_fast > ema_slow

    # 条件6: MACD DIF > -0.1
    dif = compute_macd_dif(close)
    cond6 = dif > dif_threshold

    result = cond1 & cond2 & cond3 & cond4 & cond5 & cond6
    return result.fillna(False).astype(bool)


def compute_detail(data: pd.DataFrame, **params) -> pd.DataFrame:
    """返回每个条件的详细值，用于调试和复盘。

    Returns:
        DataFrame: 含 cond1~cond6 及综合 signal 列
    """
    pct_range = params.get("pct_change_range", 3.0)
    amp_max = params.get("amplitude_max", 9.0)
    j_thr = params.get("j_threshold", 13.0)
    dif_thr = params.get("dif_threshold", -0.1)
    t_fast = params.get("trend_fast", 12)
    t_slow = params.get("trend_slow", 26)

    close = data["close"]
    high = data["high"]
    low = data["low"]

    if "pct_change" in data.columns:
        pct = data["pct_change"]
    else:
        pct = (close - close.shift(1)) / close.shift(1).replace(0, np.nan) * 100

    if "amplitude" in data.columns:
        amp = data["amplitude"]
    else:
        amp = (high - low) / close.shift(1).replace(0, np.nan) * 100

    j = compute_kdj_j(high, low, close)
    ema_f = compute_ema(close, t_fast)
    ema_s = compute_ema(close, t_slow)
    dif = compute_macd_dif(close)

    return pd.DataFrame({
        "pct_change": pct.round(2),
        "cond1_range": pct.abs() <= pct_range,
        "amplitude": amp.round(2),
        "cond2_amp": amp < amp_max,
        "cond3_cap": True,  # 默认通过
        "kdj_j": j.round(2),
        "cond4_j": j < j_thr,
        "ema_fast": ema_f.round(2),
        "ema_slow": ema_s.round(2),
        "cond5_trend": ema_f > ema_s,
        "macd_dif": dif.round(3),
        "cond6_dif": dif > dif_thr,
        "signal": (pct.abs() <= pct_range) & (amp < amp_max)
                  & (j < j_thr) & (ema_f > ema_s) & (dif > dif_thr),
    }, index=data.index)
