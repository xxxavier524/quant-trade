"""信号追踪 CLI — 每日选股后运行（eod_pipeline 15:30 调度）。

1. 录入最新 screen_*.csv 信号（含战法归属），回填旧信号缺失标注
2. 回填全部信号的1-7日表现
3. 成功判定：5日内涨超+5%=脱离成本区；累计跌超-5%=大跌止踪
4. 新成功案例自动复盘（DeepSeek，选股过程/特征/上涨原因）
5. 夜间复盘推飞书：按两大战法分列的成功率 + 案例复盘

用法：
    python scripts/track_signals.py              # 完整流程（含飞书推送）
    python scripts/track_signals.py --no-feishu  # 不推送（调试）
    python scripts/track_signals.py --no-llm     # 复盘用规则拼装不调LLM
    python scripts/track_signals.py --distill    # 额外跑连涨归因沉淀（既有闭环）
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.config.settings import DATA_DIR, FEISHU_WEBHOOK_URL  # noqa: E402
from alphapulse.tracking import signal_tracker as tk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--distill", action="store_true", help="连涨归因+LLM沉淀")
    ap.add_argument("--no-feishu", action="store_true", help="不推送飞书")
    ap.add_argument("--no-llm", action="store_true", help="成功复盘不调LLM")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    for csv in sorted((PROJECT_ROOT / "reports").glob("screen_*.csv")):
        n = tk.record_signals(csv)
        if n:
            print(f"录入 {csv.name}: +{n} 条")

    n = tk.backfill_labels()
    if n:
        print(f"回填战法标注: {n} 条")

    n = tk.update_performance(Path(args.data_dir))
    print(f"回填表现: +{n} 条")

    outcomes = tk.evaluate_outcomes()
    print(f"成功判定: 成功{outcomes['success']} 止踪{outcomes['stopped_drop']} "
          f"过期{outcomes['expired']}")

    reviews = tk.distill_success(use_llm=not args.no_llm)
    for rv in reviews:
        print(f"⭐ 复盘 {rv['symbol']} {rv['name']} +{rv['outcome_pct']}%: {rv['review'][:80]}")

    review_text = tk.nightly_review_text(new_reviews=reviews, new_outcomes=outcomes)
    print("\n" + review_text)

    if not args.no_feishu and FEISHU_WEBHOOK_URL:
        from alphapulse.notify.feishu_bot import send_feishu
        ok = send_feishu(FEISHU_WEBHOOK_URL, review_text)
        print(f"飞书夜间复盘推送: {'成功' if ok else '失败'}")

    rep = tk.weekly_report()
    if rep.empty:
        print("暂无可复盘数据")
        return
    print(f"\n近一周信号 {len(rep)} 条；连涨≥2天 {int((rep['streak'] >= 2).sum())} 条")
    cols = [c for c in ["date", "symbol", "name", "score", "streak", "cum_pct"] if c in rep.columns]
    print(rep[cols].head(15).to_string(index=False))

    if args.distill:
        import json
        r = tk.distill_streaks(use_llm=not args.no_llm)
        print("\n===== 连涨归因 =====")
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
