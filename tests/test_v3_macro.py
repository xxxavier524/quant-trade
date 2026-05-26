import pandas as pd
import numpy as np
import pytest
from alphapulse.market.macro_position import (
    compute_ma_alignment_score, compute_volume_price_score,
    compute_sentiment_score, compute_northbound_score,
    classify_macro_level, compute_macro_score
)

@pytest.fixture
def bull_df():
    n = 100
    close = np.linspace(10, 20, n) + np.random.randn(n) * 0.1
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"date": dates, "close": close, "volume": np.random.randint(1e7, 5e7, n) * 1.0})

def test_ma_alignment_bull(bull_df):
    score = compute_ma_alignment_score(bull_df)
    assert 20 <= score <= 25

def test_ma_alignment_short_data():
    df = pd.DataFrame({"close": [10, 11, 12]})
    score = compute_ma_alignment_score(df)
    assert score == 12.5

def test_volume_price_score(bull_df):
    score = compute_volume_price_score(bull_df)
    assert 0 <= score <= 25

def test_sentiment_score():
    score = compute_sentiment_score(3000, 2000, 50, 5)
    assert score > 12.5

def test_sentiment_score_bearish():
    score = compute_sentiment_score(1000, 4000, 5, 50)
    assert score < 12.5

def test_northbound_score():
    score = compute_northbound_score([5e8, 3e8, 2e8, 1e8, 0.5e8])
    assert score > 15

def test_classify_bull():
    assert classify_macro_level(85) == "多头"

def test_classify_bear():
    assert classify_macro_level(15) == "空头"

def test_compute_macro_score_basic(bull_df):
    result = compute_macro_score(bull_df, bull_df, bull_df)
    assert "score" in result
    assert "level" in result
    assert 0 <= result["score"] <= 100
