#!/usr/bin/env python3
"""agent 决策对账 — 决策日志 vs 其后实际行情（阶段三闭环第二步）。

对 reports/agent_decisions.jsonl 里每条决策，用本地日线算 决策数据日 之后的
1/3/5 日收益，统计：
- 按评级桶（Buy/增持/持有/减持/Sell）：胜率 + 均值
- 按角色方向（factor/pattern/sector/referee 各自 bullish vs 其余）：方向命中率
- 有仓位建议的组合（position_pct>0）：加权表现

追加到 daily_auto_report.md；由 eod_pipeline 每日收盘后自动跑（非关键步）。

用法：python scripts/review_agent_decisions.py
"""

import logging
import sys
from datetime import date as _date
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.agent_team.decision_log import load_decisions  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("review_agent")
REPORT = PROJECT_ROOT / "daily_auto_report.md"

AGENTS = ["factor", "pattern", "sector", "referee"]


def _fwd_returns(symbol: str, trade_date: str) -> dict | None:
    """决策数据日收盘 → 之后1/3/5交易日收益。数据不足返回 None。"""
    csv = Path(DATA_DIR) / f"{symbol}.csv"
    if not csv.exists():
        return None
    try:
        df = pd.read_csv(csv, usecols=["date", "close"])
    except Exception:
        return None
    dates = df["date"].astype(str).tolist()
    if trade_date not in dates:
        return None
    i = dates.index(trade_date)
    c0 = float(df["close"].iloc[i])
    out = {}
    for n in (1, 3, 5):
        if i + n < len(df):
            out[f"fwd{n}"] = float(df["close"].iloc[i + n]) / c0 - 1.0
    return out or None


def main() -> int:
    dec = load_decisions()
    if dec.empty:
        logger.info("决策日志为空，跳过")
        return 0

    rows = []
    for _, r in dec.iterrows():
        fwd = _fwd_returns(str(r["symbol"]).zfill(6), str(r["trade_date"]))
        if fwd:
            rows.append({**r.to_dict(), **fwd})
    df = pd.DataFrame(rows)
    if df.empty or "fwd1" not in df.columns:
        logger.info(f"决策 {len(dec)} 条，均未到可对账日（次日行情未出）")
        return 0
    logger.info(f"决策 {len(dec)} 条，可对账 {len(df)} 条")

    today = _date.today().isoformat()
    lines = [f"\n## Agent决策对账 {today}",
             f"累计决策 {len(dec)} 条 · 可对账 {len(df)} 条（有次日行情）\n",
             "| 评级 | n | 1日胜率 | 3日胜率/均值 | 5日胜率/均值 |", "|---|---|---|---|---|"]

    def _s(sub, col):
        s = sub[col].dropna()
        if s.empty:
            return "—"
        return f"{(s > 0).mean()*100:.0f}%/{s.mean()*100:+.2f}%"

    for rating, g in df.groupby("rating"):
        f1 = g["fwd1"].dropna()
        c1 = f"{(f1 > 0).mean()*100:.0f}%" if len(f1) else "—"
        c3 = _s(g, "fwd3") if "fwd3" in g.columns else "—"
        c5 = _s(g, "fwd5") if "fwd5" in g.columns else "—"
        lines.append(f"| {rating} | {len(g)} | {c1} | {c3} | {c5} |")

    lines.append("\n**各角色方向命中率**（bullish 决策的 3日正收益率）")
    for a in AGENTS:
        col = f"{a}_signal"
        if col not in df.columns:
            continue
        bull = df[(df[col] == "bullish") & df.get("fwd3", pd.Series()).notna()]
        if len(bull) >= 3:
            hit = (bull["fwd3"] > 0).mean()
            lines.append(f"- {a}: {hit*100:.0f}%（n={len(bull)}）")

    pos = df[(df["position_pct"] > 0) & df.get("fwd5", pd.Series()).notna()]
    if len(pos):
        w = pos["position_pct"] / pos["position_pct"].sum()
        lines.append(f"\n仓位组合（{len(pos)}条）：5日加权收益 "
                     f"{float((pos['fwd5'] * w).sum())*100:+.2f}% · "
                     f"等权 {pos['fwd5'].mean()*100:+.2f}%")

    with REPORT.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
