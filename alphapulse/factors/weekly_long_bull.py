"""B1补丁1 · 周线大级别多头排列（55/144/233周线）。

来源：zettaranc B1选股双补丁（2026-02-20，docs/research_journal/12_* P0 #7）：
`MA(C,55)>MA(C,144) AND MA(C,144)>MA(C,233)`（周线）且 55/144 周线趋势向上。
作用：5000票 → 1600票的大级别粗筛，过滤掉走坏的下跌票。

历史不足 233 周（约4.5年）→ False（保守：无大级别多头证据不放行）。
"""

import pandas as pd


def compute(
    data: pd.DataFrame,
    m1: int = 55,
    m2: int = 144,
    m3: int = 233,
    require_rising: bool = True,
) -> pd.Series:
    close = data["close"].astype(float)
    if not isinstance(data.index, pd.DatetimeIndex):
        return pd.Series(False, index=data.index)

    wclose = close.resample("W-FRI").last().dropna()
    ma1 = wclose.rolling(m1).mean()
    ma2 = wclose.rolling(m2).mean()
    ma3 = wclose.rolling(m3).mean()

    bull = (ma1 > ma2) & (ma2 > ma3)
    if require_rising:
        bull &= (ma1 > ma1.shift(1)) & (ma2 > ma2.shift(1))

    # 用上一完整周的状态映射回日线（无未来函数）
    return bull.shift(1).reindex(close.index, method="ffill").fillna(False).astype(bool)
