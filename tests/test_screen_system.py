"""v5 纯选股成功率系统测试（2026-08-02）。

覆盖：评估器口径（机会命中/基线/样本门槛/右删失）、策略注册表包装、
screen_bt 报告端到端、screen_optimize 优化流程（小网格冒烟）。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.screening.evaluator import (  # noqa: E402
    evaluate_strategy, forward_outcome, signal_dates_of, wilson_lower,
    cross_sectional_base_rates,
)
from alphapulse.screening.strategies import (  # noqa: E402
    SCREENING_STRATEGIES, run_strategy,
)


def _mk_df(n: int = 320, start: str = "2025-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=n)
    close = 10 + np.sin(np.arange(n) / 8) + np.arange(n) * 0.001
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": np.full(n, 1e6),
    })


def test_signal_dates_of_maps_range_index():
    df = _mk_df()
    sig = pd.DataFrame({"signal": 0}, index=df.index)
    sig.loc[10, "signal"] = 1
    sig.loc[20, "signal"] = 1
    assert signal_dates_of(sig, df) == [df["date"].iloc[10], df["date"].iloc[20]]


def test_forward_outcome_censoring_and_metrics():
    closes = pd.Series([10, 10.5, 10.2, 11.0, 10.0, 10.6, 10.8],
                       index=[f"d{i}" for i in range(7)])
    out = forward_outcome(["d0", "d5", "d99"], closes, horizon=5, success_pct=5.0)
    assert len(out) == 1                    # d5/d99 右删失丢弃
    o = out[0]
    assert o.success is True                # d1=+5.0% 触及
    assert o.end_ret == pytest.approx(6.0)  # d5 收盘 10.6 → +6%
    assert o.max_ret == pytest.approx(10.0) # 最高 11.0 → +10%
    assert o.min_ret == 0.0                 # 未来5日最低收盘 10.0 → 0%


def test_evaluate_strategy_baseline_and_min_signals():
    idx = [f"d{j}" for j in range(60)]
    # s0 信号日起就涨，s1/s2 信号日起就跌 → 基线=1/3，策略（只选 s0）成功率 100%
    closes_map = {"s0": pd.Series(np.concatenate([[10.0], np.full(59, 11.0)]), index=idx),
                  "s1": pd.Series(np.concatenate([[10.0], np.full(59, 9.0)]), index=idx),
                  "s2": pd.Series(np.concatenate([[10.0], np.full(59, 9.0)]), index=idx)}
    r = evaluate_strategy({"s0": ["d0"]}, closes_map,
                          horizon=5, success_pct=5.0, min_signals=1)
    assert r["success_rate"] == 100.0
    assert r["base_rate"] == 33.33
    assert r["lift_pp"] == 66.67
    # 样本门槛
    r2 = evaluate_strategy({"s0": ["d0"]}, closes_map,
                           horizon=5, success_pct=5.0, min_signals=100)
    assert r2["success_rate"] is None and "样本不足" in r2["reason"]


def test_wilson_lower_bounds():
    assert wilson_lower(50.0, 100) < 50.0
    assert wilson_lower(0.0, 0) is None


def test_cross_sectional_base_rates():
    closes_map = {"a": pd.Series([10, 11, 11, 11, 11, 11],
                                 index=list("abcdef")),
                  "b": pd.Series([10, 10, 10, 10, 10, 10],
                                 index=list("abcdef"))}
    base = cross_sectional_base_rates(["a"], closes_map, horizon=5, success_pct=5.0)
    assert base["a"] == 50.0


def test_registry_wrappers():
    df = _mk_df()
    for name in ["B1_FORMULA", "NEEDLE", "VOLUME_B1", "ZHIXING_ULTRA"]:
        frame = run_strategy(name, df)
        assert "signal" in frame.columns
        hit = frame.index[frame["signal"] == 1].tolist()
        assert signal_dates_of(frame, df) == [df["date"].iloc[i] for i in hit]
    assert "B1_B2_B3" in SCREENING_STRATEGIES


def test_screen_bt_report_end_to_end(tmp_path):
    import screen_bt
    for i in range(3):
        df = _mk_df(320, "2025-01-02")
        df.to_csv(tmp_path / f"s{i:02d}.csv", index=False)
    out = tmp_path / "report.md"
    old_argv = sys.argv
    sys.argv = ["screen_bt", "--strategies", "NEEDLE,B1_FORMULA",
                "--sample", "3", "--data-dir", str(tmp_path),
                "--min-days", "300", "--out", str(out), "--seed", "1"]
    try:
        code = screen_bt.main()
    finally:
        sys.argv = old_argv
    assert code == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "NEEDLE" in text and "B1_FORMULA" in text
    assert "因果门禁" in text


def test_screen_optimize_smoke(tmp_path, monkeypatch):
    import screen_optimize
    for i in range(3):
        df = _mk_df(1100, "2022-01-03")
        df.to_csv(tmp_path / f"s{i:02d}.csv", index=False)
    # 缩小网格加速测试
    monkeypatch.setitem(screen_optimize.GRIDS, "NEEDLE_WASHOUT", {
        "j_threshold": [20, 25],
        "shadow_mult": [3.0],
        "volume_shrink_ratio": [0.85],
        "fib_min": [0.2],
    })
    old = sys.argv
    sys.argv = ["screen_optimize", "--strategy", "NEEDLE_WASHOUT",
                "--sample", "3", "--data-dir", str(tmp_path),
                "--min-lift", "-100", "--min-improve", "-100",
                "--seed", "1"]
    try:
        code = screen_optimize.main()
    finally:
        sys.argv = old
    # 无有效窗（窗口内信号不足）也属于正常退出；关键是流程不崩
    assert code in (0, 1)
    # 回归：链式回测成功率是百分数，报告里不得出现 ×100 后的荒谬值（曾输出 2406%）
    report = (PROJECT_ROOT / "reports" / "screen_optimize_NEEDLE_WASHOUT.md")
    if report.exists():
        text = report.read_text(encoding="utf-8")
        assert "2406" not in text, "链式成功率被错误地乘了100"
