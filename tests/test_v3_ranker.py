import numpy as np
import pandas as pd
import pytest
from alphapulse.ranking.stock_ranker import (
    winsorize, zscore_normalize, rank_stocks
)


# ---------------------------------------------------------------------------
# winsorize
# ---------------------------------------------------------------------------

def test_winsorize():
    """Extreme values are clipped to the specified percentile bounds."""
    s = pd.Series([-100.0, 1.0, 2.0, 3.0, 4.0, 5.0, 100.0], dtype=float)
    result = winsorize(s, lower_pct=0.01, upper_pct=0.99)
    assert result.iloc[0] > -100.0   # clipped up
    assert result.iloc[-1] < 100.0   # clipped down
    # non-extreme values should be untouched
    assert result.iloc[1] == 1.0
    assert result.iloc[2] == 2.0
    assert result.iloc[-2] == 5.0


# ---------------------------------------------------------------------------
# zscore_normalize
# ---------------------------------------------------------------------------

def test_zscore():
    """Z-scored series has mean ≈ 0 and std ≈ 1."""
    np.random.seed(42)
    s = pd.Series(np.random.randn(1000) * 5 + 10)
    z = zscore_normalize(s)
    assert abs(z.mean()) < 1e-10
    assert abs(z.std() - 1.0) < 1e-10


def test_zscore_constant():
    """A constant series returns all zeros."""
    s = pd.Series([3.0] * 20)
    z = zscore_normalize(s)
    assert (z == 0.0).all()


# ---------------------------------------------------------------------------
# rank_stocks
# ---------------------------------------------------------------------------

def test_rank_stocks_basic():
    """Four stocks are ranked correctly by weighted composite score."""
    df = pd.DataFrame({
        "symbol": ["A", "B", "C", "D"],
        "name": ["a", "b", "c", "d"],
        "f1": [10.0, 20.0, 30.0, 40.0],   # higher is better
        "f2": [0.2, 0.3, 0.4, 0.5],       # higher is better → D wins both
    })
    weights = {"f1": 1.0, "f2": 1.0}
    result = rank_stocks(df, weights, top_pct=1.0)

    assert len(result) == 4
    assert list(result.columns) == [
        "symbol", "name", "score", "raw_score", "rank", "top_factors",
        "sector", "reason"
    ]
    # ranks should be 1..4
    assert result["rank"].tolist() == [1, 2, 3, 4]
    # highest raw inputs → highest score → rank 1
    assert result["symbol"].iloc[0] == "D"   # f1=40, f2=0.2 → highest
    assert result["symbol"].iloc[-1] == "A"  # f1=10, f2=0.5 → lowest
    assert (result["score"] >= 0).all() and (result["score"] <= 100).all()


def test_rank_stocks_top50():
    """Ten stocks are filtered down to 5 (top 50%)."""
    np.random.seed(7)
    n = 10
    df = pd.DataFrame({
        "symbol": [chr(65 + i) for i in range(n)],  # A-J
        "name": [f"stock_{i}" for i in range(n)],
        "f1": np.random.randn(n) * 5 + 50,
        "f2": np.random.rand(n) * 10,
    })
    weights = {"f1": 1.0, "f2": 1.0}
    result = rank_stocks(df, weights, top_pct=0.5)

    assert len(result) == 5
    assert result["rank"].tolist() == [1, 2, 3, 4, 5]
    assert result["score"].is_monotonic_decreasing


def test_rank_stocks_empty_weights():
    """Empty factor_weights returns an empty DataFrame with correct columns."""
    df = pd.DataFrame({
        "symbol": ["X"],
        "name": ["x"],
        "f1": [1.0],
    })
    result = rank_stocks(df, {}, top_pct=1.0)
    assert result.empty
    assert list(result.columns) == [
        "symbol", "name", "score", "raw_score", "rank", "top_factors",
        "sector", "reason"
    ]
