"""agent team 共享上下文（批量分析只建一次，避免逐股重算）。

- macro_level/macro_score：大盘档位（compute_market_score，读本地 data/index/）
- sector_map / concept_map：股票→行业/概念（读本地 data/meta/*.json）
- sector_scores：行业相对强弱，优先读最新 reports/sectors_*.csv（全市场预算结果），
  取不到再退回空（sector_agent 会回退到大盘分）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = PROJECT_ROOT / "reports"


@dataclass
class TeamContext:
    macro_level: str = "震荡"
    macro_score: float = 50.0
    sector_scores: dict[str, float] = field(default_factory=dict)   # sector -> score
    sector_map: dict[str, str] = field(default_factory=dict)        # symbol -> sector
    concept_map: dict[str, str] = field(default_factory=dict)       # symbol -> "a/b/c"


def _load_sector_scores(reports_dir: Path, date: str | None) -> dict[str, float]:
    try:
        if date:
            f = reports_dir / f"sectors_{date}.csv"
            files = [f] if f.exists() else []
        else:
            files = sorted(reports_dir.glob("sectors_*.csv"))
        if not files:
            return {}
        sdf = pd.read_csv(files[-1])
        return {str(s): float(v) for s, v in zip(sdf["sector"], sdf["score"])}
    except Exception:
        return {}


def build_context(end_date: str = "9999-12-31", date: str | None = None,
                  reports_dir: Path | None = None) -> TeamContext:
    """构建共享上下文。date 指定回放日（用于取对应 sectors_*.csv）。"""
    ctx = TeamContext()
    try:
        from alphapulse.market.market_score import compute_market_score
        m = compute_market_score(end_date=end_date)
        ctx.macro_level = m.get("level", "震荡")
        ctx.macro_score = float(m.get("score", 50.0))
    except Exception:
        pass
    try:
        from alphapulse.market.sector_score import symbol_sector_map, symbol_concept_map
        ctx.sector_map = symbol_sector_map()
        ctx.concept_map = symbol_concept_map()
    except Exception:
        pass
    ctx.sector_scores = _load_sector_scores(reports_dir or REPORTS_DIR, date)
    return ctx
