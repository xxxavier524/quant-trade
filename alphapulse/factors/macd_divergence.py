"""MACD 面积背驰因子（路线图#7，chan.py divergence_rate 本地化）。

把 DD 顶背离从经验判断变为可回测参数：价格创新高，但该上涨段的 MACD 红柱面积
< 前一上涨段面积 × divergence_rate → 顶背离卖点（DD）。

算法（红柱分段，全因果）：
- MACD hist=2·(dif−dea)（复用 macd_bull_dead.compute_macd，12/26/9）；红柱=hist>0。
- 连续 hist>0 切成红柱段，每段记 area=Σhist、price_peak=段内 high 最大值。
- 段在 hist 由正转非正的**死叉日**完结（此刻该段完全已知）；与上一完结段比：
  signal = (price_peak_now > price_peak_prev) AND (area_now/area_prev < divergence_rate)
  → 死叉日触发。

输出 compute(df, divergence_rate=0.9) -> Series[bool]（背驰死叉日为 True）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphapulse.factors.macd_bull_dead import compute_macd


def _red_segments(hist: np.ndarray, high: np.ndarray):
    """连续 hist>0 的红柱段 → 列表 [(area, price_peak, dead_cross_idx)]。

    dead_cross_idx = 段结束后首个 hist≤0 的日索引（=卖点候选日）；段以数据末尾
    结束时无死叉日（None，不产生信号，因未来未知）。
    """
    n = len(hist)
    red = hist > 0
    segs = []
    i = 0
    while i < n:
        if not red[i]:
            i += 1
            continue
        j = i
        area = 0.0
        peak = -np.inf
        while j < n and red[j]:
            area += hist[j]
            if high[j] > peak:
                peak = high[j]
            j += 1
        # 段 = [i, j-1]；死叉日 = j（若存在，即 hist[j]≤0）
        dead = j if j < n else None
        segs.append((area, peak, dead))
        i = j
    return segs


def compute(data: pd.DataFrame, divergence_rate: float = 0.9,
            fast: int = 12, slow: int = 26, signal: int = 9,
            min_area: float = 1e-9) -> pd.Series:
    """MACD 面积背驰（顶背离）死叉日信号。

    Args:
        data: 含 close/high
        divergence_rate: area_now/area_prev < 此值 且 价创新高 → 背驰（默认0.9）
        min_area: 前段面积下限（避免除以≈0 的噪声段）

    Returns:
        pd.Series[bool]，背驰死叉日为 True
    """
    close = data["close"].astype(float)
    high = data["high"].to_numpy(dtype=float)
    _, _, hist = compute_macd(close, fast, slow, signal)
    hist = hist.to_numpy(dtype=float)

    out = np.zeros(len(data), dtype=bool)
    segs = _red_segments(hist, high)
    for k in range(1, len(segs)):
        area_prev, peak_prev, _ = segs[k - 1]
        area_now, peak_now, dead_now = segs[k]
        if dead_now is None or area_prev < min_area:
            continue
        if peak_now > peak_prev and area_now / area_prev < divergence_rate:
            out[dead_now] = True
    return pd.Series(out, index=data.index)


def compute_detail(data: pd.DataFrame, divergence_rate: float = 0.9,
                   fast: int = 12, slow: int = 26, signal: int = 9,
                   **_) -> pd.DataFrame:
    """明细：在每个死叉日给出 area_now/area_prev/背驰比/价新高标记。"""
    close = data["close"].astype(float)
    high = data["high"].to_numpy(dtype=float)
    _, _, hist = compute_macd(close, fast, slow, signal)
    hist = hist.to_numpy(dtype=float)

    n = len(data)
    area_now = np.full(n, np.nan)
    area_prev = np.full(n, np.nan)
    ratio = np.full(n, np.nan)
    higher_high = np.zeros(n, dtype=bool)
    segs = _red_segments(hist, high)
    for k in range(1, len(segs)):
        ap, pp, _ = segs[k - 1]
        an, pn, dead = segs[k]
        if dead is None:
            continue
        area_now[dead] = an
        area_prev[dead] = ap
        ratio[dead] = an / ap if ap > 0 else np.nan
        higher_high[dead] = pn > pp
    return pd.DataFrame({
        "area_now": np.round(area_now, 4),
        "area_prev": np.round(area_prev, 4),
        "div_ratio": np.round(ratio, 4),
        "higher_high": higher_high,
        "signal": compute(data, divergence_rate, fast, slow, signal),
    }, index=data.index)
