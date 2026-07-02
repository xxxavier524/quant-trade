"""RiskAgent — A股硬约束仓位建议（阶段二，确定性规则）。

规则（CLAUDE.md 约束 + HKUDS arXiv:2512.10971 结论）：
- 只有 Buy/增持 给仓位：单票上限 20% × 评级系数（Buy 1.0 / 增持 0.6）
- 流通市值 < 10 亿 → 仓位 ×0.5（低流动性折减）
- 大盘偏空 → 全体 ×0.5
- 组合最多 5 只：按团队分取前 5，其余高分股标"候补"
"""

from __future__ import annotations

from alphapulse.agent_team.contract import (
    StockOpinion, TeamVerdict, SIGNAL_BULL, SIGNAL_BEAR, SIGNAL_NEUTRAL)

MAX_SINGLE_PCT = 20.0
RATING_COEF = {"Buy": 1.0, "增持": 0.6}
SMALL_CAP_YI = 10.0
SMALL_CAP_DISCOUNT = 0.5
MACRO_BEAR_DISCOUNT = 0.5
MAX_POSITIONS = 5


def _position_for(verdict: TeamVerdict, macro_level: str) -> tuple[float, list[str]]:
    """单票建议仓位% + 折减说明。评级无仓位资格返回 (0, [...])。"""
    coef = RATING_COEF.get(verdict.rating)
    if coef is None:
        return 0.0, [f"评级{verdict.rating}不建仓"]
    pct = MAX_SINGLE_PCT * coef
    notes = [f"{verdict.rating}基础{pct:.0f}%"]
    mv = verdict.meta.get("float_mv_yi")
    if mv is not None and mv < SMALL_CAP_YI:
        pct *= SMALL_CAP_DISCOUNT
        notes.append(f"流通市值{mv:.1f}亿<10亿×{SMALL_CAP_DISCOUNT}")
    if "空" in str(macro_level):
        pct *= MACRO_BEAR_DISCOUNT
        notes.append(f"大盘{macro_level}×{MACRO_BEAR_DISCOUNT}")
    return round(pct, 1), notes


def apply_risk(verdicts: list[TeamVerdict], macro_level: str,
               max_positions: int = MAX_POSITIONS) -> None:
    """就地为每个 verdict 追加 risk opinion 并写 meta['position_pct']。

    仓位资格 = Buy/增持；按团队分排序，前 max_positions 名给仓位，其余标候补。
    """
    eligible = sorted([v for v in verdicts if v.ok and v.rating in RATING_COEF],
                      key=lambda v: v.score, reverse=True)
    slots = {v.symbol: i + 1 for i, v in enumerate(eligible)}

    for v in verdicts:
        if not v.ok:
            continue
        pct, notes = _position_for(v, macro_level)
        slot = slots.get(v.symbol)
        standby = slot is not None and slot > max_positions
        if standby:
            final_pct = 0.0
            label = f"候补(第{slot}名,组合限{max_positions}只)"
            signal = SIGNAL_NEUTRAL
        elif pct > 0:
            final_pct = pct
            label = f"建议仓位{pct:.1f}%"
            signal = SIGNAL_BULL
        else:
            final_pct = 0.0
            label = notes[0]
            signal = SIGNAL_BEAR if v.rating in ("减持", "Sell") else SIGNAL_NEUTRAL

        v.meta["position_pct"] = final_pct
        ev = {"position_pct": final_pct, "slot": slot, "standby": standby,
              "float_mv_yi": v.meta.get("float_mv_yi"), "notes": notes}
        v.opinions.append(StockOpinion(
            "risk", signal, final_pct / MAX_SINGLE_PCT * 100 if final_pct else 0.0,
            ev, label + ("" if len(notes) < 2 else "(" + "、".join(notes[1:]) + ")")))
