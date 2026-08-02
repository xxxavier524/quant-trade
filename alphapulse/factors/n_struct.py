"""N型结构识别因子。

识别价格走势中的N型结构（上升-回撤-再上升），返回阶段标签：
'A'（起点低点）、'B'（第一波上升）、'C'（回撤）、'D'（第二波突破），其余为NaN。

⚠️ 因果性（v5 2026-08-02）：`compute()` 使用 scipy argrelextrema 判定枢轴，
第 i 根K线是否为枢轴需要前后各 min_leg_len 根K线（即未来数据），
**禁止用于任何实盘/回测信号**（已废弃，仅兼容历史调用）。
新代码一律使用 `compute_causal()`——一切阶段/价格信息按确认时点对齐，无未来函数。
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

    Note:
        非因果（枢轴判定依赖未来K线），仅供历史兼容。新代码用 compute_causal()。
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


def compute_causal(
    data: pd.DataFrame,
    min_leg_len: int = 5,
    retrace_ratio: float = 0.618,
) -> pd.DataFrame:
    """因果版 N 型上下文（v5，禁止未来函数）。

    argrelextrema 判定枢轴需要枢轴点前后各 min_leg_len 根K线，即第 i 根K线
    是否为枢轴要到 i+min_leg_len 才能确认。compute() 把标签/阶段直接标在
    枢轴日，等于在信号日使用了未来数据。本函数把一切信息按"确认时点"对齐：

      - label:  结构成立后公布——C 标签放在 C 确认日（c+order），
                D 标签放在 D 确认日（d+order）。A/B 不单独发标签
                （其价格由 a_price/b_price 承载，且结构要等 C 验证才成立）
      - phase:  第 t 根bar的状态 = 最近一个"确认时点 ≤ t"的结构事件
                  phase 2: C 确认（A-B-C 回撤结构成立）→ 洗盘后恢复期。
                            注意 phase 1（A→B 上升腿）无法实时存在——
                            一段上升腿是不是 N 型结构的起点，要等 C 回撤
                            验证后才可知，故因果版没有 phase 1 时段。
                  phase 3: D 确认（再上升/追高区）
      - a_price / b_price: 最近确认结构的 A/B 点价格；无任何确认时为 NaN

    注意：因为枢轴需要确认窗，"当前正处回调中"在实盘里天生不可知——
    phase 2 只能在回调结束后才出现，这是旧版未来函数被移除后的诚实语义。

    Args:
        data: 日线 OHLCV DataFrame
        min_leg_len: 枢轴确认所需最小腿长（前后各 N 根K线）
        retrace_ratio: 回撤比例阈值（同 compute）

    Returns:
        pd.DataFrame（index 对齐 data）: [phase, a_price, b_price, label]
        - phase: int（0/1/2/3）
        - a_price/b_price: float（最近确认结构的A/B点价格，未确认 NaN）
        - label: object（'A'/'B'/'C'/'D' 出现在枢轴确认日，其余 NaN）
    """
    order = min_leg_len
    n = len(data)
    idx = data.index
    low = data["low"].values
    high = data["high"].values

    label_full = np.full(n, None, dtype=object)
    events = []   # (confirm, phase, a_val, b_val)，登记顺序与 compute() 的遍历一致

    high_peaks, low_troughs = find_pivots(data["high"], min_leg_len)
    # A-B-C 结构需要 2 个谷（A/C）+ 1 个峰（B）；D 峰仅 phase 3 需要，
    # 因此不能像旧 compute() 那样要求 ≥2 个峰（截断序列里 D 可能尚未出现）。
    if len(low_troughs) >= 2 and len(high_peaks) >= 1:
        for a_idx in low_troughs[:-1]:
            a_val = low[a_idx]
            b_candidates = [p for p in high_peaks if p > a_idx]
            if not b_candidates:
                continue
            b_idx = b_candidates[0]
            b_val = high[b_idx]
            ab_range = b_val - a_val
            if ab_range <= 0:
                continue

            c_candidates = [t for t in low_troughs if t > b_idx]
            if not c_candidates:
                continue
            c_idx = c_candidates[0]
            c_val = low[c_idx]
            actual_retrace = (b_val - c_val) / ab_range
            retrace_tolerance = 0.15
            if not (retrace_ratio - retrace_tolerance <= actual_retrace
                    <= retrace_ratio + retrace_tolerance):
                continue

            # ── phase 2：A-B-C 结构在 C 确认日（c_idx+order）才成立 ──
            # 与旧 compute() 的关键差异：旧版把 phase 1/2 标在 B→C 区间内，
            # 等于在回调进行中就用了"未来会确认 C"的信息。因果版把整个
            # 结构推迟到 C 确认后公布，phase 1 因此不会出现在时间线上。
            events.append((c_idx + order, 2, a_val, b_val))
            label_full[c_idx] = "C"

            # ── phase 3：D 突破 B 在 D 确认日（d_idx+order）才成立 ──
            d_candidates = [p for p in high_peaks if p > c_idx]
            if d_candidates:
                d_idx = d_candidates[0]
                d_val = high[d_idx]
                if d_val >= b_val * 0.95:
                    events.append((d_idx + order, 3, a_val, b_val))
                    label_full[d_idx] = "D"

    # ── 阶段状态推进：t 日状态 = 最近一个确认时点 ≤ t 的事件（向量化）──
    phase = np.zeros(n, dtype=int)
    a_price = np.full(n, np.nan)
    b_price = np.full(n, np.nan)
    if events:
        events.sort(key=lambda e: e[0])          # 稳定排序保登记顺序
        confirms = np.array([e[0] for e in events], dtype=int)
        ev_phase = np.array([e[1] for e in events], dtype=int)
        ev_a = np.array([e[2] for e in events], dtype=float)
        ev_b = np.array([e[3] for e in events], dtype=float)
        t_idx = np.arange(n)
        pos = np.searchsorted(confirms, t_idx, side="right") - 1
        valid = pos >= 0
        pos_c = pos.clip(0)
        phase = np.where(valid, ev_phase[pos_c], 0).astype(int)
        a_price = np.where(valid, ev_a[pos_c], np.nan)
        b_price = np.where(valid, ev_b[pos_c], np.nan)

    # ── 标签放在确认日：枢轴 i 的标签在 i+order 才公布 ──
    label = pd.Series(np.nan, index=idx, dtype=object)
    for i, lbl in enumerate(label_full):
        if lbl is not None and i + order < n:
            label.iloc[i + order] = lbl

    return pd.DataFrame({
        "phase": pd.Series(phase, index=idx),
        "a_price": pd.Series(a_price, index=idx),
        "b_price": pd.Series(b_price, index=idx),
        "label": label,
    })
