#!/usr/bin/env python3
"""launchd 任务硬超时包装器 — 任何子任务都不可能无限挂死。

用法（plist ProgramArguments）：
    python scripts/run_with_timeout.py 3600 python scripts/daily_update.py --max-minutes 45

超时后先 SIGTERM（给10秒清理保存进度），仍不退则 SIGKILL，exit 124。

失败告警（2026-07-11）：子任务非零退出时直读 .env 发飞书——不 import settings，
因为外接数据盘缺盘时 settings 导入即抛错，届时脚本内的告警代码根本没机会执行，
这里是最后一道告警防线。
"""

import subprocess
import sys
from pathlib import Path


def _alert_best_effort(msg: str) -> None:
    """不依赖 settings/requests 的飞书告警（stdlib urllib + 直读 .env）。"""
    try:
        env_file = Path(__file__).resolve().parent.parent / ".env"
        url = ""
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("FEISHU_WEBHOOK_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        if not url:
            return
        import json
        import urllib.request
        payload = {"msg_type": "text",
                   "content": {"text": f"[AlphaPulse] ⚠️ 定时任务失败: {msg}"}}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # 告警失败不影响退出码


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: run_with_timeout.py <秒数> <命令...>", file=sys.stderr)
        return 64
    timeout = float(sys.argv[1])
    cmd = sys.argv[2:]
    task_name = next((a for a in cmd if a.endswith(".py")), cmd[0])
    proc = subprocess.Popen(cmd)
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[watchdog] 超过 {timeout:.0f}s，发送 SIGTERM", file=sys.stderr)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("[watchdog] SIGTERM 无效，SIGKILL", file=sys.stderr)
            proc.kill()
            proc.wait()
        _alert_best_effort(f"{Path(task_name).name} 硬超时{timeout:.0f}s被终止")
        return 124
    if rc != 0:
        _alert_best_effort(f"{Path(task_name).name} 退出码 {rc}"
                           "（缺盘/数据/脚本异常，查 logs/*stderr.log）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
