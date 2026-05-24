"""暴力K因子。

识别当日涨幅超过阈值且成交量显著放大的暴力K线。
含义：主力暴力拉升，短期强势信号。
"""

import pandas as pd


def compute(
    data: pd.DataFrame,
    pct_threshold: float = 5.0,
    vol_mult: float = 3.0,
) -> pd.Series:
    """识别暴力K线。

    条件：
    1. 当日涨幅 > pct_threshold（百分比，如5.0表示5%）
    2. 成交量 > vol_mult * 20日均量

    Args:
        data: 含 'close', 'volume' 列的DataFrame
        pct_threshold: 涨幅阈值（百分比）
        vol_mult: 成交量倍数阈值

    Returns:
        pd.Series: 布尔Series，满足条件为True
    """
    close = data["close"]
    volume = data["volume"]

    # 涨幅（百分比）
    pct_change = close.pct_change() * 100

    # 涨幅 > 阈值
    gain_condition = pct_change > pct_threshold

    # 成交量 > vol_mult * 20日均量
    vol_ma20 = volume.rolling(20, min_periods=1).mean()
    vol_condition = volume > (vol_mult * vol_ma20)

    result = gain_condition & vol_condition

    return result.fillna(False).astype(bool)
