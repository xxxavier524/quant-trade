"""统一信号协议 + 置信度加权聚合（路线图#8）。

把排序层各来源（规则截面分 / LGBM 概率 / 可选 LLM / 可选 UMP 否决）归一为
SignalOpinion（signed∈[-1,1], confidence∈[0,1]），死区阈值抑制近中性弱信号，
置信度加权聚合成单一分数。

定位：显式化现有隐式统一（composite 已把规则+LGBM 用 IC 权重合成 0-100）+ 补"死区"。
不替换生产 composite/stock_ranker，作可选口径 + AB 研究。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SignalOpinion:
    source: str            # 'rule' / 'ml' / 'llm' / 'ump'
    signed: float          # [-1,1] 方向×强度（正=看多）
    confidence: float      # [0,1]


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def aggregate(opinions: list[SignalOpinion], dead_zone: float = 0.0) -> float:
    """置信度加权聚合 → [-1,1]。

    死区：|signed| < dead_zone 的观点视为噪声不计（只让明确观点参与）。
    UMP 否决（source='ump' 且 signed<0）作硬否决：命中则聚合封顶为其 signed。
    """
    veto = min((o.signed for o in opinions
                if o.source == "ump" and o.signed < 0), default=None)

    num = den = 0.0
    for o in opinions:
        if o.source == "ump":
            continue                       # UMP 只做否决，不进加权
        s = _clip(o.signed, -1.0, 1.0)
        c = _clip(o.confidence, 0.0, 1.0)
        if abs(s) < dead_zone:
            continue                       # 死区：弱信号清零
        num += c * s
        den += c
    agg = num / den if den > 0 else 0.0
    if veto is not None:
        agg = min(agg, veto)               # 硬否决封顶
    return _clip(agg, -1.0, 1.0)


def to_score_100(agg: float) -> float:
    """[-1,1] → [0,100]（与 composite 0-100 同尺度，便于对比/展示）。"""
    return round((agg + 1.0) * 50.0, 2)


def from_rule_ml(rule_z: float, ml_prob: float | None,
                 rule_conf: float = 1.0, ml_conf: float = 0.7,
                 llm_signed: float | None = None, llm_conf: float = 0.6,
                 ump_veto: bool = False) -> list[SignalOpinion]:
    """把排序层来源映射为 opinions。

    Args:
        rule_z: 规则综合分的截面 zscore（已 winsorize/zscore），tanh 压到 [-1,1]
        ml_prob: GBDT 胜率概率 [0,1]，中心化 2·(p−0.5)
        llm_signed: 可选 LLM 方向×强度 [-1,1]
        ump_veto: 可选 UMP 否决
    """
    import math
    ops = [SignalOpinion("rule", math.tanh(rule_z), rule_conf)]
    if ml_prob is not None:
        ops.append(SignalOpinion("ml", _clip(2.0 * (ml_prob - 0.5), -1, 1), ml_conf))
    if llm_signed is not None:
        ops.append(SignalOpinion("llm", _clip(llm_signed, -1, 1), llm_conf))
    if ump_veto:
        ops.append(SignalOpinion("ump", -1.0, 1.0))
    return ops
