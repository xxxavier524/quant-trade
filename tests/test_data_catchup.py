"""data_catchup.plan 状态机单测——保证：数据够才选股、只选一次、最后窗口才告警、只告警一次。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from data_catchup import (  # noqa: E402
    plan, DONE_THRESHOLD, SELECT_MIN, FINAL_HOUR,
    BUDGET_SEC, INDEX_SEC, SELECT_RESERVE_SEC, ATTEMPT_MIN)


def _plist_hard_timeout() -> int:
    """从 launchd plist 读 run_with_timeout 的硬超时秒数。"""
    import re
    p = Path(__file__).resolve().parent.parent / "config" / "com.alphapulse.data-catchup.plist"
    txt = p.read_text(encoding="utf-8")
    m = re.search(r"run_with_timeout\.py</string>\s*<string>(\d+)</string>", txt)
    assert m, "plist 中未找到 run_with_timeout 硬超时"
    return int(m.group(1))


def test_budget_fits_inside_plist_hard_timeout():
    """回归(2026-07-27事故)：索引180+续传2700+选股1200=4080s > 硬超时3300s → 必被SIGTERM。
    总预算必须小于 plist 硬超时，且各步之和不超过总预算。"""
    hard = _plist_hard_timeout()
    assert BUDGET_SEC < hard, f"总预算 {BUDGET_SEC}s 必须小于 plist 硬超时 {hard}s"
    worst = INDEX_SEC + (BUDGET_SEC - INDEX_SEC - SELECT_RESERVE_SEC) + SELECT_RESERVE_SEC
    assert worst <= BUDGET_SEC, f"各步预算之和 {worst}s 超过总预算 {BUDGET_SEC}s"
    # 续传软限（分钟）须留出余量，保证 daily_update 自存进度后才可能被硬杀
    assert ATTEMPT_MIN * 60 < BUDGET_SEC - INDEX_SEC - SELECT_RESERVE_SEC + 120

FRESH = {"selection_done": False, "final_alerted": False}


def test_complete_triggers_selection_once_no_alert():
    a = plan(0.95, 16, dict(FRESH))
    assert a["run_selection"] is True and a["notify"] is None


def test_complete_but_already_selected_is_noop():
    a = plan(0.95, 20, {"selection_done": True, "final_alerted": False})
    assert a["run_selection"] is False and a["notify"] is None


def test_incomplete_midwindow_is_silent_retry():
    a = plan(0.30, 17, dict(FRESH))  # 未达标、非最后窗口
    assert a["run_selection"] is False and a["notify"] is None


def test_final_window_enough_to_select_gives_partial_notice():
    cov = (SELECT_MIN + DONE_THRESHOLD) / 2  # ≥SELECT_MIN 但 <DONE
    a = plan(cov, FINAL_HOUR, dict(FRESH))
    assert a["run_selection"] is True and a["notify"] == "partial"


def test_final_window_too_low_alerts_once_and_does_not_select():
    # 铁律：覆盖率 < 选股下限时绝不选股（不在陈旧数据上操作），只首次告警
    a = plan(0.40, FINAL_HOUR + 1, dict(FRESH))
    assert a["run_selection"] is False and a["notify"] == "fail"
    # 已告警过则不再重复
    a2 = plan(0.40, FINAL_HOUR + 1, {"selection_done": False, "final_alerted": True})
    assert a2["notify"] is None and a2["run_selection"] is False


def test_boundary_done_threshold_is_complete():
    assert plan(DONE_THRESHOLD, 23, dict(FRESH))["notify"] is None


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
