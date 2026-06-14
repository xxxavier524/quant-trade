"""周线M5上穿M14 + 日/周线均线多头排列（B1加强因子，用户需求 2026-06-11）。

- 周线：日线按周五重采样收盘 → MA5/MA14；
  M5 > M14 = 周线多头；近 recent_weeks 周内发生上穿 = 最强加分
- 日线：MA5 > MA10 > MA20 = 日线多头排列

compute 返回布尔（周线M5>M14 且 日线多头排列）；
compute_detail 返回各状态明细（GUI选股依据用）。
"""

import pandas as pd


def _to_dates(data: pd.DataFrame) -> pd.Series:
    """稳健解析日期：兼容 '2026-05-22' 与 '2026-05-22 00:00:00' 混合格式。"""
    if "date" in data.columns:
        # 切到前10位（YYYY-MM-DD），规避单只CSV混入时间戳导致 to_datetime 推断format失败
        return pd.to_datetime(data["date"].astype(str).str.slice(0, 10),
                              format="%Y-%m-%d", errors="coerce")
    # 无 date 列：按原索引解析（DatetimeIndex 直接用，整数索引退回 epoch 行为，不崩溃）
    idx = data.index
    if isinstance(idx, pd.DatetimeIndex):
        return pd.Series(idx)
    return pd.to_datetime(pd.Series(idx), errors="coerce")


def weekly_close(data: pd.DataFrame) -> pd.Series:
    """日线 → 周线收盘（自然周最后交易日）。"""
    dates = _to_dates(data)
    close = data["close"].astype(float)
    s = pd.Series(close.values, index=dates).dropna()
    return s.resample("W-FRI").last().dropna()


def compute_weekly_state(data: pd.DataFrame, fast: int = 5, slow: int = 14,
                         recent_weeks: int = 4) -> dict:
    """周线 M5/M14 状态：above（当前M5>M14）、crossed_recently（近N周上穿）。"""
    wc = weekly_close(data)
    if len(wc) < slow + 2:
        return {"above": False, "crossed_recently": False, "m5": None, "m14": None}
    m_fast = wc.rolling(fast).mean()
    m_slow = wc.rolling(slow).mean()
    above = bool(m_fast.iloc[-1] > m_slow.iloc[-1])
    cross_up = (m_fast.shift(1) <= m_slow.shift(1)) & (m_fast > m_slow)
    crossed = bool(cross_up.tail(recent_weeks).any())
    return {"above": above, "crossed_recently": crossed,
            "m5": round(float(m_fast.iloc[-1]), 3),
            "m14": round(float(m_slow.iloc[-1]), 3)}


def daily_ma_bull(data: pd.DataFrame) -> pd.Series:
    """日线多头排列：MA5 > MA10 > MA20（逐日布尔序列）。"""
    c = data["close"].astype(float)
    ma5, ma10, ma20 = c.rolling(5).mean(), c.rolling(10).mean(), c.rolling(20).mean()
    return ((ma5 > ma10) & (ma10 > ma20)).fillna(False)


def compute(data: pd.DataFrame, fast: int = 5, slow: int = 14,
            recent_weeks: int = 4) -> pd.Series:
    """布尔因子：周线M5>M14 且 日线多头排列（最后一日状态广播为序列尾值）。

    注意：周线状态只对最后一日有意义，历史回放请用 compute_weekly_series。
    """
    daily = daily_ma_bull(data)
    wk = compute_weekly_state(data, fast, slow, recent_weeks)
    result = daily.copy()
    result.iloc[:] = False
    if len(result):
        result.iloc[-1] = bool(daily.iloc[-1] and wk["above"])
    return result


def compute_weekly_series(data: pd.DataFrame, fast: int = 5, slow: int = 14) -> pd.DataFrame:
    """逐日对齐的周线M5/M14序列（用前一周已完成的周线值，无未来泄漏）。

    用于胜率验证/ML：weekly_above 列 = 截至该日上一完整周 M5>M14。
    """
    dates = _to_dates(data)
    wc = weekly_close(data)
    m_fast = wc.rolling(fast).mean()
    m_slow = wc.rolling(slow).mean()
    weekly_above = (m_fast > m_slow)
    cross_up = (m_fast.shift(1) <= m_slow.shift(1)) & (m_fast > m_slow)
    # 对齐到日线：取上一周五（已完成周）的状态，shift(1)避免使用本周未完成数据
    above_daily = weekly_above.shift(1).reindex(dates, method="ffill").fillna(False)
    cross_daily = cross_up.shift(1).reindex(dates, method="ffill").fillna(False)
    return pd.DataFrame({"weekly_above": above_daily.values,
                         "weekly_cross": cross_daily.values}, index=data.index)


def compute_detail(data: pd.DataFrame, **params) -> dict:
    """选股依据明细（GUI展示）。"""
    wk = compute_weekly_state(data)
    daily = bool(daily_ma_bull(data).iloc[-1]) if len(data) else False
    c = data["close"].astype(float)
    mas = {f"MA{n}": round(float(c.rolling(n).mean().iloc[-1]), 2)
           for n in (5, 10, 20, 60) if len(c) >= n}
    return {
        "daily_ma_bull": daily,
        "daily_mas": mas,
        "weekly_m5": wk["m5"],
        "weekly_m14": wk["m14"],
        "weekly_above": wk["above"],
        "weekly_crossed_recently": wk["crossed_recently"],
    }
