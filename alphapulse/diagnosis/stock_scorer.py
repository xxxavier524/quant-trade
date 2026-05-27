"""Five-dimension stock scoring system (0-100 -> S/A/B/C/D)."""
import pandas as pd
import numpy as np

DEFAULT_WEIGHTS = {"technical": 30, "volume": 20, "pattern": 20, "risk": 15, "sector": 15}
GRADE_THRESHOLDS = {"S": 85, "A": 70, "B": 55, "C": 40}


def score_technical(factor_snapshot: dict) -> float:
    score = 0.0
    if factor_snapshot.get("WEEKLY_MA_BULL", 0):
        score += 10
    kdj = factor_snapshot.get("KDJ_J_LOW", 0)
    if kdj:
        score += 10
    # No score if KDJ not triggered - don't penalize, but don't reward
    if factor_snapshot.get("MACD_BULL_DEAD", 0):
        score += 10
    return min(score, 30)


def score_volume(factor_snapshot: dict) -> float:
    score = 0.0
    if factor_snapshot.get("ABNORMAL_VOL", 0):
        score += 7
    if factor_snapshot.get("VOL_CONT_SHRINK", 0) or factor_snapshot.get("SHRINK_TO_ABNORMAL", 0):
        score += 7
    if factor_snapshot.get("DOUBLE_VOLUME_BAR", 0):
        score += 6
    return min(score, 20)


def score_pattern(factor_snapshot: dict) -> float:
    score = 0.0
    if factor_snapshot.get("N_STRUCT", 0):
        score += 8
    if factor_snapshot.get("BRICK_INDICATOR", 0):
        score += 6
    if factor_snapshot.get("KEY_KLINE", 0) or factor_snapshot.get("VIOLENT_KLINE", 0):
        score += 6
    return min(score, 20)


def score_risk(factor_snapshot: dict) -> float:
    score = 15.0
    s1 = factor_snapshot.get("S1_SELL_SIGNAL", 0)
    dd = factor_snapshot.get("DD_SELL_SIGNAL", 0)
    if s1 >= 2:
        score -= 10
    elif s1 == 1:
        score -= 5
    if dd >= 2:
        score -= 5
    elif dd == 1:
        score -= 3
    return max(0, score)


def score_sector_resonance(sector_strength_score: float, rank_in_sector: int, total_in_sector: int) -> float:
    score = 0.0
    score += min(sector_strength_score / 100 * 8, 8)
    if total_in_sector > 0:
        score += (1 - rank_in_sector / total_in_sector) * 7
    return min(score, 15)


def compute_diagnosis(factor_snapshot: dict, sector_strength_score: float = 50,
                      rank_in_sector: int = 1, total_in_sector: int = 1, weights: dict = None) -> dict:
    w = weights or DEFAULT_WEIGHTS
    subs = {
        "technical": score_technical(factor_snapshot),
        "volume": score_volume(factor_snapshot),
        "pattern": score_pattern(factor_snapshot),
        "risk": score_risk(factor_snapshot),
        "sector": score_sector_resonance(sector_strength_score, rank_in_sector, total_in_sector),
    }
    max_subs = {"technical": 30, "volume": 20, "pattern": 20, "risk": 15, "sector": 15}
    total = sum(subs[k] * w[k] / 100 for k in subs)
    max_possible_raw = sum(max_subs[k] * w[k] / 100 for k in max_subs)
    total_scaled = round(total / max_possible_raw * 100, 1) if max_possible_raw > 0 else 0
    grade = "D"
    for g, t in sorted(GRADE_THRESHOLDS.items(), key=lambda x: x[1], reverse=True):
        if total_scaled >= t:
            grade = g
            break
    dim_scores = {k: round(subs[k] * w[k] / sum(w.values()) * 100, 1) for k in subs}
    return {
        "total_score": total_scaled,
        "grade": grade,
        "sub_scores": {k: round(v, 1) for k, v in subs.items()},
        "dim_contributions": dim_scores,
        "top_dimensions": sorted(dim_scores, key=dim_scores.get, reverse=True)[:3],
    }
