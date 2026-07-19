"""B1 入场过滤器 — 「B1入场三问」与三波理论的可计算部分。

来源：zettaranc trading-core 3.0a / 三波理论（docs/research_journal/12_* P0 #10/#11）：
- 三问之一「离黄线近不近？有没有可控止损？」——在白线和黄线中间飘着、
  往下到黄线还有 10-15% 空间的 B1，止损没法设 → 不做
- 「拉升波第一个 B1 不碰，等回调一半或 SB1」「高位白线第一个 B1 绝不做」
  ——用「近10日涨幅 ≥ lift_min_return」近似拉升波状态（与 wave_identifier
  的拉升波定义一致），该状态下的 B1 视为高位余震，回避。
"""

import pandas as pd

from alphapulse.factors.zhixing_trend import compute_bull_bear_line


def compute_yellow_distance_ok(
    data: pd.DataFrame,
    max_dist: float = 0.08,
    m1: int = 14, m2: int = 28, m3: int = 57, m4: int = 114,
) -> pd.Series:
    """黄线距离过滤：(close-黄线)/close ≤ max_dist 且 close≥黄线 → True=止损可控。

    收盘在黄线下方也算通过（距离为负，止损就在脚下）；
    悬空超过 max_dist（默认8%）→ False=不做。
    """
    close = data["close"].astype(float)
    yellow = compute_bull_bear_line(close, m1, m2, m3, m4)
    dist = (close - yellow) / close
    return (dist <= max_dist).fillna(False).astype(bool)


def compute_lift_wave_avoid(
    data: pd.DataFrame,
    lift_min_return: float = 0.15,
    lift_window: int = 10,
) -> pd.Series:
    """拉升波回避：近 lift_window 日涨幅 ≥ lift_min_return → True=处于拉升波，
    此时出现的（第一个）B1 回避。

    注意语义：True = 应回避（作为负面过滤使用，与 wave_identifier 拉升波定义对齐）。
    """
    close = data["close"].astype(float)
    ret = close / close.shift(lift_window) - 1
    return (ret >= lift_min_return).fillna(False).astype(bool)


def compute(data: pd.DataFrame, **params) -> pd.Series:
    """registry 默认入口 = 黄线距离过滤（True=可做）。"""
    yellow_params = {k: v for k, v in params.items()
                     if k in ("max_dist", "m1", "m2", "m3", "m4")}
    return compute_yellow_distance_ok(data, **yellow_params)
