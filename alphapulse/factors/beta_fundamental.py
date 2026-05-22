"""Stage 2: Beta Prediction via Fundamental Factor Proxies.

Predicts individual stock β relative to industry portfolio using fundamental
factor proxies derived from price/volume/holding data.

Theory: β is determined by:
- Operating leverage (经营杠杆): revenue sensitivity to economic cycles
- Financial leverage (财务杠杆): debt-to-equity intensity
- Business cycle attributes (业务周期属性): sector cyclicality
- Asset quality (资产质量): balance sheet health
- Earnings stability (盈利稳定性): smoothed earnings volatility
- Size (规模): log market cap
- Growth (成长性): revenue/earnings growth trajectory

Since we only have OHLCV data, each factor is proxied by:
- Size: log(average turnover * price)
- Earnings stability proxy: residual volatility (IVOL-like)
- Growth proxy: price momentum, volume trend
- Operating leverage proxy: price sensitivity to industry returns
- Financial leverage proxy: high-frequency return volatility
- Asset quality proxy: price above long-term MA stability
- Business cycle: industry membership (categorical)

Output: predicted β score (higher = higher expected β)
"""

import numpy as np
import pandas as pd


def compute_historical_beta(
    stock_returns: pd.Series,
    industry_returns: pd.Series,
    window: int = 252,
    min_periods: int = 60,
) -> pd.Series:
    """Compute rolling CAPM β of stock vs industry index.

    β = Cov(r_i, r_m) / Var(r_m) over rolling window.
    """
    aligned = pd.DataFrame({"stock": stock_returns, "index": industry_returns}).dropna()
    if len(aligned) < min_periods:
        return pd.Series(np.nan, index=stock_returns.index)

    cov = aligned["stock"].rolling(window, min_periods=min_periods).cov(aligned["index"])
    var = aligned["index"].rolling(window, min_periods=min_periods).var()
    beta = cov / var.replace(0, np.nan)
    return beta


def compute_fundamental_proxies(data: pd.DataFrame) -> pd.DataFrame:
    """Compute fundamental factor proxies from OHLCV data.

    Returns DataFrame with columns for each proxy factor.
    All outputs are cross-sectionally comparable (z-scored).

    Args:
        data: DataFrame with columns [open, high, low, close, volume, amount, turnover]
    """
    close = data["close"]
    volume = data["volume"]
    amount = data.get("amount", close * volume)
    turnover = data.get("turnover", pd.Series(np.nan, index=data.index))

    returns = close.pct_change()
    result = pd.DataFrame(index=data.index)

    # 1. Size proxy (规模): log market cap estimate
    # Market cap ≈ avg daily amount / avg turnover rate
    avg_amount = amount.rolling(60, min_periods=20).mean()
    if turnover.notna().any():
        avg_turnover = turnover.rolling(60, min_periods=20).mean().replace(0, np.nan)
        mkt_cap_proxy = avg_amount / avg_turnover
    else:
        mkt_cap_proxy = avg_amount * 100  # rough approximation
    result["size"] = np.log(mkt_cap_proxy.replace(0, np.nan))

    # 2. Earnings stability proxy (盈利稳定性): IVOL-like residual volatility
    # Regress returns on market return, take residual volatility
    returns_clean = returns.dropna()
    if len(returns_clean) >= 60:
        rolling_std = returns.rolling(60, min_periods=20).std()
        result["earnings_stability"] = -rolling_std  # negative: higher vol = lower stability
    else:
        result["earnings_stability"] = 0.0

    # 3. Growth proxy (成长性): multi-horizon momentum
    for h in [20, 60, 120]:
        if len(close) > h:
            mom = close.pct_change(h)
            result[f"momentum_{h}d"] = mom
    # Composite growth score
    mom_cols = [c for c in result.columns if c.startswith("momentum_")]
    if mom_cols:
        result["growth"] = result[mom_cols].mean(axis=1)

    # 4. Operating leverage proxy (经营杠杆): beta of revenue vs costs
    # Proxy: sensitivity of daily return to volume changes
    if len(returns_clean) >= 60:
        vol_change = volume.pct_change()
        aligned = pd.DataFrame({"ret": returns, "dvol": vol_change}).dropna()
        if len(aligned) >= 30:
            cov_rv = aligned["ret"].rolling(60, min_periods=20).cov(aligned["dvol"])
            var_v = aligned["dvol"].rolling(60, min_periods=20).var()
            result["operating_leverage"] = cov_rv / var_v.replace(0, np.nan)
        else:
            result["operating_leverage"] = 0.0
    else:
        result["operating_leverage"] = 0.0

    # 5. Financial leverage proxy (财务杠杆): downside volatility / total volatility
    # Higher downside vol ratio = higher financial leverage
    if len(returns_clean) >= 60:
        down_ret = returns_clean[returns_clean < 0]
        total_vol = returns.rolling(60, min_periods=20).std()
        down_vol = returns.rolling(60, min_periods=20).apply(
            lambda x: x[x < 0].std() if len(x[x < 0]) > 0 else 0
        )
        result["financial_leverage"] = (down_vol / total_vol.replace(0, np.nan)).fillna(0)
    else:
        result["financial_leverage"] = 0.0

    # 6. Asset quality proxy (资产质量): price stability around long MA
    if len(close) >= 120:
        ma_long = close.rolling(120, min_periods=60).mean()
        deviation = (close - ma_long) / ma_long.replace(0, np.nan)
        result["asset_quality"] = -deviation.abs()  # smaller deviation = higher quality
    else:
        result["asset_quality"] = 0.0

    # 7. Volume trend (量能趋势): volume acceleration
    if len(volume) >= 60:
        vol_ma_short = volume.rolling(10).mean()
        vol_ma_long = volume.rolling(60).mean()
        result["volume_trend"] = (vol_ma_short / vol_ma_long.replace(0, np.nan) - 1).fillna(0)
    else:
        result["volume_trend"] = 0.0

    return result


def predict_beta(
    data: pd.DataFrame,
    industry_returns: pd.Series | None = None,
) -> pd.Series:
    """Stage 2: Predict stock β relative to industry.

    Combines historical β with fundamental factor proxies to produce
    a forward-looking β prediction.

    Decision rule: higher predicted β → stronger expected response to
    industry uptrend → preferred when industry is ranked as mainline.

    Args:
        data: OHLCV DataFrame
        industry_returns: optional industry index returns for historical β

    Returns:
        pd.Series: predicted beta score (higher = higher expected β)
    """
    returns = data["close"].pct_change()

    # Historical β (if industry returns available)
    if industry_returns is not None and len(industry_returns) > 60:
        hist_beta = compute_historical_beta(returns, industry_returns)
        hist_beta = hist_beta.fillna(1.0).clip(-2, 5)
    else:
        hist_beta = pd.Series(1.0, index=data.index)

    # Fundamental factor proxies
    fund_proxies = compute_fundamental_proxies(data)

    # Cross-sectional z-score normalize each proxy
    for col in fund_proxies.columns:
        s = fund_proxies[col]
        rolling_mean = s.rolling(252, min_periods=60).mean()
        rolling_std = s.rolling(252, min_periods=60).std().replace(0, 1)
        fund_proxies[f"{col}_z"] = (s - rolling_mean) / rolling_std

    z_cols = [c for c in fund_proxies.columns if c.endswith("_z")]
    if not z_cols:
        return hist_beta

    # Weighted combination of factors to predict β
    # Weights based on relative importance for β prediction:
    # Size (large→lower β), Financial leverage (higher→higher β),
    # Operating leverage (higher→higher β), Growth (higher→higher β temporarily)
    weights = {
        "size_z": -0.15,            # Larger = lower β (diversified)
        "financial_leverage_z": 0.25,  # Higher FL = higher β
        "operating_leverage_z": 0.20,  # Higher OL = higher β
        "growth_z": 0.15,           # Higher growth = higher β (growth tilt)
        "earnings_stability_z": 0.10, # More stable = higher β (less volatile than expected)
        "asset_quality_z": 0.05,    # Higher quality = moderate β
        "volume_trend_z": 0.10,     # Volume expansion = higher β
    }

    factor_beta = pd.Series(0.0, index=data.index)
    for col, w in weights.items():
        if col in fund_proxies.columns:
            factor_beta += w * fund_proxies[col].fillna(0)

    # Blend: 60% historical β + 40% fundamental factor prediction
    predicted_beta = 0.60 * hist_beta + 0.40 * factor_beta
    predicted_beta = predicted_beta.clip(0.3, 3.0)  # Sensible bounds

    return predicted_beta


def rank_stocks_by_beta(
    stock_data: dict[str, pd.DataFrame],
    industry_returns: pd.Series | None = None,
    top_n: int = 10,
) -> pd.DataFrame:
    """Rank stocks by predicted β within an industry.

    Args:
        stock_data: symbol -> DataFrame for stocks in same industry
        industry_returns: industry index returns (for historical β calc)
        top_n: select top N by β

    Returns:
        DataFrame with columns [symbol, predicted_beta, hist_beta, growth, size, ...]
    """
    results = []
    for sym, data in stock_data.items():
        try:
            pred_beta = predict_beta(data, industry_returns)
            latest_beta = pred_beta.dropna().iloc[-1] if len(pred_beta.dropna()) > 0 else np.nan
            fund = compute_fundamental_proxies(data)
            latest_growth = fund["growth"].dropna().iloc[-1] if "growth" in fund.columns and len(fund["growth"].dropna()) > 0 else np.nan
            latest_size = fund["size"].dropna().iloc[-1] if "size" in fund.columns and len(fund["size"].dropna()) > 0 else np.nan
            results.append({
                "symbol": sym,
                "predicted_beta": round(latest_beta, 4) if not pd.isna(latest_beta) else np.nan,
                "growth": round(latest_growth, 6) if not pd.isna(latest_growth) else np.nan,
                "size": round(latest_size, 2) if not pd.isna(latest_size) else np.nan,
            })
        except Exception:
            pass

    df = pd.DataFrame(results).dropna(subset=["predicted_beta"])
    df = df.sort_values("predicted_beta", ascending=False)
    return df.head(top_n).reset_index(drop=True)
