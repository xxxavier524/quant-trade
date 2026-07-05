#!/usr/bin/env python3
"""收盘后流水线（15:30）：增量更新数据 → 立即全市场选股 → 信号追踪。

用户需求 2026-06-12：更新时间定在收盘后 15:30，更新完数据立即选股。
每步独立子进程，单步失败不影响后续（选股可用已有数据兜底）。
完成后写 reports/last_run.json（首页显示"数据/选股更新时间"）。

用法：
    python scripts/eod_pipeline.py [--max-update-min 30]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PY = str(PROJECT_ROOT / ".venv" / "bin" / "python")
REPORTS_DIR = PROJECT_ROOT / "reports"


def run_step(name: str, args: list[str], timeout: int) -> dict:
    t0 = datetime.now()
    print(f"\n===== [{t0:%H:%M:%S}] {name} =====", flush=True)
    try:
        rc = subprocess.call([PY] + args, cwd=str(PROJECT_ROOT), timeout=timeout)
        ok = rc == 0
    except subprocess.TimeoutExpired:
        print(f"[{name}] 超时 {timeout}s", file=sys.stderr)
        ok, rc = False, 124
    dur = (datetime.now() - t0).total_seconds()
    print(f"[{name}] {'完成' if ok else '失败'} rc={rc} 耗时{dur:.0f}s", flush=True)
    return {"step": name, "ok": ok, "rc": rc, "seconds": round(dur)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-update-min", type=int, default=30)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--skip-update", action="store_true", help="只重跑选股（调试用）")
    args = ap.parse_args()

    steps = []
    if not args.skip_update:
        steps.append(run_step("数据增量更新",
                              ["scripts/daily_update.py", "--max-minutes", str(args.max_update_min)],
                              timeout=(args.max_update_min + 10) * 60))
    # 选股：即使更新失败也跑（用已有数据），陈旧告警在脚本内
    steps.append(run_step("全市场选股",
                          ["scripts/daily_screener.py", "--top", str(args.top)],
                          timeout=900))
    # 信号追踪：录入今日Top + 回填历史表现（非关键，失败不影响）
    steps.append(run_step("信号追踪",
                          ["scripts/track_signals.py"], timeout=300))
    # agent决策对账：决策日志 vs 实际行情，各角色命中率（非关键）
    steps.append(run_step("agent决策对账",
                          ["scripts/review_agent_decisions.py"], timeout=300))

    REPORTS_DIR.mkdir(exist_ok=True)
    _noncritical = {"信号追踪", "agent决策对账"}
    marker = {
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "steps": steps,
        "ok": all(s["ok"] for s in steps if s["step"] not in _noncritical),
    }
    (REPORTS_DIR / "last_run.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2))
    print(f"\n流水线完成 @ {marker['finished_at']}: {marker}")
    return 0 if marker["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
