"""MACD多头或零轴上死叉因子。

- MACD多头：DIF > DEA（柱状图为正）
- 零轴上死叉：DIF从上方下穿DEA，且DIF > 0（零轴上方）
任一条件满足即为True。
"""

import pandas as pd
import numpy as np


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """计算MACD指标。

    Returns:
        (DIF, DEA, MACD_histogram)
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)

    return dif, dea, macd_hist


def compute(
    data: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.Series:
    """MACD多头或零轴上死叉信号。

    - MACD多头：DIF > DEA（即MACD柱 > 0）
    - 零轴上死叉：前一日的DIF > DEA 且 当日DIF <= DEA，且DEA > 0（零轴上方）

    Args:
        data: 含 'close' 列的DataFrame
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期

    Returns:
        pd.Series: 布尔Series
    """
    dif, dea, macd_hist = compute_macd(data["close"], fast, slow, signal)

    # MACD多头：DIF > DEA
    macd_bull = dif > dea

    # 零轴上死叉：前一日DIF>DEA 且 当日DIF<=DEA 且 DEA>0（零轴上方）
    prev_dif_gt_dea = (dif.shift(1) > dea.shift(1))
    curr_dif_le_dea = (dif <= dea)
    above_zero = dea > 0
    zero_axis_death_cross = prev_dif_gt_dea & curr_dif_le_dea & above_zero

    result = macd_bull | zero_axis_death_cross

    return result.fillna(False).astype(bool)
