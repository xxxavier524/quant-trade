"""P1: agent 决策对账幂等写入单测（write_reconciliation_block）。

修复每天无条件 append 导致同日重复块、且早于晚间数据的过时块留存的问题。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from review_agent_decisions import write_reconciliation_block  # noqa: E402


def test_dedupes_existing_today_blocks_and_preserves_others(tmp_path):
    rpt = tmp_path / "daily_auto_report.md"
    today = "2026-07-23"
    # 预置：一个别的小节 + 两个重复的今日块（模拟历史双写）
    rpt.write_text(
        "## 自动调参周检 2026-07-19\n旧内容\n"
        f"\n## Agent决策对账 {today}\n旧块1\n"
        f"\n## Agent决策对账 {today}\n旧块2\n",
        encoding="utf-8")
    new_block = f"\n## Agent决策对账 {today} ⚠️STALE\n新块内容\n"
    write_reconciliation_block(rpt, today, new_block)
    text = rpt.read_text(encoding="utf-8")
    assert text.count(f"## Agent决策对账 {today}") == 1   # 只剩一个今日块
    assert "新块内容" in text and "旧块1" not in text and "旧块2" not in text
    assert "自动调参周检" in text and "旧内容" in text     # 其它小节保留


def test_appends_when_absent(tmp_path):
    rpt = tmp_path / "daily_auto_report.md"
    rpt.write_text("## 别的小节\nx\n", encoding="utf-8")
    write_reconciliation_block(rpt, "2026-07-23", "\n## Agent决策对账 2026-07-23\nY\n")
    text = rpt.read_text(encoding="utf-8")
    assert "别的小节" in text and "## Agent决策对账 2026-07-23" in text


def test_creates_when_missing(tmp_path):
    rpt = tmp_path / "new.md"
    write_reconciliation_block(rpt, "2026-07-23", "\n## Agent决策对账 2026-07-23\nZ\n")
    assert rpt.exists() and "Z" in rpt.read_text(encoding="utf-8")


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
