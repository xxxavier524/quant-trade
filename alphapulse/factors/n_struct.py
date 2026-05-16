"""N型结构识别因子。

识别价格走势中的N型结构（上升-回撤-再上升），
返回每个bar所处的阶段标签：'A'（起点低点）、'B'（第一波上升）、
'C'（回撤）、'D'（第二波突破），其余为NaN。
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def find_pivots(series: pd.Series, min_leg_len: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """找出局部极值点（波峰和波谷）。"""
    order = min_leg_len
    local_max_idx = argrelextrema(series.values, np.greater, order=order)[0]
    local_min_idx = argrelextrema(series.values, np.less, order=order)[0]
    return local_max_idx, local_min_idx


def compute(
    data: pd.DataFrame,
    min_leg_len: int = 5,
    retrace_ratio: float = 0.618,
) -> pd.Series:
    """识别N型结构，返回每根bar的阶段标签。

    N型结构定义：
    - A: 显著低点（波谷）
    - B: 显著高点（波峰），AB为上升段
    - C: 从B回撤到约 retrace_ratio 位置的低点
    - D: 突破B或接近B的后续高点

    Returns:
        pd.Series: index对齐data，值为 'A','B','C','D' 或 NaN
    """
    close = data["close"].values
    high = data["high"].values
    low = data["low"].values
    index = data.index

    result = pd.Series(np.nan, index=index, dtype=object)

    # 用high找波峰，用low找波谷
    high_peaks, low_troughs = find_pivots(data["high"], min_leg_len)

    if len(low_troughs) < 2 or len(high_peaks) < 2:
        return result

    # 遍历波谷，寻找N型：波谷A -> 波峰B -> 回撤C -> 突破D
    trough_set = set(low_troughs)
    peak_set = set(high_peaks)

    for i, a_idx in enumerate(low_troughs[:-1]):
        a_val = low[a_idx]

        # 找A之后的第一个波峰B
        b_candidates = [p for p in high_peaks if p > a_idx]
        if not b_candidates:
            continue
        b_idx = b_candidates[0]
        b_val = high[b_idx]
        ab_range = b_val - a_val
        if ab_range <= 0:
            continue

        # 找B之后的第一个波谷C（回撤到A-B的retrace_ratio附近）
        c_candidates = [t for t in low_troughs if t > b_idx]
        if not c_candidates:
            continue
        c_idx = c_candidates[0]
        c_val = low[c_idx]

        # 检查回撤幅度是否在retrace_ratio的容忍范围内（±15%）
        actual_retrace = (b_val - c_val) / ab_range
        retrace_tolerance = 0.15
        if not (retrace_ratio - retrace_tolerance <= actual_retrace <= retrace_ratio + retrace_tolerance):
            continue

        # 找C之后的第一个波峰D（应高于B或接近B）
        d_candidates = [p for p in high_peaks if p > c_idx]
        if not d_candidates:
            continue
        d_idx = d_candidates[0]
        d_val = high[d_idx]

        # D应接近或突破B
        if d_val < b_val * 0.95:
            continue

        # 标记各段
        result.iloc[a_idx] = "A"
        result.iloc[b_idx] = "B"
        result.iloc[c_idx] = "C"
        result.iloc[d_idx] = "D"

    return result
