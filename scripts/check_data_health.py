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
    #    判定标准 = 是否与 settings.DATA_DIR 一致（而非硬编码某个盘），
    #    这样迁盘决策变化时不会误报（2026-07-13 修正：外接盘现为主存储）。
    print("\n[6] launchd 定时任务一致性")
    canon = os.path.normpath(str(data_dir))

    def plist_data_dir(pl: dict) -> str:
        """取 plist 实际使用的数据目录：优先 ALPHAPULSE_DATA_DIR，否则 --output-dir。"""
        env = pl.get("EnvironmentVariables") or {}
        if env.get("ALPHAPULSE_DATA_DIR"):
            return os.path.normpath(env["ALPHAPULSE_DATA_DIR"])
        args = pl.get("ProgramArguments", [])
        for i, a in enumerate(args):
            if a == "--output-dir" and i + 1 < len(args):
                return os.path.normpath(args[i + 1])
        return ""     # 未显式指定 → 继承 settings.DATA_DIR，视为一致

    la_dir = Path.home() / "Library" / "LaunchAgents"
    if sys.platform == "darwin" and la_dir.exists():
        found_mismatch = False
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
            pdd = plist_data_dir(pl)
            mismatch = bool(pdd) and pdd != canon
            loaded = subprocess.run(["launchctl", "list", name],
                                    capture_output=True).returncode == 0
            if mismatch:
                found_mismatch = True
                p(FAIL, f"{name}: 数据目录 {pdd} ≠ settings.DATA_DIR ({canon})"
                        f"{'，且已加载' if loaded else ''}")
            else:
                p(OK if loaded else WARN,
                  f"{name}: 数据目录一致{'，已加载' if loaded else '，但未加载(launchctl load)'}")
                if not loaded:
                    fixes.append(f"launchctl load ~/Library/LaunchAgents/{name}.plist")
        if found_mismatch:
            issues.append("LaunchAgents 中的 plist 数据目录与 settings.DATA_DIR 不一致")
            fixes.append('同步plist: cp "config/"com.alphapulse.*.plist ~/Library/LaunchAgents/ '
                         "&& for n in daily-update full-download daily-auto; do "
                         "launchctl unload ~/Library/LaunchAgents/com.alphapulse.$n.plist 2>/dev/null; "
                         "launchctl load ~/Library/LaunchAgents/com.alphapulse.$n.plist; done")
    else:
        p(WARN, "非macOS或无LaunchAgents目录，跳过")

    # 7. 主存储盘挂载
    print("\n[7] 主存储盘挂载")
    if canon.startswith("/Volumes/"):
        vol = "/" + "/".join(canon.split("/")[1:3])   # /Volumes/<卷名>
        mounted = Path(vol).exists()
        p(OK if mounted else FAIL,
          f"{vol} {'已挂载（主存储在此盘）' if mounted else '未挂载！主存储在此盘，流水线会启动即失败'}")
        if not mounted:
            issues.append("主存储盘未挂载")
            fixes.append(f"插上并确认挂载 {vol}，或临时切换: export ALPHAPULSE_DATA_DIR=<可用目录>")
    else:
        p(OK, f"主存储为内置盘路径 {canon}")

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
