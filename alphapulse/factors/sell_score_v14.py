"""防卖飞策略 V1.4 — 持仓每日评分（0-5），防止提前清仓错过主升浪。

来源：zettaranc sell-discipline 3.10（docs/research_journal/12_* P0 #4）。

五项各 +1：
1. 收盘涨（close > 昨收）
2. BBI 没破（close > BBI）
3. 不是放量阴线（放量=相对最近，用 vol > MA5(vol)*fangliang_mult 近似）
4. 趋势还向上（白线 EMA(EMA(C,10),10) 上行）
5. J 没死叉（死叉是状态：J<K 且 J<D 即算，不是下穿瞬间）

判读：4-5 持有 / 3 减半 / <3 准备离场。
**重要**：本评分只用于持仓管理，不能作为开新仓依据（V1.4 第4条）。
"""

import pandas as pd

from alphapulse.factors.bbi import compute_bbi
from alphapulse.factors.kdj_j_low import compute_kdj
from alphapulse.factors.zhixing_trend import compute_short_trend


def compute(
    data: pd.DataFrame,
    fangliang_mult: float = 1.2,
) -> pd.Series:
    """返回 0-5 的整数评分序列。"""
    return compute_detail(data, fangliang_mult=fangliang_mult)["score"]


def compute_detail(
    data: pd.DataFrame,
    fangliang_mult: float = 1.2,
) -> pd.DataFrame:
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)

    item1 = close > close.shift(1)                                # 收盘涨
    item2 = close > compute_bbi(close)                            # BBI 没破

    is_yin = close < open_
    is_fangliang = volume > volume.rolling(5).mean() * fangliang_mult
    item3 = ~(is_yin & is_fangliang)                              # 不是放量阴线

    white = compute_short_trend(close)
    item4 = white > white.shift(1)                                # 趋势向上

    k, d, j = compute_kdj(high, low, close)
    item5 = ~((j < k) & (j < d))                                  # J 非死叉状态

    items = pd.DataFrame({
        "close_up": item1, "bbi_hold": item2, "no_fangliang_yin": item3,
        "trend_up": item4, "j_alive": item5,
    }).fillna(False)
    items["score"] = items.sum(axis=1).astype(int)
    items["action"] = pd.cut(items["score"], bins=[-1, 2, 3, 5],
                             labels=["准备离场", "减半", "持有"])
    return items
