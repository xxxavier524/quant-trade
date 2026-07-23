#!/usr/bin/env python3
"""每小时数据自愈补齐 — 保证当日数据最终更新，且不每次尝试都告警（2026-07-23 用户定）。

背景：baostock 在收盘/晚间跑批时段间歇性"网络接收错误"，单次更新常只覆盖 14-23%，
导致每天两次定时任务都以 rc=1 告警。本脚本由 launchd 在收盘后每小时唤醒（15:35→22:30）：
  1. 刷新指数 → 得当日基准交易日 target（个股取数不受影响的独立基准）。
  2. 覆盖率 cov = 个股已到 target 的占比。
  3. cov ≥ DONE_THRESHOLD：数据够 → 若当日尚未选股则选一次（选股自身推送）→ 退出，不额外告警。
  4. cov < DONE_THRESHOLD：静默 resume daily_update（断点续传，--quiet 不推飞书）→ 重测 cov：
     - 非最后窗口：静默，等下一小时再续（launchd 下个整点唤醒）。
     - 最后窗口(hour≥FINAL_HOUR)仍不足：用现有数据选股一次，并"只推一次"提示(≥SELECT_MIN)
       或告警(<SELECT_MIN)。
状态 logs/catchup_state.json 保证"选股只一次、告警只一次"。周末跳过（无行情）。

用法：
    python scripts/data_catchup.py            # 一次唤醒
    python scripts/data_catchup.py --dry-run  # 只算 target/cov/plan，不动数据/不选股/不推送
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PY = str(PROJECT_ROOT / ".venv" / "bin" / "python")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR, FEISHU_WEBHOOK_URL  # noqa: E402
from daily_update import _coverage  # noqa: E402  复用尾行覆盖率计算

LOGS_DIR = PROJECT_ROOT / "logs"
STATE_FILE = LOGS_DIR / "catchup_state.json"
INDEX_CSV = PROJECT_ROOT / "data" / "index" / "sh000001.csv"

DONE_THRESHOLD = 0.90   # 覆盖率达此值视为"当日数据够了"（留停牌股余量）
SELECT_MIN = 0.75       # 够选股的最低覆盖率（与 daily_update 健康线一致）
FINAL_HOUR = 22         # 最后一个补齐窗口的小时；此后仍不足才告警
ATTEMPT_MIN = 35        # 单次 resume 的时间预算（分钟）——+选股≈55min，短于1小时窗口间隔


def _index_latest() -> str | None:
    """基准最新交易日 = 上证指数最新bar日期（独立于个股取数）。"""
    if not INDEX_CSV.exists():
        return None
    try:
        import pandas as pd
        d = pd.read_csv(INDEX_CSV, usecols=["date"])
        return str(d["date"].iloc[-1]) if len(d) else None
    except Exception:
        return None


def load_state(today: str) -> dict:
    """读当日状态；跨天自动重置。"""
    try:
        s = json.loads(STATE_FILE.read_text())
        if s.get("date") == today:
            return s
    except Exception:
        pass
    return {"date": today, "selection_done": False, "final_alerted": False,
            "attempts": 0, "best_cov": 0.0}


def save_state(state: dict) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False))
    import os
    os.replace(tmp, STATE_FILE)


def plan(cov: float, hour: int, state: dict,
         done_thr: float = DONE_THRESHOLD, select_min: float = SELECT_MIN,
         final_hour: int = FINAL_HOUR) -> dict:
    """纯决策：给定（重测后的）覆盖率/当前小时/当日状态，决定是否选股 + 通知类型。

    返回 {run_selection: bool, notify: None|'partial'|'fail'}。
    - 数据够(cov≥done)：若还没选过则选一次；不额外告警（选股自身会推送）。
    - 未够且非最后窗口：静默续传，不选不通知（等下一小时）。
    - 未够且最后窗口：用现有数据选一次；cov≥select_min 推一次"提示"，否则推一次"告警"。
    """
    sel_done = bool(state.get("selection_done"))
    if cov >= done_thr:
        return {"run_selection": not sel_done, "notify": None}
    if hour >= final_hour:
        if cov >= select_min:
            return {"run_selection": not sel_done, "notify": None if sel_done else "partial"}
        return {"run_selection": not sel_done,
                "notify": None if state.get("final_alerted") else "fail"}
    return {"run_selection": False, "notify": None}


def _feishu(msg: str) -> None:
    if not FEISHU_WEBHOOK_URL:
        return
    try:
        from alphapulse.notify.feishu_bot import send_feishu
        send_feishu(FEISHU_WEBHOOK_URL, msg)
    except Exception:
        pass


def _run(args: list[str], timeout: int) -> int:
    try:
        return subprocess.call([PY] + args, cwd=str(PROJECT_ROOT), timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只算 target/cov/plan，无副作用")
    ap.add_argument("--force-weekend", action="store_true")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    data_path = Path(args.data_dir)

    # 周末守卫：无行情，避免"永远补不齐→最后窗口误告警"
    if not args.force_weekend and now.weekday() >= 5:
        print("周末非交易日，跳过数据自愈")
        return 0

    # 硬盘未挂载是致命错误——始终告警（非 --quiet）
    if not data_path.exists() or not any(data_path.glob("*.csv")):
        if not args.dry_run:
            _feishu(f"⚠️ AlphaPulse 数据自愈: 数据目录不可用 {data_path}（外接盘未挂载？）")
        print(f"数据目录不可用: {data_path}")
        return 2

    if not args.dry_run:
        _run(["scripts/fetch_index_data.py"], timeout=180)  # 刷新指数基准（快）
    target = _index_latest()
    if not target:
        print("无指数基准 sh000001.csv，无法确定目标交易日；跳过（不告警）")
        return 0

    state = load_state(today)
    cov = _coverage(data_path, target)
    print(f"[{now:%H:%M}] 目标日 {target} 覆盖率 {cov*100:.1f}% "
          f"(DONE≥{DONE_THRESHOLD*100:.0f}% SELECT≥{SELECT_MIN*100:.0f}%) 状态={state}")

    if args.dry_run:
        print("plan:", plan(cov, now.hour, state))
        return 0

    # 未达标 → 静默续传一次（断点续传，--quiet 不推飞书）
    if cov < DONE_THRESHOLD:
        rc = _run(["scripts/daily_update.py", "--quiet", "--max-minutes", str(ATTEMPT_MIN)],
                  timeout=(ATTEMPT_MIN + 10) * 60)
        state["attempts"] = int(state.get("attempts", 0)) + 1
        cov = _coverage(data_path, target)  # 重测
        print(f"续传后覆盖率 {cov*100:.1f}%（daily_update rc={rc}，第{state['attempts']}次）")
    state["best_cov"] = max(float(state.get("best_cov", 0.0)), cov)

    action = plan(cov, now.hour, state)

    if action["run_selection"]:
        sel_rc = _run(["scripts/eod_pipeline.py", "--skip-update", "--push-label", "自愈"],
                      timeout=1200)
        state["selection_done"] = True
        print(f"已触发选股流水线（eod_pipeline --skip-update rc={sel_rc}）")

    if action["notify"] == "partial":
        _feishu(f"📊 AlphaPulse 数据自愈: 当日数据覆盖 {cov*100:.0f}%（已尽力续传 "
                f"{state['attempts']} 次），用现有数据完成选股。")
    elif action["notify"] == "fail":
        state["final_alerted"] = True
        _feishu(f"⚠️ AlphaPulse 数据自愈: 当日数据仅覆盖 {cov*100:.0f}%（<{SELECT_MIN*100:.0f}%，"
                f"续传 {state['attempts']} 次仍不足），数据源可能持续异常，请检查网络/baostock。")

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
