"""祖冲之目标价 — 填坑场景的模糊正确目标位。

来源：zettaranc「坑里起好货/祖冲之法」（docs/research_journal/12_* P0 #12）：
主力大致要拉到 **2a - b** 再出货才有足够利润空间（a=近期高点，b=近期低点）。
- 填大坑过程中遇到 BBI 下 2 根 K 线可以扛一会儿
- 到达目标价位 → 及时卤煮（止盈）
"""

import pandas as pd


def compute_target(data: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """目标价序列：2*HHV(high,lookback) - LLV(low,lookback)。"""
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    return 2 * high.rolling(lookback).max() - low.rolling(lookback).min()


def compute_reached(data: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """是否触达目标价（用滞后一日的目标，避免用当日高点抬高目标）→ True=触发卤煮。"""
    close = data["close"].astype(float)
    target = compute_target(data, lookback).shift(1)
    return (close >= target).fillna(False).astype(bool)


def compute(data: pd.DataFrame, **params) -> pd.Series:
    """registry 默认入口 = 目标价数值序列（indicator）。"""
    return compute_target(data, **params)
