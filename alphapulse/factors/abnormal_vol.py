"""放量异动因子。

检测成交量异常放大：当日成交量 > K倍 * 过去M日均量，
且在最近Y日内至少出现X次异动。
"""

import pandas as pd


def compute(
    data: pd.DataFrame,
    M: int = 60,
    P: int = 20,
    K: float = 2.0,
    X: int = 3,
    Y: int = 5,
) -> pd.Series:
    """检测放量异动日。

    Args:
        data: 含 'volume' 列的DataFrame
        M: 计算均量的回溯窗口
        P: 短期均量窗口（用于辅助判断）
        K: 量能倍数阈值
        X: 最小异动次数
        Y: 最近Y日内

    Returns:
        pd.Series: 布尔Series，异动日为True
    """
    volume = data["volume"]

    # 长期均量
    vol_ma_m = volume.rolling(M).mean()
    # 短期均量
    vol_ma_p = volume.rolling(P).mean()

    # 当日成交量 > K倍长期均量
    abnormal_day = volume > (K * vol_ma_m)

    # 额外条件：短期均量也放大（确认短期趋势）
    abnormal_day &= vol_ma_p > vol_ma_m

    # 在最近Y日内至少出现X次
    result = abnormal_day.rolling(Y).sum() >= X

    return result.fillna(False).astype(bool)
