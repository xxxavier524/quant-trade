"""run_walk_forward 覆盖在任参数的门槛（2026-07-28 修正）。

此前无条件写入本轮网格第一名 → 固定随机抽样 + 噪声较大的命中率目标下，
重跑很容易用"这轮碰巧最高"的参数替换掉更稳健的在任参数（生产参数漂移）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_walk_forward import should_replace  # noqa: E402

NEG_INF = float("-inf")


def test_writes_when_no_incumbent():
    assert should_replace(0.10, NEG_INF, 0.02) is True


def test_blocks_marginal_improvement_within_noise():
    # 在任 0.2388（best_params 里 BRICK 的实际值），新 0.2450 只高 0.006 → 属噪声
    assert should_replace(0.2450, 0.2388, 0.02) is False


def test_allows_clear_improvement():
    assert should_replace(0.2700, 0.2388, 0.02) is True


def test_blocks_worse_score():
    assert should_replace(0.1500, 0.2388, 0.02) is False


def test_force_write_overrides_gate():
    assert should_replace(0.0100, 0.9000, NEG_INF) is True


def test_exact_threshold_is_not_enough():
    """必须严格大于 在任+容忍，等于不算改善。"""
    assert should_replace(0.2588, 0.2388, 0.02) is False


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
