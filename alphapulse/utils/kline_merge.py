"""K线包含关系合并预处理（路线图#10，缠论合并去毛刺）。

若相邻两根K线有包含关系（一根[high,low]完全含另一根），按当前方向合并：
- 向上：取"高高"（new_high=max, new_low=max）
- 向下：取"低低"（new_high=min, new_low=min）
消除横盘毛刺，让长下影/N型转折点在合并后序列上更稳定。

因果：单次前向扫描，第t根只依赖≤t的原始K线；历史合并段被非包含K线终结后固定。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def merge_klines(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """缠论包含合并。

    Returns:
        (merged_df, orig_to_merged)
        merged_df: 列 open/high/low/close/volume/date/orig_start/orig_end
        orig_to_merged: 长度=len(df) 的数组，原始行 i → 其所属合并行下标
    """
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    vol = df["volume"].to_numpy(dtype=float)
    dates = df["date"].astype(str).to_numpy() if "date" in df.columns \
        else np.array([str(x) for x in df.index])

    orig_to_merged = np.zeros(n, dtype=int)
    if n == 0:
        return (pd.DataFrame(columns=["open", "high", "low", "close", "volume",
                                      "date", "orig_start", "orig_end"]),
                orig_to_merged)

    # 合并段：每段记 mh/ml(合并高低)、start/end(原始下标)、vol累计
    m_high = [high[0]]
    m_low = [low[0]]
    m_start = [0]
    m_end = [0]
    m_vol = [vol[0]]
    direction = 1   # 初始向上（首个非包含关系会立即校正）

    for i in range(1, n):
        ph, pl = m_high[-1], m_low[-1]
        ch, cl = high[i], low[i]
        contains = (ch <= ph and cl >= pl) or (ch >= ph and cl <= pl)
        if contains:
            if direction >= 0:                      # 向上取高高
                m_high[-1] = max(ph, ch)
                m_low[-1] = max(pl, cl)
            else:                                    # 向下取低低
                m_high[-1] = min(ph, ch)
                m_low[-1] = min(pl, cl)
            m_end[-1] = i
            m_vol[-1] += vol[i]
            orig_to_merged[i] = len(m_high) - 1
        else:
            direction = 1 if ch > ph else -1        # 无包含 → 定方向
            m_high.append(ch); m_low.append(cl)
            m_start.append(i); m_end.append(i); m_vol.append(vol[i])
            orig_to_merged[i] = len(m_high) - 1

    starts = np.array(m_start)
    ends = np.array(m_end)
    merged = pd.DataFrame({
        "open": open_[starts],           # 合并段起始开盘
        "high": np.array(m_high),
        "low": np.array(m_low),
        "close": close[ends],            # 合并段末尾收盘
        "volume": np.array(m_vol),
        "date": dates[ends],             # 合并段以末尾日为可交易日（因果）
        "orig_start": starts,
        "orig_end": ends,
    })
    return merged, orig_to_merged


def map_merged_signal_to_original(merged_sig: np.ndarray,
                                  merged_df: pd.DataFrame,
                                  n_orig: int) -> np.ndarray:
    """合并K线上的 bool 信号 → 原始日历。

    合并段的信号落在该段的 orig_end 日（=该段完成日，可交易，因果）。
    """
    out = np.zeros(n_orig, dtype=bool)
    ends = merged_df["orig_end"].to_numpy()
    sig = np.asarray(merged_sig, dtype=bool)
    fire_ends = ends[sig]
    out[fire_ends] = True
    return out
