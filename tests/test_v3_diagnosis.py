import pytest
from alphapulse.diagnosis.stock_scorer import (
    compute_diagnosis,
    score_technical,
    score_volume,
    score_pattern,
    score_risk,
)
from alphapulse.diagnosis.llm_diagnosis import generate_diagnosis_summary


def test_score_technical_bullish():
    assert (
        score_technical({"WEEKLY_MA_BULL": 1, "KDJ_J_LOW": 1, "MACD_BULL_DEAD": 1})
        == 30
    )


def test_score_technical_empty():
    assert score_technical({}) == 3


def test_score_volume_full():
    assert (
        score_volume({"ABNORMAL_VOL": 1, "SHRINK_TO_ABNORMAL": 1, "DOUBLE_VOLUME_BAR": 1})
        == 20
    )


def test_score_risk_safe():
    assert score_risk({"S1_SELL_SIGNAL": 0, "DD_SELL_SIGNAL": 0}) == 15


def test_score_risk_s1_confirmed():
    assert score_risk({"S1_SELL_SIGNAL": 2, "DD_SELL_SIGNAL": 0}) == 5


def test_compute_diagnosis():
    snap = {
        "WEEKLY_MA_BULL": 1,
        "KDJ_J_LOW": 1,
        "MACD_BULL_DEAD": 1,
        "ABNORMAL_VOL": 1,
        "SHRINK_TO_ABNORMAL": 1,
        "N_STRUCT": 1,
        "S1_SELL_SIGNAL": 0,
        "DD_SELL_SIGNAL": 0,
    }
    result = compute_diagnosis(snap)
    assert "total_score" in result
    assert "grade" in result
    assert 0 <= result["total_score"] <= 100


def test_llm_summary_fallback():
    diag = {
        "total_score": 75,
        "grade": "A",
        "sub_scores": {},
        "top_dimensions": ["technical", "volume"],
    }
    summary = generate_diagnosis_summary("000001", "平安银行", diag)
    assert "平安银行" in summary
    assert "A" in summary
