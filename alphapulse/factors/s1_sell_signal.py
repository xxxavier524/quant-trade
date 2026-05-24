"""S1 最强卖出信号因子。

波段最高点放巨量阴线，识别主力高位出货信号。

条件：
1. 当日阴线 (close < open)
2. 成交量为近vol_window日最高
3. 成交量 > 近vol_window日阳量均值 * vol_mult
4. 前5日至少3日上涨

假阴真阳（close > prev_close 但 close < open）降级为 level=2。

Returns:
    pd.Series[int]: 0=无信号, 1=S1卖出, 2=假阴真阳S1卖出（降级）
"""

import numpy as np
import pandas as pd


def compute(
    data: pd.DataFrame,
    vol_window: int = 20,
    vol_mult: float = 2.0,
) -> pd.Series:
    """识别 S1 最强卖出信号。

    Args:
        data: 含 open/high/low/close/volume 的 DataFrame，index=date
        vol_window: 成交量比较窗口，默认20日
        vol_mult: 阳量均值倍数阈值，默认2.0

    Returns:
        pd.Series[int]: 0=无信号, 1=S1卖出, 2=假阴真阳S1卖出（降级）
    """
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)

    n = len(data)
    result = pd.Series(0, index=data.index, dtype=int)
    if n < vol_window + 5:
        return result

    # ---- 条件1: 当日阴线 ----
    is_yinxian = close < open_

    # ---- 条件2: 成交量是近vol_window日最高 ----
    # 当日成交量严格大于前 (vol_window-1) 日的最大值
    prev_vol_max = volume.shift(1).rolling(vol_window - 1, min_periods=1).max()
    is_vol_highest = volume > prev_vol_max

    # ---- 条件3: 成交量 > 近vol_window日阳量均值 * vol_mult ----
    is_yang = close > open_
    yang_vol_sum = volume.where(is_yang, 0.0).rolling(vol_window, min_periods=1).sum()
    yang_count = is_yang.rolling(vol_window, min_periods=1).sum()
    yang_vol_avg = yang_vol_sum / yang_count.replace(0, np.nan)
    vol_gt_yang = volume > (yang_vol_avg * vol_mult)

    # ---- 条件4: 前5日至少3日上涨（close > prev_close） ----
    is_up_day = close > close.shift(1)
    up_count_5 = is_up_day.shift(1).rolling(5, min_periods=5).sum()
    up_condition = up_count_5 >= 3

    # ---- 综合判断 ----
    s1_base = is_yinxian & is_vol_highest & vol_gt_yang & up_condition

    # 假阴真阳: 阴线但收盘价高于前日收盘价
    fake_yang = is_yinxian & (close > close.shift(1))
    is_fake = s1_base & fake_yang
    is_real = s1_base & ~fake_yang

    result[is_real] = 1
    result[is_fake] = 2

    return result
