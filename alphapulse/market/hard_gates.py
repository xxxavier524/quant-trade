"""大盘硬闸门 — 「择时是门，不是分」。

来源：zettaranc 四层模块第一层（docs/research_journal/12_* 流程对比结论）：
- MACD 零轴多空：上证 DIF<0 = 空头区间，「什么都别做，空仓休息」
- 大盘 S1：上证走出 S1 形态 → 宁可信其有，降仓位/不开新仓

与 market_score（软调节，0-100 连续分）互补：闸门只回答「今天能不能开新仓」。
指数数据缺失时 **fail-open**（放行并注明），不阻塞流水线。
"""

from __future__ import annotations

import logging

from alphapulse.market.market_score import load_index

logger = logging.getLogger("market.hard_gates")

INDEX_CODE = "sh000001"


def macd_zero_axis_gate(end_date: str = "9999-12-31") -> tuple[bool, str]:
    """上证 DIF>0 → (True, 说明)；DIF<0 空头区间 → (False, 说明)。数据缺失放行。"""
    df = load_index(INDEX_CODE, end_date)
    if df.empty or len(df) < 60:
        return True, "零轴门:指数数据不足(放行)"
    close = df["close"].astype(float)
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    v = float(dif.iloc[-1])
    if v > 0:
        return True, f"零轴门:DIF={v:.2f}>0 多头区间"
    return False, f"零轴门:DIF={v:.2f}<0 空头区间(不开新仓)"


def market_s1_gate(end_date: str = "9999-12-31", lookback: int = 5) -> tuple[bool, str]:
    """近 lookback 日上证出现 S1（高位放量阴线）→ (False, 说明)。数据缺失放行。"""
    df = load_index(INDEX_CODE, end_date)
    if df.empty or len(df) < 30:
        return True, "大盘S1门:指数数据不足(放行)"
    try:
        import pandas as pd
        from alphapulse.factors import s1_sell_signal
        idx_df = df.copy()
        idx_df["date"] = pd.to_datetime(idx_df["date"])
        idx_df = idx_df.set_index("date")
        if "open" not in idx_df.columns:
            return True, "大盘S1门:缺open列(放行)"
        s1 = s1_sell_signal.compute(idx_df)
        recent = s1.tail(lookback)
        if (recent > 0).any():
            d = str(recent[recent > 0].index[-1])[:10]
            return False, f"大盘S1门:{d}出现大盘S1(宁可信其有,不开新仓)"
        return True, "大盘S1门:近5日无大盘S1"
    except Exception as e:
        return True, f"大盘S1门:计算异常(放行) {e}"


def evaluate_gates(end_date: str = "9999-12-31") -> tuple[bool, list[str]]:
    """综合评估。返回 (是否放行, 各门说明)。任一门关闭即不放行。"""
    results = [macd_zero_axis_gate(end_date), market_s1_gate(end_date)]
    passed = all(ok for ok, _ in results)
    return passed, [msg for _, msg in results]
