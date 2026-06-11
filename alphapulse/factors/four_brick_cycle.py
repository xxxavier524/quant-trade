"""砖型图四砖一周期因子（docs/trading_system.md §3 / §4）。

用户体系：砖型图上涨以约4块红砖为一个周期——
- 第1-2块红砖：周期早段，介入有利（多头因子）
- 第4块及以后：周期尾段，应减仓（FLY_AWAY 卖出规则引用"第四块砖减仓"）

实现：
- compute_brick_position: 当前连续红砖数（0=非红砖）
- compute: True = 处于周期早段（第1-2块红砖）
- compute_late: True = 第4块及以后（供卖出/风控引用）

砖型图定义复用 brick_ultra（docs/tdx_formulas/砖型图.txt）。
"""

import pandas as pd

from alphapulse.factors.brick_ultra import compute_brick_indicator


def compute_brick_position(data: pd.DataFrame) -> pd.Series:
    """连续红砖计数：红砖=砖值上升日；非红砖日为0。"""
    brick = compute_brick_indicator(data)
    is_red = brick > brick.shift(1)
    # 向量化连续计数：分组累加（每次False重置）
    groups = (~is_red).cumsum()
    count = is_red.groupby(groups).cumsum()
    return count.fillna(0).astype(int)


def compute(data: pd.DataFrame, early_max: int = 2) -> pd.Series:
    """周期早段（第1~early_max块红砖）= True（多头因子）。"""
    pos = compute_brick_position(data)
    result = (pos >= 1) & (pos <= early_max)
    return result.astype(bool)


def compute_late(data: pd.DataFrame, late_from: int = 4) -> pd.Series:
    """周期尾段（第late_from块红砖起）= True（减仓信号）。"""
    pos = compute_brick_position(data)
    return (pos >= late_from).astype(bool)


def compute_detail(data: pd.DataFrame, **params) -> pd.DataFrame:
    brick = compute_brick_indicator(data)
    pos = compute_brick_position(data)
    return pd.DataFrame({
        "brick": brick.round(2),
        "consecutive_red": pos,
        "early_cycle": compute(data, **{k: v for k, v in params.items() if k == "early_max"}),
        "late_cycle": compute_late(data),
    }, index=data.index)
