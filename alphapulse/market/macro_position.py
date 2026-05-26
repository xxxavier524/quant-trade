"""Multi-dimensional market position scoring (0-100)."""
import pandas as pd
import numpy as np

def compute_ma_alignment_score(df: pd.DataFrame) -> float:
    close = df["close"]
    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    if pd.isna(ma60):
        return 12.5
    score = 0
    if ma5 > ma10: score += 8
    if ma10 > ma20: score += 8
    if ma20 > ma60: score += 9
    return score

def compute_volume_price_score(df: pd.DataFrame) -> float:
    if len(df) < 5:
        return 12.5
    recent = df.iloc[-5:]
    pct_chg = recent["close"].pct_change().dropna()
    vol_chg = recent["volume"].pct_change().dropna()
    score = 12.5
    for i in range(min(len(pct_chg), len(vol_chg))):
        if pct_chg.iloc[i] > 0 and vol_chg.iloc[i] > 0:
            score += 2.5
        elif pct_chg.iloc[i] > 0 and vol_chg.iloc[i] < 0:
            score -= 1.5
        elif pct_chg.iloc[i] < 0 and vol_chg.iloc[i] > 0:
            score -= 2.5
    return max(0, min(25, score))

def compute_sentiment_score(advancing: int, declining: int, limit_up: int, limit_down: int) -> float:
    total = advancing + declining
    if total == 0:
        return 12.5
    ad_ratio = advancing / total
    score = ad_ratio * 15
    if limit_up > limit_down * 3:
        score += 5
    elif limit_down > limit_up * 3:
        score -= 5
    lu_ld_ratio = limit_up / max(limit_down, 1)
    score += min(lu_ld_ratio * 2, 5)
    return max(0, min(25, score))

def compute_northbound_score(northbound_flow_days: list) -> float:
    if not northbound_flow_days:
        return 12.5
    score = 12.5
    total = sum(northbound_flow_days)
    if total > 0:
        score += min(total / 1e9 * 5, 7.5)
    else:
        score -= min(abs(total) / 1e9 * 5, 7.5)
    consecutive = 0
    for v in northbound_flow_days:
        if (total > 0 and v > 0) or (total < 0 and v < 0):
            consecutive += 1
        else:
            break
    score += consecutive * 1.0
    return max(0, min(25, score))

def classify_macro_level(score: float, thresholds: dict = None) -> str:
    if thresholds is None:
        thresholds = {"bull": 80, "slightly_bull": 60, "neutral": 40, "slightly_bear": 20}
    if score >= thresholds["bull"]: return "多头"
    elif score >= thresholds["slightly_bull"]: return "震荡偏多"
    elif score >= thresholds["neutral"]: return "震荡"
    elif score >= thresholds["slightly_bear"]: return "震荡偏空"
    else: return "空头"

def compute_macro_score(
    sh_index_df: pd.DataFrame, sz_index_df: pd.DataFrame, cyb_index_df: pd.DataFrame,
    advancing: int = 0, declining: int = 0, limit_up: int = 0, limit_down: int = 0,
    northbound_flows: list = None
) -> dict:
    northbound_flows = northbound_flows or []
    ma_scores = []
    for df in [sh_index_df, sz_index_df, cyb_index_df]:
        if df is not None and len(df) >= 60:
            ma_scores.append(compute_ma_alignment_score(df))
    ma_score = np.mean(ma_scores) if ma_scores else 12.5
    vp_score = compute_volume_price_score(sh_index_df) if sh_index_df is not None and len(sh_index_df) >= 5 else 12.5
    sent_score = compute_sentiment_score(advancing, declining, limit_up, limit_down)
    nb_score = compute_northbound_score(northbound_flows)
    total = ma_score + vp_score + sent_score + nb_score
    level = classify_macro_level(total)
    return {
        "score": round(total, 1), "level": level,
        "sub_scores": {"ma_alignment": round(ma_score, 1), "volume_price": round(vp_score, 1),
                       "sentiment": round(sent_score, 1), "northbound": round(nb_score, 1)}
    }
