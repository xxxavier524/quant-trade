"""生成因子: j15_shrink_half

描述: J值小于15且缩量到5日均量一半
来源: regex
状态: 待验证（validate_signal 后手动启用）
"""

import pandas as pd
import numpy as np




def compute(data, **params):
    """J值小于15且缩量到5日均量一半"""
    close = data['close']
    open_ = data['open']
    high = data['high']
    low = data['low']
    volume = data['volume']

    # KDJ J值计算
    low_9 = low.rolling(9).min()
    high_9 = high.rolling(9).max()
    rsv = (close - low_9) / (high_9 - low_9 + 1e-10) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d
    vol_ma20 = volume.rolling(20).mean()
    result = (j < 15.0) & (volume < vol_ma20 * 0.5)
    return result.fillna(False)