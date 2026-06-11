"""信号追踪 CLI — 每日选股后运行（可挂入定时任务）。

1. 录入最新 screen_*.csv 信号
2. 回填全部信号的1-7日表现
3. 输出近一周复盘 + 连涨归因

用法：
    python scripts/track_signals.py            # 录入+回填+复盘
    python scripts/track_signals.py --distill  # 额外跑LLM归因沉淀
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.tracking import signal_tracker as tk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--distill", action="store_true", help="连涨归因+LLM沉淀")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    for csv in sorted((PROJECT_ROOT / "reports").glob("screen_*.csv")):
        n = tk.record_signals(csv)
        if n:
            print(f"录入 {csv.name}: +{n} 条")

    n = tk.update_performance(Path(args.data_dir))
    print(f"回填表现: +{n} 条")

    rep = tk.weekly_report()
    if rep.empty:
        print("暂无可复盘数据")
        return
    print(f"\n近一周信号 {len(rep)} 条；连涨≥2天 {int((rep['streak'] >= 2).sum())} 条")
    cols = [c for c in ["date", "symbol", "name", "score", "streak", "cum_pct"] if c in rep.columns]
    print(rep[cols].head(15).to_string(index=False))

    if args.distill:
        import json
        r = tk.distill_streaks(use_llm=True)
        print("\n===== 连涨归因 =====")
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
