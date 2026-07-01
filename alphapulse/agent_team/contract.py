"""agent team 统一输出契约。

不复用 pipeline/agents.py:AgentResult（那是因子 R&D 流水线用的结构）；
本模块面向"单股投研信号"，采用 signal/confidence/evidence/reasoning 三元组+。
"""

from __future__ import annotations

from dataclasses import dataclass, field

SIGNAL_BULL = "bullish"
SIGNAL_BEAR = "bearish"
SIGNAL_NEUTRAL = "neutral"

# 团队分 → 5 档评级（含下界，降序匹配）
RATING_TIERS = [(75.0, "Buy"), (60.0, "增持"), (45.0, "持有"), (30.0, "减持"), (0.0, "Sell")]


def score_to_rating(score: float) -> str:
    for thr, label in RATING_TIERS:
        if score >= thr:
            return label
    return "Sell"


@dataclass
class StockOpinion:
    """单个角色对某股的观点。"""
    agent: str
    signal: str                       # bullish / bearish / neutral
    confidence: float                 # 0-100
    evidence: dict = field(default_factory=dict)
    reasoning: str = ""

    def signed(self) -> float:
        """带方向的置信度：bullish 正、bearish 负、neutral 0。"""
        if self.signal == SIGNAL_BULL:
            return self.confidence
        if self.signal == SIGNAL_BEAR:
            return -self.confidence
        return 0.0

    def to_dict(self) -> dict:
        return {"agent": self.agent, "signal": self.signal,
                "confidence": round(self.confidence, 1),
                "evidence": self.evidence, "reasoning": self.reasoning}


@dataclass
class TeamVerdict:
    """agent team 对某股的综合裁决。"""
    symbol: str
    name: str
    score: float                      # 0-100（数据不健康时 NaN）
    rating: str                       # Buy/增持/持有/减持/Sell/观望
    opinions: list[StockOpinion] = field(default_factory=list)
    reasoning: str = ""
    ok: bool = True

    def to_row(self) -> dict:
        row = {"symbol": self.symbol, "name": self.name,
               "score": self.score, "rating": self.rating,
               "ok": self.ok, "reasoning": self.reasoning}
        for op in self.opinions:
            row[f"{op.agent}_signal"] = op.signal
            row[f"{op.agent}_conf"] = round(op.confidence, 1)
        return row
