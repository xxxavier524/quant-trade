"""缩量至异动量1/4因子。

检测当日成交量是否萎缩至异动量（放量异动的参考量级）的1/4以下。
依赖 ABNORMAL_VOL 因子来确定异动量基准。
"""

import pandas as pd
import numpy as np


def compute(
    data: pd.DataFrame,
    ratio: float = 0.25,
    M: int = 60,
    K: float = 2.0,
) -> pd.Series:
    """缩量至异动量1/4信号。

    异动量基准 = K * 过去M日均量
    当 当日成交量 < ratio * 异动量基准 时返回True。

    Args:
        data: 含 'volume' 列的DataFrame
        ratio: 缩量比例（相对于异动量基准）
        M: 均量回溯窗口
        K: 异动倍数

    Returns:
        pd.Series: 布尔Series
    """
    volume = data["volume"]

    # 异动量基准：K倍M日均量
    abnormal_vol_base = K * volume.rolling(M).mean()

    # 当日量 < ratio * 异动量基准
    result = volume < (ratio * abnormal_vol_base)

    return result.fillna(False).astype(bool)
