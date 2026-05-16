"""周线多均线多头因子。

将日线数据重采样为周线，检查MA(5) > MA(10) > MA(20)
是否形成多头排列。返回日线级别的布尔Series。
"""

import pandas as pd
import numpy as np


def compute(
    data: pd.DataFrame,
    ma_periods: list | None = None,
) -> pd.Series:
    """周线级别均线多头排列信号。

    Args:
        data: 含 'close' 列的DataFrame（日线级别）
        ma_periods: 均线周期列表，默认 [5, 10, 20]（周线级别）

    Returns:
        pd.Series: 日线级别布尔Series，对应周的每个交易日为True
    """
    if ma_periods is None:
        ma_periods = [5, 10, 20]

    # 日线转周线
    weekly = data["close"].resample("W").last().dropna()

    if len(weekly) < max(ma_periods):
        return pd.Series(False, index=data.index)

    # 计算周线均线
    mas = {}
    for p in ma_periods:
        mas[p] = weekly.rolling(p).mean()

    # 多头排列：MA5 > MA10 > MA20
    bull_weekly = pd.Series(True, index=weekly.index)
    for i in range(len(ma_periods) - 1):
        bull_weekly &= mas[ma_periods[i]] > mas[ma_periods[i + 1]]

    # 将周线信号映射回日线
    result = pd.Series(False, index=data.index)
    for w_idx in bull_weekly[bull_weekly].index:
        # 找到该周在日线数据中的所有日期
        week_mask = (data.index >= w_idx) & (data.index < w_idx + pd.Timedelta(weeks=1))
        result[week_mask] = True

    return result.astype(bool)
