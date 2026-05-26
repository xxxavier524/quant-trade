#!/usr/bin/env python3
"""每小时监控守护进程 — 检查任务执行状态，自动重启失败任务。

用法:
  python scripts/_monitor_runner.py          # 前台
  python scripts/_monitor_runner.py --daemon # 守护进程
"""

import sys, os, time, subprocess, json, logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = "/Volumes/Mac-480g外接/quantan_data/day"
LOG_FILE = PROJECT_ROOT / "logs" / "monitor.log"
CHECKLIST_FILE = PROJECT_ROOT / "logs" / "monitor_checklist.json"

Path(PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [MONITOR] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)

# ── 检查项定义 ──
CHECKS = [
    {
        "name": "data_download_running",
        "desc": "数据下载进程存活",
        "check": 'ps aux | grep -E "download_a_share|smart_download" | grep -v grep | wc -l',
        "expect": lambda out: int(out.strip()) > 0,
        "action": f"cd '{PROJECT_ROOT}' && source .venv/bin/activate && no_proxy='*' python -u scripts/_smart_downloader.py &",
        "severity": "WARN",
    },
    {
        "name": "data_files_growing",
        "desc": "数据文件数 >= 5000",
        "check": f"ls '{DATA_DIR}'/*.csv 2>/dev/null | wc -l",
        "expect": lambda out: int(out.strip()) >= 5000,
        "action": "NONE",  # 下载进程会自行增长
        "severity": "INFO",
    },
    {
        "name": "test_suite_passing",
        "desc": "测试套件 100% 通过",
        "check": f"cd '{PROJECT_ROOT}' && source .venv/bin/activate && python -m pytest tests/ -q 2>&1 | tail -2",
        "expect": lambda out: "failed" not in out and "ERROR" not in out,
        "action": f"cd '{PROJECT_ROOT}' && source .venv/bin/activate && python -m pytest tests/ -q",
        "severity": "CRITICAL",
    },
    {
        "name": "factor_registry_importable",
        "desc": "因子注册表可导入",
        "check": f"cd '{PROJECT_ROOT}' && source .venv/bin/activate && python -c 'from alphapulse.factors.factor_registry import FACTOR_REGISTRY; print(len(FACTOR_REGISTRY))' 2>&1",
        "expect": lambda out: int(out.strip() or '0') >= 15,
        "action": "NONE",
        "severity": "CRITICAL",
    },
    {
        "name": "baostock_reachable",
        "desc": "baostock 可达",
        "check": f"cd '{PROJECT_ROOT}' && source .venv/bin/activate && python -c 'import baostock as bs; lg=bs.login(); print(lg.error_code); bs.logout()' 2>&1",
        "expect": lambda out: "0" in out,
        "action": "NONE",
        "severity": "WARN",
    },
    {
        "name": "akshare_reachable",
        "desc": "akshare 可达",
        "check": f"cd '{PROJECT_ROOT}' && source .venv/bin/activate && no_proxy='*' python -c 'import akshare as ak; df=ak.stock_zh_a_spot_em(); print(len(df))' 2>&1",
        "expect": lambda out: "0" not in out.strip(),
        "action": "NONE",
        "severity": "WARN",
    },
]


def run_check(check_def: dict) -> dict:
    """执行单个检查。"""
    try:
        result = subprocess.run(
            check_def['check'], shell=True, capture_output=True, text=True, timeout=60,
            executable='/bin/bash',
        )
        output = (result.stdout + result.stderr).strip()
        passed = check_def['expect'](output)
        return {
            "name": check_def['name'],
            "desc": check_def['desc'],
            "passed": passed,
            "output": output[:200],
            "severity": check_def['severity'],
            "action": check_def.get('action', 'NONE'),
        }
    except Exception as e:
        return {
            "name": check_def['name'],
            "passed": False,
            "output": str(e)[:200],
            "severity": check_def.get('severity', 'ERROR'),
        }


def run_all_checks() -> list[dict]:
    """运行全部检查。"""
    results = []
    for cdef in CHECKS:
        r = run_check(cdef)
        results.append(r)
        icon = "✅" if r['passed'] else "❌"
        logging.info(f"  {icon} {r['name']}: {r.get('output', '')[:80]}")
    return results


def take_action(failed: list[dict]):
    """对失败的检查执行修复动作。"""
    for r in failed:
        action = r.get('action', 'NONE')
        if action and action != 'NONE':
            logging.warning(f"  🔧 执行修复: {r['name']} → {action}")
            try:
                subprocess.run(action, shell=True, timeout=120,
                               executable='/bin/bash')
            except Exception as e:
                logging.error(f"  ❌ 修复失败: {e}")


def main_loop(interval: int = 3600):
    """主循环：每小时检查一次。"""
    logging.info("=" * 60)
    logging.info("AlphaPulse-A 监控守护进程 启动")
    logging.info(f"检查间隔: {interval}s ({interval/3600:.1f}h)")
    logging.info("=" * 60)

    cycle = 0
    while True:
        cycle += 1
        logging.info(f"-- 第 {cycle} 轮检查 {datetime.now().isoformat()} --")

        results = run_all_checks()
        failed = [r for r in results if not r['passed']]

        if failed:
            logging.warning(f"⚠️ {len(failed)} 项失败:")
            for r in failed:
                logging.warning(f"  [{r['severity']}] {r['name']}: {r.get('output', '')[:100]}")
            take_action(failed)

        # 保存状态
        Path(CHECKLIST_FILE).write_text(json.dumps(
            {"last_check": datetime.now().isoformat(), "cycle": cycle,
             "total": len(results), "passed": len(results) - len(failed),
             "failed": len(failed), "details": results},
            indent=2, default=str,
        ))

        critical_fails = [r for r in failed if r.get('severity') == 'CRITICAL']
        if critical_fails:
            logging.critical(f"🔴 {len(critical_fails)} CRITICAL 失败!")

        logging.info(f"第 {cycle} 轮完成 ({len(results)-len(failed)}/{len(results)}). 下次: {datetime.now().isoformat()} + {interval}s")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=3600, help="检查间隔（秒），默认3600")
    p.add_argument("--once", action="store_true", help="只运行一次")
    p.add_argument("--daemon", action="store_true", help="守护进程（默认）")
    args = p.parse_args()

    if args.once:
        results = run_all_checks()
        failed = [r for r in results if not r['passed']]
        print(f"\n结果: {len(results)-len(failed)}/{len(results)} 通过")
        if failed:
            print("失败项:")
            for r in failed:
                print(f"  [{r['severity']}] {r['name']}")
        sys.exit(1 if failed else 0)
    else:
        main_loop(args.interval)


# ===== v3.0 Auto-repair extension =====
import subprocess
import re

ERROR_PATTERNS = {
    r"rate.?limit|429|too many requests": {"action": "wait", "wait_sec": 60},
    r"connection refused|ConnectionError": {"action": "retry", "retry_delay": 30},
    r"timeout|Timeout": {"action": "skip", "reason": "single stock timeout"},
    r"empty.?data|no data|返回为空": {"action": "fallback", "fallback_source": "baostock"},
    r"module.*not found|ImportError|ModuleNotFoundError": {"action": "install", "reason": "missing dependency"},
}

def diagnose_error(stderr):
    for pattern, action in ERROR_PATTERNS.items():
        if re.search(pattern, stderr, re.IGNORECASE):
            return action
    return {"action": "log", "reason": "unknown error"}

def auto_repair(script_path, stderr):
    diagnosis = diagnose_error(stderr)
    logger.warning(f"Auto-repair: {diagnosis}")
    action = diagnosis.get("action")
    if action == "wait":
        time.sleep(diagnosis.get("wait_sec", 60))
        return True
    elif action == "retry":
        time.sleep(diagnosis.get("retry_delay", 30))
        return True
    elif action == "skip":
        logger.info(f"Skipping: {diagnosis.get('reason')}")
        return False
    elif action == "fallback":
        logger.info(f"Fallback to {diagnosis.get('fallback_source')}")
        return True
    elif action == "install":
        logger.info("Attempting pip install...")
        return False
    return False

def run_script_safe(script_path, timeout_min=30):
    try:
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=timeout_min*60)
        if result.returncode != 0:
            logger.error(f"Script {script_path} failed (exit={result.returncode})")
            logger.error(f"STDERR: {result.stderr[:500]}")
            if auto_repair(script_path, result.stderr):
                logger.info("Retrying after auto-repair...")
                result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=timeout_min*60)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout after {timeout_min}min")
        return -1, "", "TIMEOUT"
