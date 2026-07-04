"""agent team 编排：单股 / 批量分析（P0 量化 + 阶段二辩论/融合/风控）。"""

from __future__ import annotations

import logging
import math

import pandas as pd

from alphapulse.agent_team.agents import (
    data_agent, factor_agent, pattern_agent, sector_agent)
from alphapulse.agent_team.portfolio import portfolio_agent
from alphapulse.agent_team.contract import (
    TeamVerdict, StockOpinion, score_to_rating, SIGNAL_NEUTRAL)

logger = logging.getLogger("agent_team.core")

DEBATE_MIN_SCORE = 65.0     # 触发多空辩论的最低团队分（控 LLM 成本）


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
    v = TeamVerdict(symbol, name, port.confidence, port.evidence["rating"],
                    [dop, fop, pop, sop, port], reasoning, ok=True)
    if df is not None and "market_cap" in df.columns:
        mv = df["market_cap"].iloc[-1]
        if pd.notna(mv):
            v.meta["float_mv_yi"] = round(float(mv) / 1e8, 1)
    return v


def _apply_debate(v: TeamVerdict, chat_fn=None, persona_chat_fn=None) -> None:
    """人格观点→辩论→贝叶斯融合，就地更新 verdict（失败保持 P0 结论）。"""
    from alphapulse.agent_team.debate import run_debate
    from alphapulse.agent_team.fusion import fuse_team_score
    from alphapulse.agent_team.persona import persona_opinions

    p_ops = persona_opinions(v, chat_fn=persona_chat_fn)
    v.opinions.extend(p_ops)
    extra = [(op.agent, f"[{op.signal} {op.confidence:.0f}] {op.reasoning}")
             for op in p_ops]

    outcome = run_debate(v, chat_fn=chat_fn, extra_views=extra or None)
    if outcome is None:
        return
    p0 = v.score
    fused = fuse_team_score(p0, outcome.signal, outcome.confidence)
    v.opinions.append(StockOpinion(
        "referee", outcome.signal, outcome.confidence,
        {"bull": outcome.bull, "bear": outcome.bear,
         "p0_score": p0, "fused_score": fused},
        outcome.reasoning))
    v.score = fused
    v.rating = score_to_rating(fused)
    v.meta["debated"] = True
    logger.info(f"{v.symbol} 辩论: {outcome.signal}{outcome.confidence:.0f} "
                f"→ 团队分 {p0:.0f}→{fused:.0f}({v.rating})")


def analyze_batch(items, ctx, debate: bool = False,
                  debate_min: float = DEBATE_MIN_SCORE,
                  max_positions: int = 5, chat_fn=None,
                  persona_chat_fn=None) -> list[TeamVerdict]:
    """items: 可迭代 (symbol, name, df)。共享 ctx 只建一次（见 context.build_context）。

    debate=True 时：team_score ≥ debate_min 的标的跑 Bull/Bear/仲裁（v4-pro）
    并做贝叶斯融合；随后 RiskAgent 按 A 股硬约束给仓位（最多 max_positions 只）。
    """
    out = []
    for symbol, name, df in items:
        try:
            out.append(analyze_stock(df, symbol, name, ctx))
        except Exception as e:                        # 单股失败不拖垮批量
            out.append(TeamVerdict(symbol, name, math.nan, "观望", [],
                                   f"分析异常: {e}", ok=False))
    if debate:
        for v in out:
            if v.ok and v.score >= debate_min:
                try:
                    _apply_debate(v, chat_fn=chat_fn, persona_chat_fn=persona_chat_fn)
                except Exception as e:
                    logger.warning(f"{v.symbol} 辩论异常(保持P0): {e}")

    from alphapulse.agent_team.risk import apply_risk
    apply_risk(out, ctx.macro_level, max_positions)
    return out
