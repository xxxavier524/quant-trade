"""红肥绿瘦因子。

比较N日内上涨日与下跌日的平均成交量。
若上涨日平均量 / 下跌日平均量 > ratio_threshold，则为True。
含义：主力在上涨时放量吃货，下跌时缩量洗盘。
"""

import numpy as np
import pandas as pd


def compute(
    data: pd.DataFrame,
    N: int = 20,
    ratio_threshold: float = 1.3,
) -> pd.Series:
    """计算红肥绿瘦信号。

    Args:
        data: 含 'close', 'volume' 列的DataFrame
        N: 回溯窗口
        ratio_threshold: 上涨日均量/下跌日均量的阈值

    Returns:
        pd.Series: 布尔Series，满足条件为True
    """
    close = data["close"]
    volume = data["volume"]

    up_mask = close.diff() > 0
    down_mask = close.diff() < 0

    up_vol_avg = volume.where(up_mask, 0.0).rolling(N).sum() / up_mask.rolling(N).sum().clip(lower=1)
    down_vol_avg = volume.where(down_mask, 0.0).rolling(N).sum() / down_mask.rolling(N).sum().clip(lower=1)

    result = (up_vol_avg / down_vol_avg.replace(0, np.nan)) > ratio_threshold
    result = result.fillna(False)

    return result
