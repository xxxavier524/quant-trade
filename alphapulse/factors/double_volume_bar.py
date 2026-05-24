"""倍量柱因子。

识别当日成交量较前一日翻倍且为阳线的倍量柱。
含义：量能突变+阳线确认，主力资金进场信号。
"""

import pandas as pd


def compute(
    data: pd.DataFrame,
    mult: float = 2.0,
) -> pd.Series:
    """识别倍量柱。

    条件：
    1. 当日成交量 >= mult * 前一日成交量
    2. 阳线（收盘 > 开盘）

    Args:
        data: 含 'open', 'close', 'volume' 列的DataFrame
        mult: 成交量倍数阈值

    Returns:
        pd.Series: 布尔Series，满足条件为True
    """
    close = data["close"]
    open_ = data["open"]
    volume = data["volume"]

    # 阳线判断
    is_yang = close > open_

    # 成交量 >= mult * 前一日成交量
    prev_volume = volume.shift(1)
    vol_condition = volume >= (mult * prev_volume)

    result = is_yang & vol_condition

    return result.fillna(False).astype(bool)
