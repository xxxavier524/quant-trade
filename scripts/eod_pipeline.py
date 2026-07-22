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
    ap.add_argument("--push-label", default="", help="推送标题附注（22:00晚间版传'晚间版'）")
    ap.add_argument("--force-weekend", action="store_true", help="周末也强制运行")
    args = ap.parse_args()

    # 周末守卫：launchd 每天触发，周六日无行情，照跑只会把周五内容重复推送
    # （节假日暂未覆盖：数据更新会因无新K线快速空转，选股结果同前一交易日）
    if not args.force_weekend and datetime.now().weekday() >= 5:
        print("周末非交易日，跳过流水线（--force-weekend 可强制）")
        return 0

    steps = []
    if not args.skip_update:
        steps.append(run_step("数据增量更新",
                              ["scripts/daily_update.py", "--max-minutes", str(args.max_update_min)],
                              timeout=(args.max_update_min + 10) * 60))
    # 指数更新：硬闸门(上证MACD零轴/大盘S1)与大盘档位都依赖 data/index/，
    # 此前从未纳入流水线导致指数长期陈旧（2026-07-20 修复）。走新浪直连，很快。
    steps.append(run_step("指数更新",
                          ["scripts/fetch_index_data.py"], timeout=180))
    # 选股：即使更新失败也跑（用已有数据），陈旧告警在脚本内
    screener_args = ["scripts/daily_screener.py", "--top", str(args.top)]
    if args.push_label:
        screener_args += ["--push-label", args.push_label]
    steps.append(run_step("全市场选股", screener_args, timeout=900))
    # 信号追踪：录入今日Top + 回填历史表现（非关键，失败不影响）
    # 600s：含最多5次DeepSeek成功复盘 + 飞书频控重试(最长3×24s)，300s可能被掐
    steps.append(run_step("信号追踪",
                          ["scripts/track_signals.py"], timeout=600))
    # agent决策对账：决策日志 vs 实际行情，各角色命中率（非关键）
    steps.append(run_step("agent决策对账",
                          ["scripts/review_agent_decisions.py"], timeout=300))
    # 卡死股恢复：除权导致落后的股票慢速啃一批（H4，此前无任何调度→永不自动恢复）。
    # 非关键、恢复的数据下次选股才生效；baostock 限流时自然空转，不影响主流程。
    steps.append(run_step("卡死股恢复",
                          ["scripts/recover_stale.py", "--limit", "200"], timeout=900))

    REPORTS_DIR.mkdir(exist_ok=True)
    _noncritical = {"信号追踪", "agent决策对账", "指数更新", "卡死股恢复"}
    try:
        git_rev = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL, timeout=10).decode().strip()
    except Exception:
        git_rev = "unknown"
    marker = {
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "git_rev": git_rev,   # 部署漂移排查（H2）：记录实际运行的代码版本
        "steps": steps,
        "ok": all(s["ok"] for s in steps if s["step"] not in _noncritical),
    }
    (REPORTS_DIR / "last_run.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2))
    print(f"\n流水线完成 @ {marker['finished_at']}: {marker}")
    return 0 if marker["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
