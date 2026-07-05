#!/usr/bin/env python3
"""agent team CLI — 多角色分工投研（P0 纯量化）。

喂 daily_screener Top-N（或显式 --symbols）→ 每股跑 5 角色 → 结构化操作建议 Markdown。

用法：
    python scripts/run_agent_team.py --top 10
    python scripts/run_agent_team.py --top 10 --debate          # 高分标的加 DeepSeek 多空辩论
    python scripts/run_agent_team.py --symbols 600519 000001 --date 2026-06-16
输出：reports/agent_team_YYYY-MM-DD.md
"""

import argparse
import logging
import sys
from datetime import date as _date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.agent_team import build_context, analyze_batch  # noqa: E402
from replay_screen import load_stock  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agent_team")

REPORTS_DIR = PROJECT_ROOT / "reports"
LOCAL_DAY = PROJECT_ROOT / "data" / "day"
RATING_EMOJI = {"Buy": "🟢", "增持": "🟩", "持有": "⬜", "减持": "🟥", "Sell": "🔴", "观望": "⏸"}


def _load_names() -> dict[str, str]:
    meta = PROJECT_ROOT / "data" / "meta" / "share_capital.csv"
    if meta.exists():
        try:
            df = pd.read_csv(meta, dtype={"symbol": str})
            return dict(zip(df["symbol"].str.zfill(6), df["name"]))
        except Exception:
            pass
    return {}


def _pick_symbols(top_n: int, date: str | None, names: dict) -> list[tuple[str, str]]:
    """从最新 screen_*.csv 取 Top-N（symbol, name）。"""
    if date:
        f = REPORTS_DIR / f"screen_{date}.csv"
        files = [f] if f.exists() else []
    else:
        files = sorted(REPORTS_DIR.glob("screen_*.csv"))
    if not files:
        sys.exit("无 screen_*.csv，请先运行 scripts/daily_screener.py，或用 --symbols 指定")
    df = pd.read_csv(files[-1], dtype={"symbol": str}).head(top_n)
    def _name(r):
        n = r.get("name", "")
        return str(n) if pd.notna(n) and str(n) != "nan" else names.get(r["symbol"], "")
    return [(r["symbol"], _name(r)) for _, r in df.iterrows()]


def _resolve_csv(symbol: str, data_dir: Path) -> Path | None:
    for p in (data_dir / f"{symbol}.csv", LOCAL_DAY / f"{symbol}.csv"):
        if p.exists():
            return p
    return None


def _render_md(verdicts, date: str, ctx) -> str:
    ok = [v for v in verdicts if v.ok]
    ok.sort(key=lambda v: v.score, reverse=True)
    watch = [v for v in verdicts if not v.ok]

    n_debated = sum(1 for v in ok if v.meta.get("debated"))
    lines = [f"# Agent Team 投研建议 {date}",
             f"\n大盘：{ctx.macro_level}（{ctx.macro_score:.0f}/100） · "
             f"分析 {len(verdicts)} 只（有效 {len(ok)} / 观望 {len(watch)}"
             + (f" / 辩论 {n_debated}" if n_debated else "") + "）\n",
             "## 综合评级",
             "| 评级 | 代码 | 名称 | 团队分 | 仓位 | 因子 | 形态 | 板块 | 辩论 | 摘要 |",
             "|---|---|---|---|---|---|---|---|---|---|"]

    def _sig(v, agent):
        for op in v.opinions:
            if op.agent == agent:
                return f"{op.signal[:4]}·{op.confidence:.0f}"
        return "—"

    def _pos(v):
        pct = v.meta.get("position_pct", 0)
        if pct:
            return f"{pct:.0f}%"
        risk = next((op for op in v.opinions if op.agent == "risk"), None)
        return "候补" if risk and risk.evidence.get("standby") else "—"

    def _debate_cell(v):
        ref = next((op for op in v.opinions if op.agent == "referee"), None)
        if ref is None:
            return "—"
        return f"{ref.signal[:4]}·{ref.confidence:.0f}({ref.evidence['p0_score']:.0f}→{v.score:.0f})"

    for v in ok:
        lines.append(
            f"| {RATING_EMOJI.get(v.rating,'')} {v.rating} | {v.symbol} | {v.name} "
            f"| **{v.score:.0f}** | {_pos(v)} | {_sig(v,'factor')} | {_sig(v,'pattern')} "
            f"| {_sig(v,'sector')} | {_debate_cell(v)} | {v.reasoning} |")
    for v in watch:
        lines.append(f"| ⏸ 观望 | {v.symbol} | {v.name} | — | — | — | — | — | — | {v.reasoning} |")

    lines.append("\n## 逐股依据")
    for v in ok:
        lines.append(f"\n### {RATING_EMOJI.get(v.rating,'')} {v.symbol} {v.name} — "
                     f"{v.rating}（团队分 {v.score:.0f}）")
        for op in v.opinions:
            if op.agent == "referee":
                lines.append(f"- **多方** {op.evidence.get('bull','')}")
                lines.append(f"- **空方** {op.evidence.get('bear','')}")
                lines.append(f"- **仲裁** [{op.signal} {op.confidence:.0f}] {op.reasoning}"
                             f"　`P0 {op.evidence['p0_score']:.0f} → 融合 "
                             f"{op.evidence['fused_score']:.0f}`")
                continue
            ev = " ".join(f"{k}={val}" for k, val in op.evidence.items()
                          if k not in ("weights", "notes"))
            lines.append(f"- **{op.agent}** [{op.signal} {op.confidence:.0f}] "
                         f"{op.reasoning}　`{ev}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--symbols", nargs="+", help="显式指定代码（覆盖 --top）")
    ap.add_argument("--date", help="回放日 YYYY-MM-DD")
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--debate", action="store_true",
                    help="高分标的加 DeepSeek v4-pro 多空辩论+贝叶斯融合")
    ap.add_argument("--debate-min", type=float, default=65.0,
                    help="触发辩论的最低团队分（默认65）")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    names = _load_names()
    date = args.date or _date.today().isoformat()

    if args.symbols:
        picks = [(s, names.get(s, "")) for s in args.symbols]
    else:
        picks = _pick_symbols(args.top, args.date, names)
    logger.info(f"分析 {len(picks)} 只标的")

    end_date = args.date or "9999-12-31"
    items, missing = [], []
    for sym, name in picks:
        csv = _resolve_csv(sym, data_dir)
        df = load_stock(csv, end_date, min_rows=120) if csv else None
        if df is None:
            missing.append(sym)
        items.append((sym, name, df))
    if missing:
        logger.warning(f"{len(missing)} 只无足够日线（外接盘未挂载？）: {missing[:8]}")

    ctx = build_context(end_date=end_date, date=args.date)
    verdicts = analyze_batch(items, ctx, debate=args.debate,
                             debate_min=args.debate_min)

    REPORTS_DIR.mkdir(exist_ok=True)
    out = REPORTS_DIR / f"agent_team_{date}.md"
    out.write_text(_render_md(verdicts, date, ctx), encoding="utf-8")
    logger.info(f"→ {out}")

    # 决策日志（晚间 review_agent_decisions.py 对账各角色命中率）
    try:
        from alphapulse.agent_team.decision_log import append_decisions
        trade_date = args.date or max(
            (df.iloc[-1]["date"] for _, _, df in items if df is not None), default=date)
        n_logged = append_decisions(verdicts, str(trade_date))
        logger.info(f"决策日志 +{n_logged} 条（数据日 {trade_date}）")
    except Exception as e:
        logger.warning(f"决策日志写入失败: {e}")

    ok = sorted([v for v in verdicts if v.ok], key=lambda v: v.score, reverse=True)
    for v in ok[:10]:
        pos = v.meta.get("position_pct", 0)
        pos_s = f"仓{pos:.0f}%" if pos else "  —  "
        print(f"{v.rating:>4} {v.score:5.1f} {pos_s}  {v.symbol} {v.name}  {v.reasoning}")
    if not ok:
        print("（无有效标的——多为数据不足，挂载外接盘后重跑）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
