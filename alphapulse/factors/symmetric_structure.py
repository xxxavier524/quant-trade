"""对称结构识别因子。

识别 V 型（单底对称）和 W 型（双底对称）形态。
使用 scipy.signal.argrelextrema 定位极值点，完全向量化匹配。

V 型：下降段 → 低点 → 上升段，左右端点价格接近（对称）
W 型：两个近似等低的底 + 中间反弹峰 + 突破确认
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def compute(
    data: pd.DataFrame,
    tolerance: float = 0.05,
    min_leg_len: int = 5,
) -> pd.Series:
    """识别 V/W 型对称结构，返回布尔 Series。

    形态定义：
    - V 型：从高位回落形成低点，再从低点回升到与起点相近的高度。
      左腿下降段 >= min_leg_len 天，右腿上升段 >= min_leg_len 天，
      左右端点 close 偏差 <= tolerance。
    - W 型：两个近似等高的低点（偏差 <= tolerance），中间有反弹峰，
      且最终突破中间峰（或接近），形成双底结构。

    Args:
        data: 含 'high','low','close' 列的 DataFrame
        tolerance: 对称容忍度（价格偏差比例，默认 0.05 = 5%）
        min_leg_len: 最小腿长（默认 5 天，用于极值检测的 order 参数）

    Returns:
        pd.Series[bool]: 形态完成日为 True
    """
    close = data["close"].values
    index = data.index
    n = len(close)

    result = pd.Series(False, index=index)

    if n < 2 * min_leg_len + 1:
        return result

    # --- 找局部极值点（完全向量化） ---
    order = min_leg_len
    local_min_idx = argrelextrema(close, np.less, order=order)[0]
    local_max_idx = argrelextrema(close, np.greater, order=order)[0]

    if len(local_min_idx) < 1:
        return result

    # ============================================================
    # V 型检测：低点两侧对称回升
    # ============================================================
    # 对于每个局部低点 i：
    #   左端点 = i - min_leg_len，右端点 = i + min_leg_len
    #   须在数组范围内，且左右端点 close 偏差在 tolerance 内
    mins_arr = local_min_idx
    left_idx = mins_arr - min_leg_len
    right_idx = mins_arr + min_leg_len

    # 先过滤掉越界的索引（防止 numpy 下标越界）
    in_bounds = (left_idx >= 0) & (right_idx < n)
    if in_bounds.any():
        bound_mins = mins_arr[in_bounds]
        bound_left = left_idx[in_bounds]
        bound_right = right_idx[in_bounds]

        # 检查两端是否高于低点
        valid_v = (
            (close[bound_left] > close[bound_mins])
            & (close[bound_right] > close[bound_mins])
        )

        if valid_v.any():
            vmins = bound_mins[valid_v]
            vleft = bound_left[valid_v]
            vright = bound_right[valid_v]

            left_close = close[vleft]
            right_close = close[vright]
            price_deviation = (
                np.abs(right_close - left_close) / np.maximum(left_close, 1e-10)
            )

            v_match = price_deviation <= tolerance
            matched_right = vright[v_match]
            result.iloc[matched_right] = True

    # ============================================================
    # W 型检测：两个近似等低的最小值 + 中间反弹峰 + 突破
    # ============================================================
    # 遍历相邻的局部低点对
    if len(local_min_idx) >= 2:
        # 对相邻低点对计算价格偏差
        mins_pairs_low = close[local_min_idx[:-1]]
        mins_pairs_high = close[local_min_idx[1:]]
        pair_deviation = (
            np.abs(mins_pairs_high - mins_pairs_low)
            / np.maximum(mins_pairs_low, 1e-10)
        )

        # 两个低点价格接近
        w_height_match = pair_deviation <= tolerance

        # 两个低点间距合理（>= min_leg_len 且 <= 60 天）
        pair_distance = local_min_idx[1:] - local_min_idx[:-1]
        w_dist_ok = (pair_distance >= min_leg_len) & (pair_distance <= 60)

        w_candidates = w_height_match & w_dist_ok

        if w_candidates.any():
            candidate_indices = np.where(w_candidates)[0]
            for ci in candidate_indices:
                left_min_idx = local_min_idx[ci]
                right_min_idx = local_min_idx[ci + 1]

                # 两个低点之间至少有一个局部高点
                peaks_between = local_max_idx[
                    (local_max_idx > left_min_idx) & (local_max_idx < right_min_idx)
                ]
                if len(peaks_between) == 0:
                    continue

                middle_peak_val = close[peaks_between].max()
                bottom_val = max(close[left_min_idx], close[right_min_idx])

                # 反弹幅度 >= 两个底之间跌幅的 30%（确认有效反弹）
                rebound = (middle_peak_val - bottom_val) / max(bottom_val, 1e-10)
                if rebound < 0.03:  # 至少反弹 3%
                    continue

                # 突破确认：右底之后价格突破中间峰
                breakthrough_idx = right_min_idx + 1
                while breakthrough_idx < n:
                    if close[breakthrough_idx] >= middle_peak_val * 0.98:
                        result.iloc[breakthrough_idx] = True
                        break
                    breakthrough_idx += 1

    return result


def compute_v_only(
    data: pd.DataFrame,
    tolerance: float = 0.05,
    min_leg_len: int = 5,
) -> pd.Series:
    """仅检测 V 型反转形态（不含 W 型）。

    Returns:
        pd.Series[bool]: V 型右腿完成日为 True
    """
    close = data["close"].values
    index = data.index
    n = len(close)
    result = pd.Series(False, index=index)

    if n < 2 * min_leg_len + 1:
        return result

    order = min_leg_len
    local_min_idx = argrelextrema(close, np.less, order=order)[0]

    mins_arr = local_min_idx
    left_idx = mins_arr - min_leg_len
    right_idx = mins_arr + min_leg_len

    valid = (left_idx >= 0) & (right_idx < n)
    if not valid.any():
        return result

    valid_mins = mins_arr[valid]
    valid_left = left_idx[valid]
    valid_right = right_idx[valid]

    left_close = close[valid_left]
    right_close = close[valid_right]
    deviation = np.abs(right_close - left_close) / np.maximum(left_close, 1e-10)

    matched = deviation <= tolerance
    for ri in valid_right[matched]:
        if ri < n:
            result.iloc[ri] = True

    return result
