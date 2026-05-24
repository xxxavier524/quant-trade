"""关键K线因子。

识别近20日内涨幅最大的阳线，且当日成交量显著放大。
含义：放量突破的关键K线，代表主力明确做多信号。
"""

import numpy as np
import pandas as pd


def compute(
    data: pd.DataFrame,
    lookback: int = 20,
    vol_mult: float = 2.0,
) -> pd.Series:
    """识别关键K线。

    条件：
    1. 阳线（收盘 > 开盘）
    2. 当日涨幅在近lookback日内（阳线中）最大
    3. 成交量 > vol_mult * lookback日均量

    Args:
        data: 含 'open', 'close', 'volume' 列的DataFrame
        lookback: 回溯窗口
        vol_mult: 成交量倍数阈值

    Returns:
        pd.Series: 布尔Series，满足条件为True
    """
    close = data["close"]
    open_ = data["open"]
    volume = data["volume"]

    # 阳线判断：收盘 > 开盘
    is_yang = close > open_

    # 涨幅 = (收盘-昨收)/昨收，只保留阳线日的涨幅
    pct_change = close.pct_change()
    yang_gain = pct_change.where(is_yang, -np.inf)

    # 近lookback日内阳线涨幅最大值
    rolling_max_gain = yang_gain.rolling(lookback, min_periods=1).max()

    # 当日阳线涨幅等于滚动最大值（即当日是近lookback日涨幅最大的阳线）
    is_max_gain_yang = is_yang & (yang_gain == rolling_max_gain)

    # 成交量条件：> vol_mult * lookback日均量
    vol_ma = volume.rolling(lookback, min_periods=1).mean()
    vol_condition = volume > (vol_mult * vol_ma)

    result = is_max_gain_yang & vol_condition

    return result.fillna(False).astype(bool)
