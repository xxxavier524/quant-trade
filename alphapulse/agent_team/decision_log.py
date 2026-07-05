"""agent team 决策日志（阶段三闭环第一步）。

每次研判把 TeamVerdict 摘要追加到 reports/agent_decisions.jsonl（一行一条）；
晚间 scripts/review_agent_decisions.py 用其后实际行情对账，统计各角色命中率。
同一 (date, symbol) 重复研判只保留最新一条（读取端去重）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from alphapulse.agent_team.contract import TeamVerdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = PROJECT_ROOT / "reports" / "agent_decisions.jsonl"


def append_decisions(verdicts: list[TeamVerdict], trade_date: str,
                     path: Path | None = None) -> int:
    """把有效裁决追加到决策日志。返回写入条数。trade_date=研判针对的数据日。"""
    path = path or LOG_PATH
    path.parent.mkdir(exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for v in verdicts:
            if not v.ok:
                continue
            rec = {"trade_date": trade_date,
                   "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "symbol": v.symbol, "name": v.name,
                   "score": v.score, "rating": v.rating,
                   "position_pct": v.meta.get("position_pct", 0.0),
                   "debated": bool(v.meta.get("debated"))}
            for op in v.opinions:
                key = op.agent.replace(":", "_")
                rec[f"{key}_signal"] = op.signal
                rec[f"{key}_conf"] = round(op.confidence, 1)
                if op.agent == "pattern":
                    rec["pattern_state"] = op.evidence.get("state", "")
                if op.agent == "referee":
                    rec["p0_score"] = op.evidence.get("p0_score")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def load_decisions(path: Path | None = None) -> pd.DataFrame:
    """读取全部决策，(trade_date, symbol) 去重保留最新。"""
    path = path or LOG_PATH
    if not path.exists():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return (df.sort_values("logged_at")
            .drop_duplicates(["trade_date", "symbol"], keep="last")
            .reset_index(drop=True))
