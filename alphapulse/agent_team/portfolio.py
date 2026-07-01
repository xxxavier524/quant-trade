"""组合经理聚合角色（P0 确定性规则加权）。

team_score = 50 + 50 * Σ(权重 · 带方向置信度/100)，映射到 0-100 → 5 档评级。
数据健康守门由 core 前置处理（此处只聚合 factor/pattern/sector）。
阶段二再替换为贝叶斯置信度融合 + DeepSeek 仲裁。
"""

from __future__ import annotations

from alphapulse.agent_team.contract import (
    StockOpinion, score_to_rating, SIGNAL_BULL, SIGNAL_BEAR, SIGNAL_NEUTRAL)

WEIGHTS = {"factor": 0.40, "pattern": 0.35, "sector": 0.25}


def portfolio_agent(opinions: list[StockOpinion]) -> StockOpinion:
    """聚合 factor/pattern/sector 观点 → 团队分 + 评级。"""
    by = {op.agent: op for op in opinions}
    num = 0.0
    den = 0.0
    for agent, w in WEIGHTS.items():
        op = by.get(agent)
        if op is None:
            continue
        num += w * (op.signed() / 100.0)
        den += w
    agg = (num / den) if den else 0.0                 # ∈ [-1, 1]
    score = round(max(0.0, min(100.0, 50.0 + 50.0 * agg)), 1)
    rating = score_to_rating(score)

    if agg > 0.05:
        signal = SIGNAL_BULL
    elif agg < -0.05:
        signal = SIGNAL_BEAR
    else:
        signal = SIGNAL_NEUTRAL

    ev = {"score": score, "rating": rating, "weights": dict(WEIGHTS)}
    return StockOpinion("portfolio", signal, score, ev, f"团队分{score:.0f}→{rating}")
