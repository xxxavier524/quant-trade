"""KDJ J值低位因子。

计算KDJ指标，当J值低于阈值时返回True，
表示超卖状态。
"""

import pandas as pd
import numpy as np


def compute_kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """计算KDJ指标（向量化）。

    Returns:
        (K, D, J) 三个Series
    """
    lowest_low = low.rolling(n).min()
    highest_high = high.rolling(n).max()

    rsv = ((close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)) * 100
    rsv = rsv.fillna(50.0)

    # 迭代计算K、D值（EMA方式）
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d

    return k, d, j


def compute(
    data: pd.DataFrame,
    j_threshold: float = 13.0,
    n: int = 9,
) -> pd.Series:
    """J值低位信号。

    Args:
        data: 含 'high', 'low', 'close' 列的DataFrame
        j_threshold: J值低于此阈值则为True
        n: KDJ计算周期

    Returns:
        pd.Series: 布尔Series
    """
    _, _, j = compute_kdj(data["high"], data["low"], data["close"], n)

    result = j < j_threshold
    if hasattr(result, 'fillna'):
        result = result.fillna(False)

    return result.astype(bool)
