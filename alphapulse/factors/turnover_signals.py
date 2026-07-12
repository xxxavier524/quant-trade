"""换手率信号 — B1补丁2（累计换手<38%）与高位换手出货。

来源：zettaranc（docs/research_journal/12_* P0 #8/#9）：
- B1 补丁2（2026-03-15）：前三根中大阳线累计换手率 < 38%。
  「换手率高=筹码已发散=主力跑了。累计换手38是个魔法数字」
  参照案例：华纳 36.12 / 小微 18.31 / 航发 29.58
- 高位换手出货：4 根 K 线内累计换手 160-200% → 退出信号

数据要求：`turnover` 列（换手率%）。缺失时按中性处理（补丁通过 / 出货不触发）。
"""

import numpy as np
import pandas as pd


def _turnover(data: pd.DataFrame) -> pd.Series | None:
    for col in ("turnover", "turn"):
        if col in data.columns:
            s = pd.to_numeric(data[col], errors="coerce")
            if s.notna().sum() > 0:
                return s
    return None


def compute_b1_turnover_patch(
    data: pd.DataFrame,
    max_cum_turnover: float = 38.0,
    yang_pct: float = 4.0,
    lookback: int = 60,
) -> pd.Series:
    """B1补丁2：最近 3 根中大阳线（涨幅≥yang_pct%，lookback 内）累计换手 < max_cum_turnover → True=通过。

    不足 3 根中大阳线 → 通过（无筹码发散证据）；无 turnover 数据 → 全通过。
    """
    close = data["close"].astype(float)
    turn = _turnover(data)
    if turn is None:
        return pd.Series(True, index=data.index)

    open_ = data["open"].astype(float)
    pct = close.pct_change() * 100
    is_big_yang = ((close > open_) & (pct >= yang_pct)).to_numpy()
    tv = turn.fillna(0).to_numpy()
    n = len(data)

    result = np.ones(n, dtype=bool)
    yang_idx: list[int] = []
    for i in range(n):
        if is_big_yang[i]:
            yang_idx.append(i)
        # 只统计 lookback 窗口内、最近的 3 根
        recent = [k for k in yang_idx[-6:] if i - k < lookback][-3:]
        if len(recent) == 3:
            result[i] = tv[recent].sum() < max_cum_turnover
    return pd.Series(result, index=data.index)


def compute_high_turnover_exit(
    data: pd.DataFrame,
    window: int = 4,
    threshold: float = 160.0,
) -> pd.Series:
    """高位换手出货：window 根K线累计换手 ≥ threshold% → True=退出信号。"""
    turn = _turnover(data)
    if turn is None:
        return pd.Series(False, index=data.index)
    cum = turn.fillna(0).rolling(window).sum()
    return (cum >= threshold).fillna(False).astype(bool)


def compute(data: pd.DataFrame, **params) -> pd.Series:
    """registry 默认入口 = B1补丁2。"""
    return compute_b1_turnover_patch(data, **params)
