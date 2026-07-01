"""agent team 编排：单股 / 批量分析。"""

from __future__ import annotations

import math

import pandas as pd

from alphapulse.agent_team.agents import (
    data_agent, factor_agent, pattern_agent, sector_agent)
from alphapulse.agent_team.portfolio import portfolio_agent
from alphapulse.agent_team.contract import TeamVerdict, SIGNAL_NEUTRAL


def analyze_stock(df: pd.DataFrame | None, symbol: str, name: str, ctx) -> TeamVerdict:
    """单股多角色分析 → TeamVerdict。数据不健康则直接返回观望。"""
    dop = data_agent(df)
    if dop.signal != SIGNAL_NEUTRAL:                  # 不健康
        return TeamVerdict(symbol, name, math.nan, "观望", [dop], dop.reasoning, ok=False)

    fop = factor_agent(df)
    pop = pattern_agent(df)
    sop = sector_agent(symbol, ctx)
    port = portfolio_agent([fop, pop, sop])

    reasoning = " | ".join(op.reasoning for op in (fop, pop, sop))
    return TeamVerdict(symbol, name, port.confidence, port.evidence["rating"],
                       [dop, fop, pop, sop, port], reasoning, ok=True)


def analyze_batch(items, ctx) -> list[TeamVerdict]:
    """items: 可迭代 (symbol, name, df)。共享 ctx 只建一次（见 context.build_context）。"""
    out = []
    for symbol, name, df in items:
        try:
            out.append(analyze_stock(df, symbol, name, ctx))
        except Exception as e:                        # 单股失败不拖垮批量
            out.append(TeamVerdict(symbol, name, math.nan, "观望", [],
                                   f"分析异常: {e}", ok=False))
    return out
