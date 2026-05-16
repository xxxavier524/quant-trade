#!/usr/bin/env python3
"""带重试和错误报告的数据下载包装器。

最多重试5次，全部失败后输出错误报告告知用户如何解决。

用法:
    python scripts/download_with_retry.py --sample 100
    python scripts/download_with_retry.py --symbols 600519,000001
"""

import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime


MAX_RETRIES = 5
RETRY_DELAYS = [10, 30, 60, 120, 300]  # 逐次递增等待


def run_download(cmd: list[str]) -> tuple[bool, str]:
    """执行一次下载，返回（成功, 输出）。"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        output = result.stdout + "\n" + result.stderr
        if result.returncode == 0 and "error: 0" in output or "ok" in output:
            return True, output
        return False, output
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: 下载超过2小时"
    except Exception as e:
        return False, f"EXCEPTION: {e}"


def generate_error_report(failures: list[dict]) -> str:
    """生成错误报告。"""
    lines = [
        "# AlphaPulse-A 数据下载失败报告",
        f"",
        f"**生成时间**: {datetime.now().isoformat()}",
        f"**重试次数**: {len(failures)}/{MAX_RETRIES}",
        f"**最终状态**: ❌ 全部失败",
        f"",
        f"## 失败详情",
        f"",
    ]
    for i, f in enumerate(failures):
        lines.append(f"### 第 {i+1} 次尝试（等待{f['delay']}s后）")
        lines.append(f"```\n{f['output'][:500]}\n```")
        lines.append("")

    lines.extend([
        "## 诊断与解决",
        "",
        "### 可能原因 1：网络代理/VPN 阻断 baostock",
        "- **症状**: `RemoteDisconnected`, `ConnectionError`, `timeout`",
        "- **解决**: 关闭 VPN/代理，确保能直连 `http://baostock.com`",
        "- **验证**: 浏览器打开 http://baostock.com 确认可访问",
        "",
        "### 可能原因 2：baostock 服务不可用",
        "- **症状**: `login failed`, 所有请求返回空",
        "- **解决**: 等待1小时后重试。baostock 是免费服务，偶有维护。",
        "- **备选**: 改用 AKShare (需关闭代理)",
        "  ```bash",
        "  pip install akshare",
        "  no_proxy='*' python scripts/download_a_share_data.py --source akshare --sample 100",
        "  ```",
        "",
        "### 可能原因 3：外接硬盘未挂载",
        "- **症状**: `No such file or directory: /Volumes/...`",
        "- **解决**: 插入外接硬盘，确认挂载路径",
        "  ```bash",
        "  ls /Volumes/  # 确认硬盘已挂载",
        "  ```",
        "  - 如未挂载，可先下载到本地：",
        "  ```bash",
        "  python scripts/download_a_share_data.py --output-dir ./data/day --sample 100",
        "  ```",
        "",
        "### 可能原因 4：Python 依赖缺失",
        "- **解决**:",
        "  ```bash",
        "  source .venv/bin/activate",
        "  uv pip install baostock pandas",
        "  ```",
        "",
        "## 手动重试命令",
        "",
        "```bash",
        "cd '/Users/qiushixuan/cc/quantan trade'",
        "source .venv/bin/activate",
        "python scripts/download_a_share_data.py --sample 100",
        "```",
    ])

    return "\n".join(lines)


def main():
    # 构建命令（传递所有参数给 download_a_share_data.py）
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "download_a_share_data.py"),
        *sys.argv[1:],
    ]

    failures = []
    for attempt in range(MAX_RETRIES):
        print(f"[ATTEMPT {attempt+1}/{MAX_RETRIES}] 下载中...")
        success, output = run_download(cmd)

        if success:
            print(f"[OK] 第 {attempt+1} 次尝试成功！")
            return

        delay = RETRY_DELAYS[attempt]
        failures.append({"attempt": attempt+1, "delay": delay, "output": output})
        print(f"[FAIL] 第 {attempt+1} 次失败。等待 {delay}s 后重试...")
        time.sleep(delay)

    # 全部失败，生成报告
    report = generate_error_report(failures)
    report_path = Path(__file__).resolve().parent.parent / "reports" / "download_error_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[ERROR] {MAX_RETRIES} 次重试全部失败。")
    print(f"[INFO] 错误报告已保存: {report_path}")
    print(report)
    sys.exit(1)


if __name__ == "__main__":
    main()
