"""生成因子: bowl_j20_surge

描述: 股价在知行黄线之上但白线之下（掉进碗里），且当日J值低于20，且最近3天内出现过一根成交量超过40日均量1.8倍的阳线
来源: deepseek
状态: 待验证（validate_signal 后手动启用）
"""

import pandas as pd
import numpy as np


def compute(data: pd.DataFrame, **params) -> pd.Series:
    """
    条件：
    1. 股价在知行黄线之上但白线之下（c > yellow_line and c < white_line）
    2. 当日 J 值 < j_threshold（默认 20）
    3. 最近 3 天内出现过一根成交量 > vol_ratio（默认 1.8）倍 40 日均量的阳线
    """
    j_th = params.get("j_threshold", 20.0)
    vol_ratio = params.get("vol_ratio", 1.8)
    vol_ma_period = params.get("vol_ma_period", 40)

    c, h, l, o, v = data["close"], data["high"], data["low"], data["open"], data["volume"]

    # 知行白线：close 的 EWM(span=10) 再做一次 EWM(span=10)
    white = c.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean()
    # 知行黄线：(MA14 + MA28 + MA57 + MA114) / 4
    yellow = (
        c.rolling(14).mean() +
        c.rolling(28).mean() +
        c.rolling(57).mean() +
        c.rolling(114).mean()
    ) / 4

    # KDJ 中 J 值计算
    low_9 = l.rolling(9).min()
    high_9 = h.rolling(9).max()
    rsv = (c - low_9) / (high_9 - low_9) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d

    # 成交量放量阳线条件
    vol_ma = v.rolling(vol_ma_period).mean()
    yang_volume = (c > o) & (v > vol_ratio * vol_ma)

    # 最近 3 天内出现过放量阳线（包含今日）
    recent_3 = yang_volume.rolling(3).max().fillna(0).astype(bool)

    # 组合条件
    cond = (c > yellow) & (c < white) & (j < j_th) & recent_3
    return cond.fillna(False).astype(bool)