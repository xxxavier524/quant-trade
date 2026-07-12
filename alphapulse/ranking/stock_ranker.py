"""
Stock Ranker - Winsorize + Z-score normalization + Weighted composite score.

Produces a ranked list of stocks with Top N% filtering, macro-level
adjustment, sector annotation, and explanatory reason strings.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


def winsorize(series: pd.Series, lower_pct: float = 0.01,
              upper_pct: float = 0.99) -> pd.Series:
    """Clip a series at the given lower / upper percentiles.

    Parameters
    ----------
    series : pd.Series
        Numeric values to winsorize.
    lower_pct : float
        Lower percentile threshold (default 0.01).
    upper_pct : float
        Upper percentile threshold (default 0.99).

    Returns
    -------
    pd.Series
        Clipped series (same length, same index).
    """
    lower = series.quantile(lower_pct)
    upper = series.quantile(upper_pct)
    return series.clip(lower=lower, upper=upper)


def zscore_normalize(series: pd.Series) -> pd.Series:
    """Z-score normalize a series: (x - mean) / std.

    Returns all zeros when std is zero (constant series).

    Parameters
    ----------
    series : pd.Series
        Numeric values to normalize.

    Returns
    -------
    pd.Series
        Normalized series (μ ≈ 0, σ ≈ 1).
    """
    std = series.std()
    if std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _build_reason(top_factors: str, macro_note: str, sector_note: str) -> str:
    """Build a human-readable reason string from piece parts."""
    parts = []
    if top_factors:
        parts.append(top_factors)
    if macro_note:
        parts.append(f"宏观: {macro_note}")
    if sector_note:
        parts.append(f"板块: {sector_note}")
    if not parts:
        return "综合评分"
    return " | ".join(parts)


def rank_stocks(
    factor_df: pd.DataFrame,
    factor_weights: Dict[str, float],
    sector_strength_map: Optional[Dict[str, float]] = None,
    strong_sectors: Optional[List[str]] = None,
    macro_level: str = "震荡",
    top_pct: float = 0.5,
) -> pd.DataFrame:
    """Rank stocks by a weighted composite of winsorized + z-scored factors.

    Parameters
    ----------
    factor_df : pd.DataFrame
        Columns must include ``symbol`` and ``name``, plus one column per
        factor named in *factor_weights*.
    factor_weights : dict
        Mapping of factor column name -> weight (float).
    sector_strength_map : dict, optional
        Mapping of symbol -> sector label.
    strong_sectors : list, optional
        Sector labels considered "strong"; stocks not in these sectors are
        excluded from the output.
    macro_level : str
        One of ``多头``, ``震荡偏多``, ``震荡``, ``震荡偏空``, ``空头``.
        仅作展示语境，不参与打分（乘数已证明不改变排序，2026-07-11 移除）。
    top_pct : float
        Fraction of stocks to retain (0 < top_pct <= 1).  Default 0.5.

    Returns
    -------
    pd.DataFrame
        Columns: ``[symbol, name, score, rank, top_factors, sector, reason]``,
        sorted by *score* descending, with only the top *top_pct* of stocks.
    """
    # --- early exit ---
    if not factor_weights or factor_df.empty:
        return pd.DataFrame(
            columns=["symbol", "name", "score", "raw_score", "rank",
                     "top_factors", "sector", "reason"]
        )

    factor_cols = [c for c in factor_weights if c in factor_df.columns]
    if not factor_cols:
        return pd.DataFrame(
            columns=["symbol", "name", "score", "raw_score", "rank",
                     "top_factors", "sector", "reason"]
        )

    # --- 1. Winsorize + Z-score each factor column ---
    z_cols = {}
    for col in factor_cols:
        w = winsorize(factor_df[col])
        z_cols[col] = zscore_normalize(w)

    # --- 2. Weighted-sum composite score ---
    score = pd.Series(0.0, index=factor_df.index)
    weighted_contrib = {}
    for col in factor_cols:
        w = factor_weights.get(col, 0.0)
        contrib = z_cols[col] * w
        weighted_contrib[col] = contrib
        score = score + contrib

    # --- 3. Normalize to 0-100 ---
    s_min, s_max = score.min(), score.max()
    if s_max - s_min == 0:
        score_norm = pd.Series(50.0, index=score.index)
    else:
        score_norm = (score - s_min) / (s_max - s_min) * 100.0

    # --- (原第4步"大盘档位乘数"已移除：统一乘到 min-max 后的分数上是单调变换，
    # 排序与Top N毫无变化，只会在空头档把显示分推过100。macro_level 仅作展示。) ---

    # --- assemble result frame ---
    result = factor_df[["symbol", "name"]].copy()
    result["score"] = score_norm.round(2)
    # 原始加权z分：score 经 min-max 后只在当日截面内可比（每天最高≈100），
    # raw_score 保留绝对量纲供跨日对比与追踪库沉淀
    result["raw_score"] = score.round(4)

    # --- 5. Sector annotation & filtering ---
    if sector_strength_map is not None:
        result["sector"] = result["symbol"].map(sector_strength_map).fillna("")
    else:
        result["sector"] = ""

    if strong_sectors:
        result = result[result["sector"].isin(strong_sectors)].copy()

    if result.empty:
        return pd.DataFrame(
            columns=["symbol", "name", "score", "raw_score", "rank",
                     "top_factors", "sector", "reason"]
        )

    # --- 6. Top factors per stock (top 3 by contribution) ---
    top_factors_list = []
    for idx in result.index:
        contribs = {col: weighted_contrib[col].loc[idx] for col in factor_cols}
        top3 = sorted(contribs.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        top_str = ", ".join(
            f"{c}({v:+.2f})" for c, v in top3 if abs(v) > 1e-9
        )
        top_factors_list.append(top_str if top_str else "综合评分")
    result["top_factors"] = top_factors_list

    # --- 7. Sort by score desc → rank ---
    result = result.sort_values("score", ascending=False).reset_index(drop=True)
    result["rank"] = range(1, len(result) + 1)

    # --- 8. Top N% cutoff ---
    cutoff = max(1, int(np.ceil(len(result) * top_pct)))
    result = result.head(cutoff).copy()

    # --- 9. Reason string ---
    reasons = []
    for _, row in result.iterrows():
        sec_note = f"{row['sector']}强势" if row["sector"] and strong_sectors else ""
        reasons.append(_build_reason(row["top_factors"], "", sec_note))
    result["reason"] = reasons

    return result[["symbol", "name", "score", "raw_score", "rank", "top_factors",
                   "sector", "reason"]]
