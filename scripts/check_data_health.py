#!/usr/bin/env python3
"""数据链路一键自检 — 「数据又不更新了」时先跑这个。

逐项检查并给出诊断 + 修复命令：
1. DATA_DIR 解析结果 & 环境变量覆盖冲突
2. 日线数据新鲜度（最后日期众数 vs 今天；陈旧文件占比）
3. 指数数据新鲜度（大盘诊断/硬闸门依赖 data/index/）
4. 更新失败日志 & 断点文件（logs/data_update_failure.log, update_progress.json）
5. eod_pipeline 最近运行记录（reports/last_run.json）
6. launchd 已加载 plist 与仓库 config/ 的数据目录是否一致（外接盘残留检测）
7. 外接盘挂载状态

用法：
    python scripts/check_data_health.py
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
issues: list[str] = []
fixes: list[str] = []


def p(status, msg):
    print(f"  {status} {msg}")


def last_trade_day_guess(today: datetime) -> str:
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def main():
    print("=" * 62)
    print("AlphaPulse 数据链路自检", datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 62)

    # 1. DATA_DIR 解析
    print("\n[1] DATA_DIR 解析")
    env_override = os.environ.get("ALPHAPULSE_DATA_DIR")
    from alphapulse.config.settings import DATA_DIR
    data_dir = Path(DATA_DIR)
    if env_override:
        p(WARN, f"当前 shell 有环境变量覆盖: ALPHAPULSE_DATA_DIR={env_override}")
    p(OK if data_dir.exists() else FAIL, f"DATA_DIR = {data_dir}"
      + ("" if data_dir.exists() else "（目录不存在！）"))
    if not data_dir.exists():
        issues.append("数据目录不存在")
        fixes.append(f"确认磁盘挂载或修改 ALPHAPULSE_DATA_DIR；mkdir -p {data_dir}")
        print_summary(); return

    # 2. 日线新鲜度
    print("\n[2] 日线数据新鲜度")
    files = sorted(data_dir.glob("*.csv"))
    p(OK if len(files) > 1000 else WARN, f"CSV 文件数: {len(files)}")
    last_dates = Counter()
    sample = files[:: max(1, len(files) // 400)][:400]      # 均匀抽样≤400只
    for f in sample:
        try:
            tail = f.read_text(encoding="utf-8", errors="ignore").rstrip().rsplit("\n", 1)[-1]
            last_dates[tail.split(",")[0][:10]] += 1
        except Exception:
            continue
    if not last_dates:
        p(FAIL, "无法读取任何CSV尾行")
        issues.append("CSV不可读")
    else:
        mode_date, mode_cnt = last_dates.most_common(1)[0]
        expect = last_trade_day_guess(datetime.now())
        stale_days = (datetime.strptime(expect, "%Y-%m-%d")
                      - datetime.strptime(mode_date, "%Y-%m-%d")).days
        status = OK if stale_days <= 1 else (WARN if stale_days <= 4 else FAIL)
        p(status, f"最后日期众数: {mode_date}（占抽样 {mode_cnt}/{len(sample)}），"
                  f"距最近工作日 {expect} 相差 {stale_days} 天")
        if stale_days > 1:
            issues.append(f"日线数据陈旧 {stale_days} 天")
            fixes.append("手动补数据: source .venv/bin/activate && "
                         "python scripts/daily_update.py --max-minutes 60")
        behind = sum(c for d, c in last_dates.items() if d < mode_date)
        if behind > len(sample) * 0.1:
            p(WARN, f"落后于众数日期的文件占 {behind}/{len(sample)}（个股级断更）")
            fixes.append("个股断更恢复: python scripts/recover_stale.py")

    # 3. 指数数据
    print("\n[3] 指数数据（大盘诊断/硬闸门依赖）")
    idx_dir = PROJECT_ROOT / "data" / "index"
    idx = idx_dir / "sh000001.csv"
    if idx.exists():
        tail = idx.read_text(errors="ignore").rstrip().rsplit("\n", 1)[-1][:10]
        stale = (datetime.now() - datetime.strptime(tail, "%Y-%m-%d")).days
        p(OK if stale <= 4 else WARN, f"sh000001 最后日期 {tail}")
        if stale > 4:
            issues.append("指数数据陈旧（硬闸门/大盘档位会失真）")
            fixes.append("python scripts/fetch_index_data.py")
    else:
        p(WARN, f"{idx} 不存在（硬闸门将 fail-open）")

    # 4. 失败日志 & 断点
    print("\n[4] 更新失败日志")
    flog = PROJECT_ROOT / "logs" / "data_update_failure.log"
    if flog.exists() and flog.stat().st_size:
        lines = flog.read_text(errors="ignore").rstrip().split("\n")
        p(WARN, f"failure_log 共 {len(lines)} 条，最近3条：")
        for ln in lines[-3:]:
            print(f"       {ln[:110]}")
        issues.append("存在更新失败记录（看上面最近3条）")
    else:
        p(OK, "无失败记录")
    prog = PROJECT_ROOT / "logs" / "update_progress.json"
    if prog.exists():
        try:
            j = json.loads(prog.read_text())
            p(WARN, f"存在断点文件（上次未跑完）: {str(j)[:90]}")
            fixes.append("续传: python scripts/daily_update.py")
        except Exception:
            pass

    # 5. eod_pipeline 最近运行
    print("\n[5] 收盘流水线最近运行")
    lr = PROJECT_ROOT / "reports" / "last_run.json"
    if lr.exists():
        try:
            j = json.loads(lr.read_text())
            ts = j.get("finished_at") or j.get("time") or "?"
            p(OK, f"last_run.json: {ts} | {str({k: v for k, v in j.items() if k != 'steps'})[:90]}")
            age = None
            try:
                age = (datetime.now() - datetime.fromisoformat(str(ts)[:19])).days
            except Exception:
                pass
            if age is not None and age > 3:
                p(WARN, f"流水线已 {age} 天没跑完过")
                issues.append(f"eod_pipeline {age} 天未成功")
        except Exception as e:
            p(WARN, f"last_run.json 解析失败: {e}")
    else:
        p(WARN, "reports/last_run.json 不存在（流水线从未成功跑完？）")
        issues.append("eod_pipeline 无成功记录")

    # 6. launchd plist 一致性（macOS）
    print("\n[6] launchd 定时任务一致性")
    la_dir = Path.home() / "Library" / "LaunchAgents"
    if sys.platform == "darwin" and la_dir.exists():
        found_stale = False
        for name in ("com.alphapulse.daily-update", "com.alphapulse.full-download",
                     "com.alphapulse.daily-auto"):
            f = la_dir / f"{name}.plist"
            if not f.exists():
                p(WARN, f"{name}: 未安装到 LaunchAgents（定时任务不会跑）")
                issues.append(f"{name} 未安装")
                continue
            try:
                pl = plistlib.loads(f.read_bytes())
            except Exception as e:
                p(FAIL, f"{name}: plist 解析失败 {e}")
                continue
            env = (pl.get("EnvironmentVariables") or {})
            dd = env.get("ALPHAPULSE_DATA_DIR", "")
            args = " ".join(pl.get("ProgramArguments", []))
            stale = ("/Volumes/" in dd) or ("/Volumes/" in args and "output-dir" in args)
            loaded = subprocess.run(["launchctl", "list", name],
                                    capture_output=True).returncode == 0
            if stale:
                found_stale = True
                p(FAIL, f"{name}: 仍指向外接盘 ({dd or '见output-dir参数'})"
                        f"{'，且已加载' if loaded else ''}")
            else:
                p(OK if loaded else WARN,
                  f"{name}: 数据目录正常{'，已加载' if loaded else '，但未加载(launchctl load)'}")
                if not loaded:
                    fixes.append(f"launchctl load ~/Library/LaunchAgents/{name}.plist")
        if found_stale:
            issues.append("LaunchAgents 中的 plist 残留外接盘路径（与内置盘主存储冲突）")
            fixes.append('重装plist: cp "config/"com.alphapulse.*.plist ~/Library/LaunchAgents/ '
                         "&& launchctl unload ~/Library/LaunchAgents/com.alphapulse.daily-update.plist "
                         "&& launchctl load ~/Library/LaunchAgents/com.alphapulse.daily-update.plist")
    else:
        p(WARN, "非macOS或无LaunchAgents目录，跳过")

    # 7. 外接盘
    print("\n[7] 外接盘（冷备）")
    ext = Path("/Volumes/Mac-480g外接")
    p(OK if ext.exists() else WARN,
      f"{ext} {'已挂载' if ext.exists() else '未挂载（冷备不影响主流程，但旧plist会因此失败）'}")

    print_summary()


def print_summary():
    print("\n" + "=" * 62)
    if not issues:
        print("🎉 全部正常。若仍觉得数据不对，检查是否在看外接盘的旧副本。")
    else:
        print(f"发现 {len(issues)} 个问题：")
        for i, s in enumerate(issues, 1):
            print(f"  {i}. {s}")
        print("\n修复命令（按顺序执行）：")
        seen = set()
        for f in fixes:
            if f not in seen:
                print(f"  $ {f}")
                seen.add(f)
    print("=" * 62)


if __name__ == "__main__":
    main()
