"""知行趋势线因子。

来源：知行趋势线.txt

定义：
- 知行短期趋势线: EMA(EMA(C,10),10)
- 知行多空线: (MA(C,M1)+MA(C,M2)+MA(C,M3)+MA(C,M4))/4
  M1/M2/M3/M4 可配置，默认 20/60/120/250

条件组合（知行超短选股方案.txt）：
1. 短期趋势线 > 多空线
2. 收盘 > 多空线
3. 洗盘短线中长期值 > 65（见 zhixing_washout.py）
4. MACD DIF > 0
"""

import pandas as pd
import numpy as np


def compute_short_trend(close: pd.Series) -> pd.Series:
    """知行短期趋势线: EMA(EMA(C,10),10)。"""
    return close.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean()


def compute_bull_bear_line(
    close: pd.Series,
    m1: int = 20, m2: int = 60, m3: int = 120, m4: int = 250,
) -> pd.Series:
    """知行多空线: 4条MA的均值。"""
    ma1 = close.rolling(m1).mean()
    ma2 = close.rolling(m2).mean()
    ma3 = close.rolling(m3).mean()
    ma4 = close.rolling(m4).mean()
    return (ma1 + ma2 + ma3 + ma4) / 4


def compute_macd_dif(close: pd.Series, fast: int = 12, slow: int = 26) -> pd.Series:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


def compute(
    data: pd.DataFrame,
    m1: int = 20,
    m2: int = 60,
    m3: int = 120,
    m4: int = 250,
) -> pd.Series:
    """知行趋势条件：短期趋势线 > 多空线 AND 收盘 > 多空线 AND DIF > 0。

    Returns:
        pd.Series[bool]
    """
    close = data["close"]

    short_trend = compute_short_trend(close)
    bull_bear = compute_bull_bear_line(close, m1, m2, m3, m4)
    dif = compute_macd_dif(close)

    cond1 = short_trend > bull_bear       # 趋势线 > 多空线
    cond2 = close > bull_bear             # 收盘 > 多空线
    cond3 = dif > 0                       # DIF > 0

    result = cond1 & cond2 & cond3
    return result.fillna(False).astype(bool)


def compute_detail(data: pd.DataFrame, **params) -> pd.DataFrame:
    """返回趋势指标详细值。"""
    close = data["close"]
    m1, m2, m3, m4 = params.get("m1", 20), params.get("m2", 60), params.get("m3", 120), params.get("m4", 250)

    short = compute_short_trend(close)
    bb = compute_bull_bear_line(close, m1, m2, m3, m4)
    dif = compute_macd_dif(close)

    return pd.DataFrame({
        "short_trend": short.round(2),
        "bull_bear": bb.round(2),
        "trend_above": short > bb,
        "close_above_bb": close > bb,
        "macd_dif": dif.round(3),
        "dif_above_0": dif > 0,
    }, index=data.index)
