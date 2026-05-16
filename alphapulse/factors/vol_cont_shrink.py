"""缩量因子。

检测当日成交量是否极度萎缩：
当日成交量 < shrink_ratio * 过去recent_period内最大成交量。
"""

import pandas as pd


def compute(
    data: pd.DataFrame,
    shrink_ratio: float = 0.25,
    recent_period: int = 5,
) -> pd.Series:
    """检测缩量信号。

    Args:
        data: 含 'volume' 列的DataFrame
        shrink_ratio: 缩量比例阈值
        recent_period: 近期窗口（不含当日）

    Returns:
        pd.Series: 布尔Series，满足缩量条件为True
    """
    volume = data["volume"]

    # 过去 recent_period 日的最大成交量（用shift排除当日）
    recent_max_vol = volume.shift(1).rolling(recent_period).max()

    result = volume < (shrink_ratio * recent_max_vol)

    return result.fillna(False).astype(bool)
