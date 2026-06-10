"""知行趋势线因子。

来源：知行趋势线.txt

定义：
- 知行短期趋势线: EMA(EMA(C,10),10)
- 知行多空线: (MA(C,M1)+MA(C,M2)+MA(C,M3)+MA(C,M4))/4
  M1/M2/M3/M4 = 14/28/57/114（用户确认的通达信原始参数，见 docs/trading_system.md）

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
    m1: int = 14, m2: int = 28, m3: int = 57, m4: int = 114,
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
    m1: int = 14,
    m2: int = 28,
    m3: int = 57,
    m4: int = 114,
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


def compute_ultra(data: pd.DataFrame) -> pd.Series:
    """知行超短选股方案（docs/tdx_formulas/知行超短选股方案.txt，5条件AND）：

    1. 知行短期趋势线（白线）> 知行多空线（黄线）
    2. 砖型图超短选股公式成立（昨绿今红且红砖≥2/3绿砖）
    3. 当日收盘价 > 黄线
    4. 知行洗盘短线中长期值 > 65
    5. MACD DIF > 0

    Returns:
        pd.Series[bool]
    """
    from alphapulse.factors import brick_ultra, zhixing_washout

    close = data["close"]
    white = compute_short_trend(close)
    yellow = compute_bull_bear_line(close)
    brick = brick_ultra.compute(data)
    med_long = zhixing_washout.compute_lines(data)["med_long"]
    dif = compute_macd_dif(close)

    result = (white > yellow) & brick & (close > yellow) & (med_long > 65) & (dif > 0)
    return result.fillna(False).astype(bool)


def compute_detail(data: pd.DataFrame, **params) -> pd.DataFrame:
    """返回趋势指标详细值。"""
    close = data["close"]
    m1, m2, m3, m4 = params.get("m1", 14), params.get("m2", 28), params.get("m3", 57), params.get("m4", 114)

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
