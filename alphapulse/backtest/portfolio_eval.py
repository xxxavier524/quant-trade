"""把"逐笔交易列表"折算成"组合级绩效"（2026-07-28，P2/C7）。

为什么需要它：auto_retune / walk_forward 之前的目标函数是**逐信号等权**指标
（每持有日净收益、5日内触及+5%的命中率）。这类指标不含资金约束——不限并发持仓、
不限单票仓位、不考虑同一时间信号过多只能挑几只——因此与真实账户收益脱节：
诚实组合回测是 -12.4% 年化时，逐信号命中率看起来仍有 24%。优化这种指标不可能
达成"年化10%"的目标，因为它优化的根本不是账户收益。

本模块按 CLAUDE.md 的生产约束（单票≤20%、最多5只并发）把逐笔交易回放成资金曲线。

口径与已知局限（诚实标注）：
- 交易的 net_return 已含滑点与手续费（playbook_engine 计入 ROUND_TRIP_COST）。
- 仓位按"入场时点权益 × max_single_pct"与可用现金取小；满仓/满槽时信号被跳过
  （skipped 会返回，用于判断信号是否过密）。
- **最大回撤是"已平仓权益"口径**：持仓期间只按成本计价、不做每日盯市，
  因此**低估**持仓中的浮亏回撤。用于横向比较参数足够，不可当作真实回撤上限。
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

MAX_POSITIONS = 5
MAX_SINGLE_PCT = 0.20
INITIAL_CAPITAL = 1_000_000.0


def evaluate_portfolio(trades: list[dict],
                       max_positions: int = MAX_POSITIONS,
                       max_single_pct: float = MAX_SINGLE_PCT,
                       initial_capital: float = INITIAL_CAPITAL) -> dict:
    """逐笔交易 → 组合级绩效。

    Args:
        trades: 每笔含 entry_date / exit_date / net_return（净收益率，已扣成本）
    Returns:
        {annual_return, max_drawdown, calmar, n_taken, n_skipped, final_equity, years}
        annual_return/max_drawdown 为小数（0.10 = 10%）。
    """
    empty = {"annual_return": 0.0, "max_drawdown": 0.0, "calmar": 0.0,
             "n_taken": 0, "n_skipped": 0, "final_equity": initial_capital, "years": 0.0}
    if not trades:
        return empty

    rows = []
    for t in trades:
        try:
            ed, xd = pd.Timestamp(t["entry_date"]), pd.Timestamp(t["exit_date"])
            r = float(t["net_return"])
        except (KeyError, TypeError, ValueError):
            continue
        if pd.isna(ed) or pd.isna(xd) or xd < ed or r != r:
            continue
        rows.append((ed, xd, r))
    if not rows:
        return empty

    rows.sort(key=lambda x: x[0])
    entries_by_date: dict = defaultdict(list)
    for ed, xd, r in rows:
        entries_by_date[ed].append((xd, r))

    timeline = sorted({d for ed, xd, _ in rows for d in (ed, xd)})
    cash = initial_capital
    open_pos: list[tuple] = []          # (exit_date, cost, net_return)
    curve: list[tuple] = []
    n_taken = n_skipped = 0

    for day in timeline:
        # 1) 先结算当日及之前到期的持仓（先回款，资金可复用）
        still = []
        for xd, cost, r in open_pos:
            if xd <= day:
                cash += cost * (1.0 + r)
            else:
                still.append((xd, cost, r))
        open_pos = still

        # 2) 再开当日的新仓（受并发数与单票上限约束）
        for xd, r in entries_by_date.get(day, []):
            if len(open_pos) >= max_positions:
                n_skipped += 1
                continue
            equity_now = cash + sum(c for _, c, _ in open_pos)
            size = min(max_single_pct * equity_now, cash)
            if size <= 0:
                n_skipped += 1
                continue
            cash -= size
            open_pos.append((xd, size, r))
            n_taken += 1

        curve.append((day, cash + sum(c for _, c, _ in open_pos)))

    # 收尾：清算剩余持仓
    for xd, cost, r in open_pos:
        cash += cost * (1.0 + r)
    final_equity = cash
    if curve:
        curve[-1] = (curve[-1][0], final_equity)

    span_days = max((timeline[-1] - timeline[0]).days, 1)
    years = span_days / 365.25
    total = final_equity / initial_capital
    annual = total ** (1.0 / years) - 1.0 if years > 0 and total > 0 else 0.0

    peak = -float("inf")
    max_dd = 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, eq / peak - 1.0)

    return {"annual_return": round(annual, 4),
            "max_drawdown": round(max_dd, 4),
            "calmar": round(annual / abs(max_dd), 3) if max_dd < 0 else 0.0,
            "n_taken": n_taken, "n_skipped": n_skipped,
            "final_equity": round(final_equity, 2), "years": round(years, 2)}
