"""摸顶税 — 净值新高过程中的强制减仓规则（P1 #22）。

来源：zettaranc exit-strategies：「在净值创新高的过程中，把浮盈的 20%~50%
做计提减值作为摸顶税。顶不可预测，只能靠走出来。不要越到后期越金字塔加仓。」
换算规则：若最多接受 max_dd 回撤、单日极端跌幅 unit_drop，
则仓位上限 = max_dd / (n_units × unit_drop)。
"""

from __future__ import annotations


def top_tax_cut(nav_peak_gain: float, tax_rate: float = 0.3) -> float:
    """净值相对本轮起点的浮盈比例 → 建议计提减仓比例（浮盈部分的 tax_rate）。

    例：浮盈 40%、税率 30% → 建议减掉总仓位的约 40%*30% = 12%。
    浮盈 ≤0 → 0。
    """
    return max(0.0, nav_peak_gain) * tax_rate


def max_position_for_drawdown(max_dd: float = 0.05, unit_drop: float = 0.10,
                              n_units: int = 2) -> float:
    """按可承受回撤反推仓位上限。默认：最多受5%回撤、按连续2个跌停(20%)压力测试
    → 仓位 ≤ 0.05/0.20 = 25%。"""
    stress = n_units * unit_drop
    return min(1.0, max_dd / stress) if stress > 0 else 1.0
