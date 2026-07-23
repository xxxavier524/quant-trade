"""data_catchup.plan 状态机单测——保证：数据够才选股、只选一次、最后窗口才告警、只告警一次。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from data_catchup import plan, DONE_THRESHOLD, SELECT_MIN, FINAL_HOUR  # noqa: E402

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
