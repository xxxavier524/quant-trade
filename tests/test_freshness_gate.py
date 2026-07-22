"""P0 数据新鲜度硬闸单测（daily_screener._freshness_verdict）。

覆盖：落后指数基准=abort / 覆盖率<硬阈值=abort / 介于软硬阈值=degraded /
新鲜且高覆盖=ok / 无指数基准时不误判落后。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from daily_screener import (  # noqa: E402
    _freshness_verdict, HARD_MIN_COVERAGE, SOFT_MIN_COVERAGE)


def test_lagging_index_aborts():
    # 选股池最新交易日落后于指数基准 → 无论覆盖率多高都中止
    action, reason = _freshness_verdict("2026-07-16", "2026-07-22", 1.0)
    assert action == "abort"
    assert "落后于基准指数" in reason


def test_low_coverage_aborts():
    action, _ = _freshness_verdict("2026-07-22", "2026-07-22", HARD_MIN_COVERAGE - 0.01)
    assert action == "abort"


def test_mid_coverage_degraded():
    cov = (HARD_MIN_COVERAGE + SOFT_MIN_COVERAGE) / 2
    action, _ = _freshness_verdict("2026-07-22", "2026-07-22", cov)
    assert action == "degraded"


def test_fresh_high_coverage_ok():
    action, reason = _freshness_verdict("2026-07-22", "2026-07-22", 0.95)
    assert action == "ok"
    assert reason == ""


def test_no_index_ref_uses_coverage_only():
    # 无指数基准（ref_date=None）时不因"落后"误判，仅按覆盖率
    assert _freshness_verdict("2026-07-22", None, 0.95)[0] == "ok"
    assert _freshness_verdict("2026-07-22", None, 0.3)[0] == "abort"


def test_target_ahead_of_ref_is_ok():
    # 选股池比指数还新（个股已出T日、指数暂缺）→ 不算落后
    assert _freshness_verdict("2026-07-22", "2026-07-21", 0.95)[0] == "ok"


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
