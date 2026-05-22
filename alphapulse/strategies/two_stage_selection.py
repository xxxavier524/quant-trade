"""Two-Stage AI Quant Stock Selection Strategy.

Stage 1: Industry mainline rotation — rank industries by trend strength.
Stage 2: Within top industries, rank stocks by predicted β and select top N.

Combined logic:
1. Score all industries, select top-N "mainline" industries
2. For mainline industries, compute predicted β for all constituents
3. Select top-M stocks per industry by β
4. Rebalance monthly

Reference: AI量化选股模型 — 双层垂直AI体系
"""

import numpy as np
import pandas as pd
from datetime import datetime

from alphapulse.factors.industry_rotation import (
    build_industry_index, score_industry_trend,
    rank_industries, get_industry,
)
from alphapulse.factors.beta_fundamental import predict_beta, rank_stocks_by_beta


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    all_stocks: dict[str, pd.DataFrame] | None = None,
    top_industries: int = 5,
    stocks_per_industry: int = 10,
    rebalance_freq: str = "M",  # M=monthly, W=weekly
    min_trend_score: float = 0.45,
    industry_rankings: list[dict] | None = None,
    industry_indices: dict[str, pd.DataFrame] | None = None,
    pre_selected: set[str] | None = None,
    pre_beta: float | None = None,
    pre_trend_score: float | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Generate buy signals using two-stage selection.

    Args:
        data: OHLCV DataFrame for current stock
        symbol: stock code
        all_stocks: dict of all stock data (needed for industry ranking)
        top_industries: number of mainline industries to select
        stocks_per_industry: number of stocks per industry
        rebalance_freq: rebalance frequency
        min_trend_score: minimum industry trend score threshold

    Returns:
        DataFrame with columns [symbol, date, signal, industry, predicted_beta, ...]
    """
    # Fast-path: pre-computed selection (used by optimized backtest)
    if pre_selected is not None:
        if symbol not in pre_selected:
            return pd.DataFrame(columns=["symbol", "date", "signal", "strategy"])
        # Generate monthly/weekly signal dates
        if rebalance_freq == "M":
            signal_dates = list(data.groupby(data.index.to_period("M")).apply(lambda x: x.index[-1]))
        elif rebalance_freq == "W":
            signal_dates = list(data.groupby(data.index.to_period("W")).apply(lambda x: x.index[-1]))
        else:
            signal_dates = [data.index[-1]]
        signals = []
        for d in signal_dates:
            if d in data.index:
                signals.append({
                    "date": d, "symbol": symbol, "signal": 1,
                    "strategy": "TWO_STAGE_FAST",
                    "predicted_beta": round(pre_beta or 0, 4),
                    "industry_trend_score": round(pre_trend_score or 0, 4),
                })
        df = pd.DataFrame(signals)
        if len(df) > 0:
            df = df.set_index("date")
        return df

    if all_stocks is None or len(all_stocks) < 50:
        # Fallback: no industry context, use B1 formula
        from alphapulse.factors.b1_formula import compute as b1_compute
        signals = b1_compute(data)
        if isinstance(signals, pd.Series):
            result = pd.DataFrame({"date": signals.index, "signal": signals.astype(int)})
            result["symbol"] = symbol
            result["strategy"] = "TWO_STAGE_FALLBACK"
            return result[result["signal"] == 1][["symbol", "date", "signal", "strategy"]]
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy"])

    # Stage 1: Industry ranking (use pre-computed if provided)
    if industry_rankings is not None:
        rankings = industry_rankings
    else:
        rankings = rank_industries(all_stocks, min_constituents=5, top_n=top_industries)
    mainline_industries = set(r["industry"] for r in rankings if r["total"] >= min_trend_score)

    if not mainline_industries:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy"])

    # Check if this stock is in a mainline industry
    stock_industry = get_industry(symbol)
    if stock_industry not in mainline_industries:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy"])

    # Stage 2: β prediction for constituents in this industry
    industry_syms = [s for s in all_stocks if get_industry(s) == stock_industry]
    industry_stocks = {s: all_stocks[s] for s in industry_syms if s in all_stocks}

    # Build industry index returns for β calculation (use pre-computed if provided)
    if industry_indices is not None:
        indices = industry_indices
    else:
        indices = build_industry_index(all_stocks)
    industry_returns = indices.get(stock_industry, pd.DataFrame()).get("return") if stock_industry in indices else None

    # Predict β for this stock
    pred_beta_series = predict_beta(data, industry_returns)
    if len(pred_beta_series.dropna()) == 0:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy"])

    # Rank all stocks in industry by β
    ranked = rank_stocks_by_beta(industry_stocks, industry_returns, top_n=stocks_per_industry)
    selected_symbols = set(ranked["symbol"].tolist())

    if symbol not in selected_symbols:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy"])

    # Generate signals: last trading day of each rebalance period
    beta_latest = pred_beta_series.dropna().iloc[-1]

    if rebalance_freq == "M":
        # Monthly: last trading day of month
        month_ends = data.groupby(data.index.to_period("M")).apply(lambda x: x.index[-1])
        signal_dates = list(month_ends)
    elif rebalance_freq == "W":
        week_ends = data.groupby(data.index.to_period("W")).apply(lambda x: x.index[-1])
        signal_dates = list(week_ends)
    else:
        signal_dates = [data.index[-1]]

    # Get industry trend score
    ind_scores = {r["industry"]: r["total"] for r in rankings}
    trend_score = ind_scores.get(stock_industry, 0)

    signals = []
    for d in signal_dates:
        if d in data.index:
            signals.append({
                "date": d,
                "symbol": symbol,
                "signal": 1,
                "strategy": "TWO_STAGE",
                "industry": stock_industry,
                "industry_trend_score": round(trend_score, 4),
                "predicted_beta": round(beta_latest, 4),
            })

    df = pd.DataFrame(signals)
    if len(df) > 0:
        df = df.set_index("date")
    return df
