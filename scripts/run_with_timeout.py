#!/usr/bin/env python3
"""launchd 任务硬超时包装器 — 任何子任务都不可能无限挂死。

用法（plist ProgramArguments）：
    python scripts/run_with_timeout.py 3600 python scripts/daily_update.py --max-minutes 45

超时后先 SIGTERM（给10秒清理保存进度），仍不退则 SIGKILL，exit 124。
"""

import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: run_with_timeout.py <秒数> <命令...>", file=sys.stderr)
        return 64
    timeout = float(sys.argv[1])
    cmd = sys.argv[2:]
    proc = subprocess.Popen(cmd)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[watchdog] 超过 {timeout:.0f}s，发送 SIGTERM", file=sys.stderr)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("[watchdog] SIGTERM 无效，SIGKILL", file=sys.stderr)
            proc.kill()
            proc.wait()
        return 124


if __name__ == "__main__":
    sys.exit(main())
