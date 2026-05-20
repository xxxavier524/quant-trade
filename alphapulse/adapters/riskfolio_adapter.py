"""Riskfolio-Lib integration adapter for AlphaPulse-A.

Replaces static position sizing (20% cap, max-5 holdings, equal weight)
with production-grade portfolio optimization:

  - Black-Litterman: incorporate factor-derived return views
  - CVaR optimization: minimize tail risk
  - Hierarchical Risk Parity (HRP): correlation-aware clustering
  - HERC / NCO: advanced hierarchical methods

Usage:
    from alphapulse.adapters.riskfolio_adapter import (
        compute_bl_weights,
        compute_cvar_weights,
        compute_hrp_weights,
    )

    returns = pd.DataFrame(...)  # daily returns, columns=symbols
    weights = compute_bl_weights(returns, factor_views=my_views)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# riskfolio-lib is an optional dependency -- soft import
# ---------------------------------------------------------------------------
try:
    import riskfolio as rp

    _HAS_RISKFOLIO = True
except ImportError:
    _HAS_RISKFOLIO = False
    rp = None  # type: ignore


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FactorView:
    """A single Black-Litterman view derived from an AlphaPulse-A factor.

    Attributes:
        symbol: A-share ticker (e.g. '600519')
        direction: 1 for bullish, -1 for bearish
        magnitude: expected excess return magnitude (annualized, e.g. 0.15 = 15%)
        confidence: 0-1 confidence in this view
        factor_name: which AlphaPulse-A factor produced this view
    """

    symbol: str
    direction: int  # 1 or -1
    magnitude: float
    confidence: float
    factor_name: str = ""


@dataclass
class PortfolioAllocation:
    """Result of a portfolio optimization run.

    Attributes:
        weights: pd.Series mapping symbol -> allocation weight (0-1, sum=1)
        risk_contrib_pct: risk contribution per symbol (for HRP-based methods)
        method: optimization method used
        metadata: additional metrics (expected return, risk, etc.)
    """

    weights: pd.Series
    risk_contrib_pct: pd.Series | None = None
    method: str = ""
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def compute_bl_weights(
    returns: pd.DataFrame,
    factor_views: list[FactorView] | None = None,
    risk_aversion: float = 2.5,
    market_caps: pd.Series | None = None,
    benchmark_returns: pd.Series | None = None,
) -> PortfolioAllocation:
    """Black-Litterman portfolio optimization.

    Combines market-implied equilibrium returns with AlphaPulse-A factor views
    to produce optimal weights.

    Args:
        returns: Daily returns DataFrame (date index, symbol columns).
        factor_views: List of FactorView objects from AlphaPulse-A factors.
        risk_aversion: Risk aversion coefficient (higher = more conservative).
            Default 2.5 is typical for equity portfolios.
        market_caps: Market cap series (optional, for market-implied weights).
        benchmark_returns: Daily benchmark returns (optional, e.g. CSI 300).

    Returns:
        PortfolioAllocation with optimized weights.

    Note:
        If factor_views is None or empty, this falls back to simple
        mean-variance optimization (equivalent to vanilla Markowitz).
    """
    if not _HAS_RISKFOLIO:
        raise ImportError(
            "riskfolio-lib is required. Install it with: pip install riskfolio-lib"
        )

    symbols = returns.columns.tolist()
    n_assets = len(symbols)

    if n_assets < 2:
        return _single_asset_allocation(symbols)

    # Compute covariance and market-implied returns
    cov_matrix = returns.cov().values

    # Normalize benchmark weights
    if market_caps is not None and not market_caps.empty:
        w_mkt = market_caps.loc[symbols].values
        w_mkt = w_mkt / w_mkt.sum()
    else:
        w_mkt = np.ones(n_assets) / n_assets

    # Build views and run Black-Litterman
    if factor_views:
        P, Q = _build_bl_views_simple(factor_views, symbols)

        # riskfolio black_litterman takes raw returns X, benchmark weights w,
        # pick matrix P, and views vector Q. It internally computes implied
        # equilibrium returns and posterior distribution.
        # riskfolio expects DataFrames, not numpy arrays
        w_df = pd.DataFrame(w_mkt.reshape(1, -1), columns=symbols)

        bl = rp.black_litterman(
            X=returns,
            w=w_df,
            P=P,
            Q=Q,
            delta=risk_aversion,
            rf=0.0,
            eq=True,
        )
        posterior_mu = bl[0].values.flatten()  # posterior mean returns
        posterior_cov = bl[1].values  # posterior covariance

        logger.info(
            "Black-Litterman: %d views applied, posterior mu range: [%.4f, %.4f]",
            len(factor_views),
            posterior_mu.min(),
            posterior_mu.max(),
        )
    else:
        # No factor views: use standard mean-variance optimization
        posterior_mu = returns.mean().values * 252  # annualized
        posterior_cov = cov_matrix
        logger.info("Black-Litterman: no views, using historical mean returns")

    # Portfolio optimization on posterior
    port = rp.Portfolio(returns=returns)
    port.mu = posterior_mu
    port.cov = posterior_cov
    # NOTE: Do NOT call assets_stats() -- it recomputes mu/cov from returns,
    # overwriting our Black-Litterman posterior.

    try:
        w = port.optimization(
            model="Classic",
            rm="MV",
            obj="Sharpe",
            hist=False,
        )
    except Exception as e:
        logger.warning("Sharpe optimization failed (%s), falling back to MinRisk", e)
        w = port.optimization(
            model="Classic",
            rm="MV",
            obj="MinRisk",
            hist=False,
        )

    # w is a DataFrame-like; convert to pd.Series
    weights_series = pd.Series(
        {s: float(w.loc[s].iloc[0]) if s in w.index else 0.0 for s in symbols},
        name="weight",
    )
    weights_series = weights_series / weights_series.sum()  # normalize

    return PortfolioAllocation(
        weights=weights_series,
        method="black-litterman",
        metadata={
            "risk_aversion": risk_aversion,
            "n_views": len(factor_views) if factor_views else 0,
            "n_assets": n_assets,
        },
    )


def compute_cvar_weights(
    returns: pd.DataFrame,
    alpha: float = 0.05,
    target_return: float | None = None,
) -> PortfolioAllocation:
    """CVaR (Conditional Value-at-Risk) portfolio optimization.

    Minimizes expected tail loss (the average of the worst alpha% returns).
    More robust than mean-variance for fat-tailed return distributions,
    which are common in A-share markets.

    Args:
        returns: Daily returns DataFrame (date index, symbol columns).
        alpha: CVaR confidence level (0.05 = 95% CVaR, worst 5% of outcomes).
        target_return: Minimum target return (if None, maximizes return/CVaR ratio).

    Returns:
        PortfolioAllocation with CVaR-optimal weights.

    Note:
        CVaR is especially appropriate for A-share strategies because:
        - A-shares exhibit heavy tails (frequent small-cap limit hits)
        - Policy shocks cause extreme drawdowns that variance-based methods miss
        - CVaR explicitly models the worst scenarios
    """
    if not _HAS_RISKFOLIO:
        raise ImportError(
            "riskfolio-lib is required. Install it with: pip install riskfolio-lib"
        )

    symbols = returns.columns.tolist()
    n_assets = len(symbols)

    if n_assets < 2:
        return _single_asset_allocation(symbols)

    port = rp.Portfolio(returns=returns, alpha=alpha)
    port.assets_stats(method_mu="hist", method_cov="hist")

    try:
        w = port.optimization(
            model="Classic",
            rm="CVaR",
            obj="Sharpe",
            hist=False,
        )
    except Exception:
        # Fallback: minimize CVaR directly (no target return constraint)
        logger.warning("CVaR Sharpe optimization failed, falling back to Min CVaR")
        w = port.optimization(
            model="Classic",
            rm="CVaR",
            obj="MinRisk",
            hist=False,
        )

    weights_series = pd.Series(
        {s: float(w.loc[s].iloc[0]) if s in w.index else 0.0 for s in symbols},
        name="weight",
    )
    weights_series = _clip_and_normalize(weights_series, max_single=0.20)

    # Compute risk contribution
    risk_contrib_series = None
    try:
        if hasattr(port, 'risk_contributions') and port.risk_contributions is not None:
            rc = port.risk_contributions
            risk_contrib_series = pd.Series(
                {s: float(rc.loc[s].iloc[0]) if s in rc.index else 0.0
                 for s in symbols}
            )
    except Exception:
        pass

    return PortfolioAllocation(
        weights=weights_series,
        risk_contrib_pct=risk_contrib_series,
        method=f"cvar-alpha{alpha}",
        metadata={
            "alpha": alpha,
            "n_assets": n_assets,
        },
    )


def compute_hrp_weights(
    returns: pd.DataFrame,
    codependence: str = "pearson",
    rm: str = "MV",
    max_k: int = 5,
) -> PortfolioAllocation:
    """Hierarchical Risk Parity (HRP) portfolio optimization.

    Uses hierarchical clustering to group correlated assets, then applies
    risk parity within each cluster and across clusters. This addresses the
    core weakness of equal-weight allocation: ignoring correlation structure.

    For A-share portfolios, HRP is especially useful because:
    - Sectors often move together (e.g., all consumer stocks, all banks)
    - Equal-weighting 5 stocks in the same sector = concentrated risk
    - HRP automatically detects clusters and diversifies across them

    Args:
        returns: Daily returns DataFrame (date index, symbol columns).
        codependence: Codependence measure ('pearson', 'spearman', 'kendall').
        rm: Risk measure for within-cluster optimization ('MV', 'CVaR', 'CDaR').
        max_k: Maximum clusters for NCO (Nested Clustered Optimization).

    Returns:
        PortfolioAllocation with HRP-optimal weights.
    """
    if not _HAS_RISKFOLIO:
        raise ImportError(
            "riskfolio-lib is required. Install it with: pip install riskfolio-lib"
        )

    symbols = returns.columns.tolist()
    n_assets = len(symbols)

    if n_assets < 2:
        return _single_asset_allocation(symbols)

    port = rp.Portfolio(returns=returns)
    port.assets_stats(method_mu="hist", method_cov="hist")

    try:
        w = port.optimization(
            model="HRP",
            rm=rm,
            hist=False,
        )
    except Exception as e:
        logger.warning("HRP optimization failed (%s), falling back to CVaR", e)
        return compute_cvar_weights(returns, alpha=0.05)

    weights_series = pd.Series(
        {s: float(w.loc[s].iloc[0]) if s in w.index else 0.0 for s in symbols},
        name="weight",
    )
    weights_series = _clip_and_normalize(weights_series, max_single=0.20)

    return PortfolioAllocation(
        weights=weights_series,
        method=f"hrp-{codependence}",
        metadata={
            "codependence": codependence,
            "risk_measure": rm,
            "n_assets": n_assets,
        },
    )


def compute_risk_parity_weights(
    returns: pd.DataFrame,
    rm: str = "MV",
    risk_budget: pd.Series | None = None,
) -> PortfolioAllocation:
    """Equal Risk Contribution (ERC) / Risk Budgeting portfolio.

    Each asset contributes equally to total portfolio risk (or per budget).

    Args:
        returns: Daily returns DataFrame.
        rm: Risk measure ('MV', 'CVaR', 'CDaR', 'MDD').
        risk_budget: Custom risk budget per asset (default: equal).

    Returns:
        PortfolioAllocation with risk-parity weights.
    """
    if not _HAS_RISKFOLIO:
        raise ImportError("riskfolio-lib is required.")

    symbols = returns.columns.tolist()
    n_assets = len(symbols)

    if n_assets < 2:
        return _single_asset_allocation(symbols)

    port = rp.Portfolio(returns=returns)
    port.assets_stats(method_mu="hist", method_cov="hist")

    if risk_budget is not None and not risk_budget.empty:
        b = risk_budget.reindex(symbols, fill_value=0.0).values
        b = b / b.sum()
    else:
        b = None

    w = port.optimization(
        model="Classic",
        rm=rm,
        obj="RiskParity",
        hist=False,
    )

    weights_series = pd.Series(
        {s: float(w.loc[s].iloc[0]) if s in w.index else 0.0 for s in symbols},
        name="weight",
    )
    weights_series = _clip_and_normalize(weights_series, max_single=0.20)

    return PortfolioAllocation(
        weights=weights_series,
        method=f"risk-parity-{rm}",
        metadata={"risk_measure": rm, "n_assets": n_assets},
    )


# ---------------------------------------------------------------------------
# Convenience: select best method based on signal characteristics
# ---------------------------------------------------------------------------


def auto_optimize(
    returns: pd.DataFrame,
    factor_views: list[FactorView] | None = None,
    n_signals: int = 0,
    market_regime: str = "normal",
) -> PortfolioAllocation:
    """Automatically select the best optimization method.

    Decision logic:
    - Few signals (<=5): HRP (robust for small universes)
    - Many signals (>5): Black-Litterman (incorporates factor views)
    - High volatility regime: CVaR (tail-risk focus)
    - Factor views available: Black-Litterman (use the views)

    Args:
        returns: Daily returns DataFrame.
        factor_views: AlphaPulse-A factor-derived views.
        n_signals: Number of active buy signals.
        market_regime: 'normal', 'high_vol', 'low_vol'.

    Returns:
        PortfolioAllocation with automatically selected method.
    """
    if n_signals == 0:
        logger.warning("auto_optimize: no signals, returning empty allocation")
        return PortfolioAllocation(
            weights=pd.Series(dtype=float), method="empty"
        )

    if market_regime == "high_vol":
        logger.info("auto_optimize: high-vol regime -> CVaR optimization")
        return compute_cvar_weights(returns, alpha=0.05)

    if factor_views and len(factor_views) > 0:
        logger.info(
            "auto_optimize: %d factor views available -> Black-Litterman",
            len(factor_views),
        )
        return compute_bl_weights(returns, factor_views=factor_views)

    if n_signals <= 5:
        logger.info("auto_optimize: %d signals -> HRP", n_signals)
        return compute_hrp_weights(returns)

    logger.info("auto_optimize: %d signals -> Risk Parity", n_signals)
    return compute_risk_parity_weights(returns)


# ---------------------------------------------------------------------------
# Position sizing: convert allocation weights to tradable shares
# ---------------------------------------------------------------------------


def weights_to_positions(
    allocation: PortfolioAllocation,
    prices: dict[str, float],
    total_capital: float,
    min_shares: int = 100,
    max_single_pct: float = 0.20,
) -> dict[str, dict]:
    """Convert portfolio weights to actual tradable positions.

    Args:
        allocation: PortfolioAllocation from any optimization method.
        prices: Current prices dict {symbol: price}.
        total_capital: Total available capital.
        min_shares: Minimum trading lot size (100 for A-shares).
        max_single_pct: Maximum allocation to any single stock.

    Returns:
        Dict {symbol: {'shares': int, 'value': float, 'weight': float}}.
    """
    positions = {}
    remaining_capital = total_capital

    # Sort by weight (highest first) for allocation priority
    sorted_weights = allocation.weights.sort_values(ascending=False)

    for symbol, weight in sorted_weights.items():
        if symbol not in prices or weight <= 0.001:  # skip <0.1% allocations
            continue

        # Apply single-stock cap
        effective_weight = min(weight, max_single_pct)
        target_value = total_capital * effective_weight
        target_value = min(target_value, remaining_capital)

        price = prices[symbol]
        shares = int(target_value / price / min_shares) * min_shares

        if shares >= min_shares:
            actual_value = shares * price
            positions[symbol] = {
                "shares": shares,
                "value": actual_value,
                "weight": actual_value / total_capital,
            }
            remaining_capital -= actual_value

    return positions


# ---------------------------------------------------------------------------
# Factor views construction helpers
# ---------------------------------------------------------------------------


def factor_signal_to_view(
    factor_values: pd.Series,
    factor_name: str,
    threshold: float = 0.5,
    magnitude: float = 0.10,
) -> list[FactorView]:
    """Convert factor signal values to Black-Litterman views.

    Args:
        factor_values: pd.Series of factor values (index=symbol).
        factor_name: Name of the factor (e.g. 'KDJ_J_LOW').
        threshold: Factor value threshold for signal classification.
        magnitude: Expected annual excess return magnitude.

    Returns:
        List of FactorView objects.
    """
    views = []
    for symbol, value in factor_values.dropna().items():
        confidence = min(abs(value) / (threshold * 2), 1.0)
        if confidence < 0.3:  # ignore weak signals
            continue

        direction = 1 if value > 0 else -1
        views.append(
            FactorView(
                symbol=str(symbol),
                direction=direction,
                magnitude=magnitude,
                confidence=confidence,
                factor_name=factor_name,
            )
        )
    return views


def multi_factor_views(
    factor_df: pd.DataFrame,
    factor_specs: dict[str, dict] | None = None,
    default_magnitude: float = 0.10,
) -> list[FactorView]:
    """Build combined views from multiple factor outputs.

    Args:
        factor_df: DataFrame with factor columns (index=symbol).
            Each column is a different factor's signal values.
        factor_specs: Dict {factor_name: {threshold, magnitude}}.
            If None, uses default threshold=0.5 for all factors.
        default_magnitude: Default magnitude if not specified in factor_specs.

    Returns:
        Combined list of FactorView objects from all factors.
    """
    all_views = []
    for col in factor_df.columns:
        specs = (factor_specs or {}).get(col, {})
        views = factor_signal_to_view(
            factor_df[col],
            factor_name=col,
            threshold=specs.get("threshold", 0.5),
            magnitude=specs.get("magnitude", default_magnitude),
        )
        all_views.extend(views)

    # Deduplicate: keep highest-confidence view per symbol
    deduped = {}
    for view in all_views:
        key = view.symbol
        if key not in deduped or view.confidence > deduped[key].confidence:
            deduped[key] = view

    return list(deduped.values())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_bl_views_simple(
    factor_views: list[FactorView],
    symbols: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Build Black-Litterman P (pick matrix) and Q (views column vector).

    riskfolio's black_litterman requires Q as (n_views, 1) column vector.
    The function handles Omega (view uncertainty) internally.
    """
    sym_to_idx = {s: i for i, s in enumerate(symbols)}
    n_views = len(factor_views)

    P = np.zeros((n_views, len(symbols)))
    Q = np.zeros((n_views, 1))  # column vector required by riskfolio

    for i, view in enumerate(factor_views):
        if view.symbol not in sym_to_idx:
            continue
        idx = sym_to_idx[view.symbol]
        P[i, idx] = view.direction
        Q[i, 0] = view.magnitude * view.direction * view.confidence

    return P, Q


def _clip_and_normalize(weights: pd.Series, max_single: float = 0.20) -> pd.Series:
    """Clip single-asset weights and renormalize."""
    weights = weights.clip(lower=0.0, upper=max_single)
    total = weights.sum()
    if total > 0:
        weights = weights / total
    return weights


def _single_asset_allocation(symbols: list[str]) -> PortfolioAllocation:
    """Handle single-asset case."""
    if not symbols:
        return PortfolioAllocation(weights=pd.Series(dtype=float), method="empty")
    return PortfolioAllocation(
        weights=pd.Series({symbols[0]: 1.0}, name="weight"),
        method="single-asset",
        metadata={"n_assets": 1},
    )


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Generate synthetic return data for testing
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=252, freq="B")
    symbols = ["600519", "000001", "300750", "002594", "600036"]

    # Simulated correlated returns
    returns = pd.DataFrame(
        np.random.randn(252, 5) * 0.02,  # daily vol ~2%
        index=dates,
        columns=symbols,
    )
    # Add correlation structure
    returns += np.random.randn(252, 1) * 0.01  # common factor

    print("=== Riskfolio-Lib Adapter Test ===")

    # Test 1: Black-Litterman
    views = [
        FactorView("600519", direction=1, magnitude=0.15, confidence=0.8, factor_name="KDJ_J_LOW"),
        FactorView("000001", direction=-1, magnitude=0.05, confidence=0.5, factor_name="MACD_BULL_DEAD"),
    ]
    alloc_bl = compute_bl_weights(returns, factor_views=views)
    print(f"\nBlack-Litterman ({alloc_bl.method}):")
    print(alloc_bl.weights.round(4))

    # Test 2: CVaR
    alloc_cvar = compute_cvar_weights(returns, alpha=0.05)
    print(f"\nCVaR (alpha=0.05):")
    print(alloc_cvar.weights.round(4))

    # Test 3: HRP
    alloc_hrp = compute_hrp_weights(returns)
    print(f"\nHRP (pearson):")
    print(alloc_hrp.weights.round(4))

    # Test 4: Auto-select
    alloc_auto = auto_optimize(returns, factor_views=views, n_signals=3)
    print(f"\nAuto-select -> {alloc_auto.method}:")
    print(alloc_auto.weights.round(4))

    # Test 5: Weights to positions
    prices = {"600519": 1598.18, "000001": 12.34, "300750": 245.0, "002594": 268.5, "600036": 38.9}
    positions = weights_to_positions(alloc_hrp, prices, 100000)
    print("\nPositions (100K capital):")
    for sym, pos in positions.items():
        print(f"  {sym}: {pos['shares']} shares @ {prices[sym]:.2f} = {pos['value']:.0f} ({pos['weight']:.1%})")
