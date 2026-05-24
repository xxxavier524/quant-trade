"""放飞减仓因子。

识别加速拉升中的减仓信号，防范冲顶回落风险。

触发条件（全部 shift(1) 防未来函数）：
  1. 连续2根涨幅>3%的阳线 → 减仓1/4
  2. 连续3根涨幅>3%的阳线 → 减仓1/3
  3. 白线上方加速（close>白线 且 涨幅>5%）→ 减仓1/2
  4. 砖型图连续红砖第4块 → 减仓1/3

多条信号同时触发时，取最大减仓比例。
"""

import pandas as pd
import numpy as np

from alphapulse.factors.brick_ultra import compute_brick_indicator
from alphapulse.factors.zhixing_trend import compute_short_trend


def _consecutive_count(condition: pd.Series) -> pd.Series:
    """向量化计算连续满足条件的天数。

    使用 cumsum 分组技巧：每当 condition 翻转（True→False 或 False→True）
    时开始新组，组内 cumsum 即为连续天数。

    Args:
        condition: bool Series，True 表示当天满足条件

    Returns:
        pd.Series[int]: 连续满足天数，不满足时为 0
    """
    # 分组键：condition 每次变化时递增
    group = (condition != condition.shift(1).fillna(False)).cumsum()
    # 组内累加 True 的数量
    consecutive = condition.astype(int).groupby(group).cumsum()
    # 不满足条件的 bar 置 0
    return consecutive.where(condition, 0)


def compute(data: pd.DataFrame) -> pd.DataFrame:
    """计算放飞减仓信号。

    Args:
        data: OHLCV DataFrame，index 为日期，需含 open/high/low/close 列

    Returns:
        pd.DataFrame，index 对齐 data，包含三列：
          - fly_signal (int): 0=无信号, 1=红砖连续, 2=2连阳, 3=3连阳, 4=白线加速
          - reduce_ratio (float): 建议减仓比例
          - reason (str): 触发原因描述
    """
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    idx = data.index
    n = len(data)

    # 初始化结果
    fly_signal = pd.Series(0, index=idx, dtype=int)
    reduce_ratio = pd.Series(0.0, index=idx, dtype=float)
    reason = pd.Series("", index=idx, dtype=object)

    if n < 4:
        return pd.DataFrame({
            "fly_signal": fly_signal,
            "reduce_ratio": reduce_ratio,
            "reason": reason,
        }, index=idx)

    # ================================================================
    # 条件 1 & 2：连续阳线涨幅 > 3%
    # ================================================================
    daily_ret = close.pct_change()
    is_yang_surge = (close > open_) & (daily_ret > 0.03)

    yang_consecutive = _consecutive_count(is_yang_surge)
    # shift(1)：当日信号基于前一日收盘状态
    prev_yang_cnt = yang_consecutive.shift(1).fillna(0).astype(int)

    # 2连阳 → 减仓 1/4
    mask_2 = prev_yang_cnt >= 2
    fly_signal[mask_2] = 2
    reduce_ratio[mask_2] = 0.25
    reason[mask_2] = "连续2根涨幅>3%阳线"

    # 3连阳 → 减仓 1/3（覆盖 2连阳）
    mask_3 = prev_yang_cnt >= 3
    fly_signal[mask_3] = 3
    reduce_ratio[mask_3] = 1.0 / 3.0
    reason[mask_3] = "连续3根涨幅>3%阳线"

    # ================================================================
    # 条件 3：白线上方加速
    # 白线 = EMA(EMA(C,10),10)（知行短期趋势线）
    # ================================================================
    white_line = compute_short_trend(close)
    is_accel = (close > white_line) & (daily_ret > 0.05)
    # shift(1) 防未来函数
    prev_accel = is_accel.shift(1).fillna(False)

    # 白线加速信号（减仓比例更大，0.5）
    mask_accel = prev_accel & (reduce_ratio < 0.5)
    fly_signal[prev_accel] = 4
    reduce_ratio = reduce_ratio.where(~prev_accel, np.maximum(reduce_ratio, 0.5))

    # 更新原因：白线加速优先显示
    no_prev = prev_accel & (reason == "")
    has_prev = prev_accel & (reason != "")
    reason[no_prev] = "白线上方加速(涨幅>5%)"
    reason[has_prev] = reason[has_prev] + "+白线加速"

    # ================================================================
    # 条件 4：砖型图连续红砖 ≥ 4
    # ================================================================
    brick = compute_brick_indicator(data)
    is_red_brick = brick > brick.shift(1).fillna(0)

    red_consecutive = _consecutive_count(is_red_brick)
    # shift(1) 防未来函数
    prev_red_cnt = red_consecutive.shift(1).fillna(0).astype(int)

    mask_red4 = prev_red_cnt >= 4
    # 只在减仓比例不足 1/3 时更新
    need_update = mask_red4 & (reduce_ratio < 1.0 / 3.0)
    fly_signal[need_update] = 1

    # 对所有满足红砖4连的，取 max(reduce_ratio, 1/3)
    reduce_ratio = reduce_ratio.where(~mask_red4, np.maximum(reduce_ratio, 1.0 / 3.0))

    # 更新原因
    red_no_prev = mask_red4 & (reason == "")
    red_has_prev = mask_red4 & (reason != "")
    reason[red_no_prev] = "砖型图连续4块红砖"
    reason[red_has_prev] = reason[red_has_prev] + "+红砖连续"

    return pd.DataFrame({
        "fly_signal": fly_signal,
        "reduce_ratio": reduce_ratio,
        "reason": reason,
    }, index=idx)
