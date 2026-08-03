"""v5 B2/B3 分级徽章测试（2026-08-03）。

验证：B1_B2_B3 递进阶段进入每日选股输出（b1b2b3_stage / sig_b2 / sig_b3），
B2/B3 归入"基本面法"战法家族（成功率追踪口径一致）。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.ranking.composite import _b1b2b3_stage, build_stock_row  # noqa: E402
from alphapulse.tracking.signal_tracker import load_families  # noqa: E402


def _mk_df(n: int = 320) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=n)
    close = 10 + np.sin(np.arange(n) / 8) + np.arange(n) * 0.001
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": np.full(n, 1e6),
    })


def test_b1b2b3_stage_last_bar(monkeypatch):
    """末行 B3 信号 → 徽章返回 B3；无信号 → 空串。"""
    import alphapulse.strategies.b1_b2_b3_strategy as b123

    def fake_gen(data, symbol="", **kw):
        return pd.DataFrame({"signal": [0, 1],
                             "signal_type": ["B1", "B3"]},
                            index=[data.index[0], data.index[-1]])

    monkeypatch.setattr(b123, "generate_signals", fake_gen)
    df = _mk_df()
    assert _b1b2b3_stage(df) == "B3"

    def fake_none(data, symbol="", **kw):
        return pd.DataFrame(columns=["symbol", "date", "signal",
                                     "strategy", "signal_type",
                                     "confidence", "factor_snapshot"])

    monkeypatch.setattr(b123, "generate_signals", fake_none)
    assert _b1b2b3_stage(df) == ""


def test_build_stock_row_has_badges():
    row = build_stock_row("600000", "测试", _mk_df())
    assert row is not None
    assert "b1b2b3_stage" in row
    assert row["sig_b2"] is False or row["sig_b2"] is True
    assert row["sig_b3"] is False or row["sig_b3"] is True


def test_b2b3_in_basic_family():
    fams = load_families()
    assert "B2确认" in fams["基本面法"]
    assert "B3锁仓" in fams["基本面法"]
