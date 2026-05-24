"""关键K线ABC节点识别因子。

识别关键K线的A-B-C三节点模式：
- A: lookback日最低点 + 反弹确认(>rebound_pct%)
- B: A反弹后的首次回调低点
- C: 突破前高（突破A反弹形成的高点）

输出值: 0=无信号, 1=A, 2=B, 3=C
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def compute(
    data: pd.DataFrame,
    lookback: int = 20,
    rebound_pct: float = 3.0,
    min_leg_len: int = 3,
) -> pd.Series:
    """识别A-B-C关键节点。

    算法流程：
    1. 找到所有lookback日最低点作为A候选
    2. 对每个A候选：向前看3日验证反弹幅度 > rebound_pct% → A确认
    3. 找A反弹峰值后的第一个局部低点 → B
    4. 找B之后第一根收盘突破反弹高点的K线 → C

    Args:
        data: 含 'high', 'low', 'close' 列的DataFrame
        lookback: A点回溯窗口（默认20）
        rebound_pct: A点反弹确认百分比（默认3.0表示3%）
        min_leg_len: 局部极值的最小间隔（传给argrelextrema的order）

    Returns:
        pd.Series: 整数Series，0=无信号, 1=A, 2=B, 3=C
    """
    close = data["close"].values
    high = data["high"].values
    low = data["low"].values
    n = len(data)
    index = data.index

    result = pd.Series(0, index=index, dtype=int)

    # --- Step 1: 识别A点候选（lookback日最低）---
    rolling_min = pd.Series(low, index=index).rolling(lookback).min()
    is_20d_low = data["low"] == rolling_min
    a_candidates = np.where(is_20d_low.values)[0]

    # --- Step 2: 找局部极值点（用于B/C定位）---
    local_min_idx = set(argrelextrema(low, np.less, order=min_leg_len)[0])

    # --- Step 3: 遍历A候选点，确认并找B、C ---
    for a_idx in a_candidates:
        a_low = low[a_idx]

        # 向前看3日确认反弹
        forward_end = min(a_idx + 4, n)
        if forward_end <= a_idx + 1:
            continue

        forward_highs = high[a_idx + 1 : forward_end]
        rebound_peak_val = np.max(forward_highs)
        rebound = (rebound_peak_val - a_low) / a_low * 100.0
        if rebound < rebound_pct:
            continue

        # A 确认
        result.iloc[a_idx] = 1

        # 反弹峰值位置
        rebound_peak_idx = a_idx + 1 + int(np.argmax(forward_highs))

        # --- 找B点：反弹峰值后的第一个局部低点 ---
        b_candidates = sorted([idx for idx in local_min_idx if idx > rebound_peak_idx])
        if not b_candidates:
            continue
        b_idx = b_candidates[0]

        # B的低点应明显低于反弹高点（确保是有效回调）
        if low[b_idx] >= rebound_peak_val * 0.98:
            continue

        result.iloc[b_idx] = 2

        # --- 找C点：B之后收盘突破反弹高点的第一根K线 ---
        for j in range(b_idx + 1, n):
            if close[j] > rebound_peak_val:
                result.iloc[j] = 3
                break

    return result
