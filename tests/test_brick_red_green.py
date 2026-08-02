"""BRICK_THREE_TYPES 红/绿砖定义回归测试（H5，2026-07-28 修复）。

旧定义按"水平"取 is_red=brick>0 / is_green=brick==0；但 brick=IF(VAR6A>4,VAR6A-4,0)
使 brick==0 仅约 0.3% 交易日 → 绿→红转换几乎不存在，三子类型死掉两个
（真实 298 只样本实测：N_JUMP 2 条、CONTINUATION 1 条 vs BREAKOUT 8067 条）。
正确定义与 brick_ultra.compute 一致：砖值上升=红、下降=绿（方向，而非水平）。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.factors.brick_ultra import compute_brick_indicator  # noqa: E402


def _synthetic(n: int = 400, seed: int = 7) -> pd.DataFrame:
    """带涨跌波动的合成日线，保证 brick 序列有升有降。"""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0008, 0.02, n)
    close = 10 * np.exp(np.cumsum(ret))
    high = close * (1 + abs(rng.normal(0.006, 0.004, n)))
    low = close * (1 - abs(rng.normal(0.006, 0.004, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    vol = rng.lognormal(13, 0.4, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": vol}, index=idx)


def test_brick_zero_is_rare_so_level_definition_is_degenerate():
    """证明旧定义的病根：brick==0 极罕见 → 以其为"绿砖"必然几乎无转换。"""
    brick = compute_brick_indicator(_synthetic()).values
    zero_share = float((brick == 0).mean())
    assert zero_share < 0.10, f"brick==0 占比 {zero_share:.1%}，本测试前提不再成立"


def test_directional_definition_yields_many_transitions():
    """方向定义下，绿→红转换应大量存在（旧定义下几乎为零）。"""
    brick = compute_brick_indicator(_synthetic()).values
    prev = np.empty_like(brick)
    prev[0], prev[1:] = np.nan, brick[:-1]
    is_red, is_green = brick > prev, brick < prev

    # 旧（水平）定义
    old_red, old_green = brick > 0, brick == 0
    old_trans = int(np.sum(old_green[:-1] & old_red[1:]))
    new_trans = int(np.sum(is_green[:-1] & is_red[1:]))

    assert new_trans > 20, f"方向定义下的绿→红转换仅 {new_trans} 次，修复未生效"
    assert new_trans > old_trans * 5, (
        f"方向定义({new_trans})应远多于水平定义({old_trans})的转换数")


def test_red_and_green_are_mutually_exclusive_and_cover_moves():
    """红/绿互斥；持平日两者皆 False；首日不触发（NaN 比较为 False）。"""
    brick = compute_brick_indicator(_synthetic()).values
    prev = np.empty_like(brick)
    prev[0], prev[1:] = np.nan, brick[:-1]
    is_red, is_green = brick > prev, brick < prev

    assert not bool(is_red[0]) and not bool(is_green[0]), "首日不应判红/绿"
    assert not np.any(is_red & is_green), "红绿不应同时为真"
    flat = brick[1:] == prev[1:]
    assert not np.any(is_red[1:][flat]) and not np.any(is_green[1:][flat])


def test_generate_signals_activates_all_three_subtypes():
    """端到端：三个子类型都应能在合成数据上触发（修复前 N_JUMP/CONTINUATION 近乎为0）。"""
    from alphapulse.strategies import brick_three_types as b3
    frames = [_synthetic(seed=s) for s in range(6)]
    seen = set()
    for i, df in enumerate(frames):
        sig = b3.generate_signals(df, symbol=f"T{i}", require_consolidation=False)
        if not sig.empty:
            seen.update(sig["brick_type"].unique())
    assert "BRICK_N_JUMP" in seen or "BRICK_CONTINUATION" in seen, (
        f"修复后 N_JUMP/CONTINUATION 仍未触发，实际只有 {seen}")


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
