"""DD 卖出信号因子。

DD (Dark Day): 收盘价 < 前日最低价，表示空方强势。
DD增强: 连续两天出现 DD，强化卖出信号。

全部使用 shift(1) 防止未来函数。

Returns:
    pd.Series[int]: 0=无信号, 1=DD卖出, 2=DD增强卖出
"""

import pandas as pd


def compute(data: pd.DataFrame) -> pd.Series:
    """识别 DD 卖出信号与 DD 增强信号。

    Args:
        data: 含 close/low 的 DataFrame，index=date

    Returns:
        pd.Series[int]: 0=无信号, 1=DD卖出, 2=DD增强卖出
    """
    close = data["close"].astype(float)
    low = data["low"].astype(float)

    n = len(data)
    result = pd.Series(0, index=data.index, dtype=int)
    if n < 3:
        return result

    # DD: 昨日收盘价 < 前日最低价（shift(1)防未来函数）
    dd = close.shift(1) < low.shift(2)

    # DD增强: 连续两天DD（昨日DD 且 前日DD）
    dd_enhanced = dd & dd.shift(1)

    result[dd] = 1
    result[dd_enhanced] = 2

    return result
