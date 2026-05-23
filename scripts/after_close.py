#!/usr/bin/env python3
"""收盘后任务：更新数据 → 全量选股 → 输出今日信号。

每天 15:30 由 launchd 触发。
"""

import sys, json, subprocess
from pathlib import Path
from datetime import date, datetime
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path("/Volumes/Mac-480g外接/quantan_data/day")

def run_step(cmd: list, desc: str) -> bool:
    print(f"\n{'='*50}")
    print(f"[{datetime.now():%H:%M:%S}] {desc}")
    print(f"{'='*50}")
    r = subprocess.run(cmd, capture_output=False, cwd=str(PROJECT_ROOT))
    return r.returncode == 0

def main():
    today = date.today()
    print(f"\n{'='*60}")
    print(f"  AlphaPulse-A 收盘后任务 — {today}")
    print(f"{'='*60}")

    # Step 1: 增量更新数据
    if not run_step(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "daily_update.py")],
        "Step 1/2: 数据增量更新"
    ):
        print("[ERROR] 数据更新失败，终止选股")
        return 1

    # Step 2: 全量选股
    if not run_step(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "friday_screener.py")],
        "Step 2/2: 全量选股"
    ):
        print("[ERROR] 选股失败")
        return 1

    # Step 3: 输出简报
    json_path = PROJECT_ROOT / "reports" / f"friday_screen_{today.isoformat()}.json"
    if json_path.exists():
        d = json.loads(json_path.read_text())
        n_consensus = len(d.get("consensus", {}))
        n_stocks = d.get("n_stocks_screened", 0)
        fs = d.get("filter_stats", {})

        print(f"\n{'='*60}")
        print(f" 今日选股完成")
        print(f"{'='*60}")
        print(f"  过滤前: {d.get('n_before_filter', '?')} 只")
        print(f"  ST排除: {fs.get('st', '?')} | 退市排除: {fs.get('delisted', '?')}")
        print(f"  N型排除: {fs.get('n_struct', '?')} | 涨停排除: {fs.get('limit_up', '?')}")
        print(f"  过滤后: {n_stocks} 只 → 共识信号: {n_consensus} 只")
        if isinstance(d["consensus"], dict):
            for sym, v in sorted(d["consensus"].items(), key=lambda x: -len(x[1]["strategies"])):
                print(f"    {sym}: {', '.join(v['strategies'])}")

    print(f"\n[{datetime.now():%H:%M:%S}] 收盘任务全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
