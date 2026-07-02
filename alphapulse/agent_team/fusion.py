"""贝叶斯置信度融合（阶段二）。

来源：TrustTrade（arXiv:2603.22567，见 09 研报 §4.3）——
量化置信度 c1（P0 team_score/100）与 LLM 仲裁置信度 c2 的贝叶斯合并：
- 方向一致：c = c1·c2 / (c1·c2 + (1−c1)·(1−c2))   （互相强化，c > max(c1,c2) 当双方>0.5）
- 方向分歧：c = c1·(1−c2) / (c1·(1−c2) + (1−c1)·c2) （互相削弱）

c2=0.5（LLM 中立）时两式均退化为 c=c1 —— 中立仲裁不改变量化结论。
"""

from __future__ import annotations

_EPS = 0.01  # 防 0/1 退化（置信度 100% 会让贝叶斯不可逆转）


def bayes_fuse(c1: float, c2: float, agree: bool) -> float:
    """融合两个 [0,1] 置信度。agree=方向是否一致。返回 [0,1]。"""
    c1 = min(max(float(c1), _EPS), 1.0 - _EPS)
    c2 = min(max(float(c2), _EPS), 1.0 - _EPS)
    if agree:
        num = c1 * c2
        den = num + (1.0 - c1) * (1.0 - c2)
    else:
        num = c1 * (1.0 - c2)
        den = num + (1.0 - c1) * c2
    return num / den


def fuse_team_score(team_score: float, referee_signal: str,
                    referee_confidence: float) -> float:
    """P0 团队分(0-100) × 仲裁观点 → 融合团队分(0-100)。

    方向判定：team_score≥50 视为量化偏多。仲裁 bullish/bearish 与其比对；
    neutral 视为 c2=0.5（融合恒等，不改变量化结论）。
    """
    quant_bull = team_score >= 50.0
    if referee_signal == "neutral":
        c2, agree = 0.5, True
    else:
        ref_bull = referee_signal == "bullish"
        agree = (ref_bull == quant_bull)
        c2 = min(max(referee_confidence / 100.0, 0.0), 1.0)

    c1 = min(max(team_score / 100.0, 0.0), 1.0)
    # 以"偏多概率"为坐标融合：量化偏空时把 c1 翻到偏空概率再融合、再翻回
    if quant_bull:
        fused = bayes_fuse(c1, c2, agree)
    else:
        fused = 1.0 - bayes_fuse(1.0 - c1, c2, agree)
    return round(fused * 100.0, 1)
