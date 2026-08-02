"""FactorMonitor 因子列选取（2026-07-28 修正 f_ 前缀导致的空报告）。

旧实现 `if not col.startswith("f_"): continue`，而真实因子无一带该前缀
（j_low/vol_shrink/amplitude…）→ daily_update 报告恒为空，
"自动剔除失效因子"从未真正运行过。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.monitor.factor_monitor import FactorMonitor  # noqa: E402


def _frame(n=60, seed=3):
    rng = np.random.default_rng(seed)
    fwd = rng.normal(0, 0.03, n)
    return (pd.DataFrame({
        "symbol": [f"{i:06d}" for i in range(n)],   # 元数据，应跳过
        "sector": ["电子"] * n,                      # 非数值，应跳过
        "close": rng.uniform(5, 50, n),             # 元数据，应跳过
        "sig_b1": rng.integers(0, 2, n),            # 信号徽章，应跳过
        "j_low": fwd * 8 + rng.normal(0, 0.01, n),  # 真因子（与收益正相关）
        "vol_shrink": rng.normal(0, 1, n),          # 真因子（无关）
    }), pd.DataFrame({"forward_return": fwd}))


def test_real_factor_names_are_monitored():
    fdf, rdf = _frame()
    rep = FactorMonitor().daily_update(fdf, rdf)
    assert "j_low" in rep and "vol_shrink" in rep, f"真实因子未被监控: {list(rep)}"


def test_metadata_columns_excluded():
    fdf, rdf = _frame()
    rep = FactorMonitor().daily_update(fdf, rdf)
    for meta in ("symbol", "sector", "close", "sig_b1"):
        assert meta not in rep, f"元数据列 {meta} 不应被当作因子"


def test_explicit_factor_cols_respected():
    fdf, rdf = _frame()
    rep = FactorMonitor().daily_update(fdf, rdf, factor_cols=["j_low"])
    assert list(rep) == ["j_low"]


def test_legacy_f_prefix_still_supported():
    fdf, rdf = _frame()
    fdf = fdf.rename(columns={"j_low": "f_j_low"})
    rep = FactorMonitor().daily_update(fdf, rdf)
    assert "f_j_low" in rep


def test_predictive_factor_gets_higher_ic_than_noise():
    fdf, rdf = _frame()
    rep = FactorMonitor().daily_update(fdf, rdf)
    assert abs(rep["j_low"]["mean_ic_20d"]) > abs(rep["vol_shrink"]["mean_ic_20d"])


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
