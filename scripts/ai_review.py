"""AI 研判 — 对每日选股 Top N 生成 DeepSeek 点评（deepseek-v4-flash 批量）。

读取 reports/screen_YYYY-MM-DD.csv（daily_screener 输出），把 Top N 的
子分数明细+严格信号+大盘/板块语境一次性发给 LLM，产出中文研判 markdown。
成本控制：单次调用、Top10、~2k tokens 出 → 约 ¥0.1/天。

用法：
    python scripts/ai_review.py                # 最新一份 screen csv
    python scripts/ai_review.py --date 2026-05-15 --top 10
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPORTS_DIR = PROJECT_ROOT / "reports"

PROMPT_TMPL = """你是A股短线交易员的复盘助手。交易体系：B1底部买点（J低位+缩量+知行白线上黄线）、
B2放量确认、单针下三十洗盘补票、砖型图超短。卖出看S1巨量阴/DD/破白线。

今日量化选股 Top {n}（评分0-100，子分数0-1）：

{table}

大盘：{macro}

请输出（中文，紧凑）：
1. 一句话大盘观点
2. 逐只点评（每只≤2行）：强弱点、属于哪类买点形态、需要注意什么
3. 按确定性排序的前3推荐与理由
不要编造数据，只基于给出的指标。"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    from alphapulse.llm.client import chat, is_configured, MODEL_BATCH
    if not is_configured():
        sys.exit("未配置 DEEPSEEK_API_KEY，跳过 AI 研判")

    if args.date:
        csv = REPORTS_DIR / f"screen_{args.date}.csv"
    else:
        cands = sorted(REPORTS_DIR.glob("screen_*.csv"))
        if not cands:
            sys.exit("无 screen_*.csv，请先运行 daily_screener")
        csv = cands[-1]
    date = csv.stem.replace("screen_", "")

    df = pd.read_csv(csv, dtype={"symbol": str}).head(args.top)
    sub_cols = [c for c in ["j_low", "trend_gap", "vol_shrink", "yangyin", "surge",
                            "bowl", "washout_recover"] if c in df.columns]
    lines = []
    for _, r in df.iterrows():
        sigs = [s for s, c in [("B1", "sig_b1"), ("量能B1", "sig_volume_b1"),
                               ("知行超短", "sig_zhixing")] if r.get(c)]
        subs = " ".join(f"{c}={r[c]:.2f}" for c in sub_cols if pd.notna(r.get(c)))
        lines.append(f"{r['rank']}. {r['symbol']}{r.get('name', '')} 总分{r['score']:.0f} "
                     f"严格信号[{'+'.join(sigs) or '无'}] 板块[{r.get('sector', '')}] {subs}")

    macro = ""
    md_path = REPORTS_DIR / f"daily_report_{date}.md"
    if md_path.exists():
        for line in md_path.read_text().splitlines():
            if line.startswith("大盘"):
                macro = line
                break

    prompt = PROMPT_TMPL.format(n=len(df), table="\n".join(lines), macro=macro or "未知")
    print(f"调用 {MODEL_BATCH} 研判 {len(df)} 只 ...")
    text = chat(prompt, model=MODEL_BATCH, temperature=0.4, max_tokens=2500)

    out = REPORTS_DIR / f"ai_review_{date}.md"
    out.write_text(f"# AI 研判 {date}\n\n{text}\n", encoding="utf-8")
    print(text)
    print(f"\n已存 {out}")


if __name__ == "__main__":
    main()
