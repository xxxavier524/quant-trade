"""ZG_B1_BRICK 融合选股策略测试。"""

import numpy as np
import pandas as pd
import pytest

from alphapulse.strategies import zg_b1_brick
from alphapulse.factors.factor_registry import compute_factor, FACTOR_REGISTRY


def _synth(n=200, seed=0):
    """构造一段有涨有跌的日线，保证因子可计算。"""
    rng = np.random.default_rng(seed)
    close = 10 + np.cumsum(rng.normal(0, 0.2, n))
    close = np.abs(close) + 5
    high = close + np.abs(rng.normal(0, 0.15, n))
    low = close - np.abs(rng.normal(0, 0.15, n))
    open_ = close + rng.normal(0, 0.1, n)
    vol = np.abs(rng.normal(1e6, 3e5, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def test_compute_returns_bool_series_aligned():
    df = _synth()
    sig = zg_b1_brick.compute(df)
    assert isinstance(sig, pd.Series)
    assert sig.dtype == bool
    assert sig.index.equals(df.index)


def test_short_history_returns_empty():
    df = _synth(n=100)
    gs = zg_b1_brick.generate_signals(df, symbol="TEST")
    assert list(gs.columns) == zg_b1_brick._OUT_COLS
    assert len(gs) == 0


def test_registry_path_matches_direct_call():
    df = _synth(seed=3)
    direct = zg_b1_brick.compute(df)
    viareg = compute_factor("ZG_B1_BRICK", df)
    assert (direct == viareg).all()


def test_registered_as_selection():
    entry = FACTOR_REGISTRY["ZG_B1_BRICK"]
    assert entry["type"] == "selection"
    assert entry["module"] is zg_b1_brick


def test_signals_confined_to_brick_early_cycle():
    """require_brick_early=True 时，所有信号日必须处于第1~early_max红砖，且非尾段。"""
    df = _synth(seed=7)
    gs = zg_b1_brick.generate_signals(df, symbol="TEST", early_max=2, late_from=4)
    if len(gs) == 0:
        pytest.skip("该随机序列无信号")
    assert (gs["brick_position"] >= 1).all()
    assert (gs["brick_position"] <= 2).all()


def test_discipline_card_fields_present():
    """每个信号必须带 Z哥纪律卡：止损线、置信度、离场提示。"""
    df = _synth(seed=7)
    gs = zg_b1_brick.generate_signals(df, symbol="TEST")
    if len(gs) == 0:
        pytest.skip("该随机序列无信号")
    r = gs.iloc[-1]
    assert r["stop_loss"] < r["factor_snapshot"]["close"]   # 止损低于现价
    assert 0.0 < r["confidence"] <= 1.0
    assert r["exit_hint"] in ("", "S1卖出", "四砖尾段减仓")


def test_no_brick_mode_is_superset():
    """关闭砖型图早段约束后，信号数应 >= 强制早段的信号数。"""
    df = _synth(seed=11)
    strict = zg_b1_brick.compute(df, require_brick_early=True)
    loose = zg_b1_brick.compute(df, require_brick_early=False)
    assert int(loose.sum()) >= int(strict.sum())
    # loose 覆盖 strict（strict 为真处 loose 必为真）
    assert (loose | ~strict).all()
