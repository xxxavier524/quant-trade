"""vectorbt integration adapter for AlphaPulse-A.

Accelerates parameter grid search (Phase 6) using vectorized backtesting.
The key insight: vectorbt represents every strategy config as a column
in a 2D matrix, allowing thousands of combos to be backtested in seconds.

Complements VeighNa (primary engine per CLAUDE.md constraint):
  - Pre-screening: Quickly eliminate bad parameter combos
  - Cross-validation: Verify VeighNa results
  - Speed: Reduce grid search from hours to seconds

IMPORTANT: This module does NOT replace the VeighNa backtest engine.
It serves as an accelerator and cross-validation tool only.

Usage:
    from alphapulse.adapters.vectorbt_adapter import (
        vbt_grid_search,
        vbt_signal_to_portfolio,
        vbt_cross_validate,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# vectorbt is an optional dependency
# ---------------------------------------------------------------------------
try:
    import vectorbt as vbt

    _HAS_VBT = True
except ImportError:
    _HAS_VBT = False
    vbt = None  # type: ignore


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GridSearchResult:
    """Results from a vectorized grid search over parameter combinations.

    Attributes:
        stats_df: DataFrame where each row is a parameter combo with metrics.
        best_params: Dict of best parameters by Sharpe ratio.
        best_sharpe: Best Sharpe ratio found.
        best_return: Annualized return of best combo.
        best_drawdown: Max drawdown of best combo.
        pareto_front: DataFrame of non-dominated parameter combos.
    """

    stats_df: pd.DataFrame
    best_params: dict
    best_sharpe: float = 0.0
    best_return: float = 0.0
    best_drawdown: float = 0.0
    pareto_front: pd.DataFrame | None = None


@dataclass
class CrossValidationResult:
    """Comparison of vbt results vs VeighNa results.

    Attributes:
        vbt_metrics: Dict of vbt-computed metrics.
        vnpy_metrics: Dict of VeighNa-computed metrics (from external source).
        discrepancies: Dict of metric -> absolute difference pct.
        is_valid: True if all discrepancies are within threshold.
    """

    vbt_metrics: dict
    vnpy_metrics: dict
    discrepancies: dict
    is_valid: bool
    threshold: float = 0.05  # 5% discrepancy tolerance


# ---------------------------------------------------------------------------
# Core API: Grid Search
# ---------------------------------------------------------------------------


def vbt_grid_search(
    close: pd.DataFrame,
    signal_func: callable,
    param_grid: dict[str, list],
    init_cash: float = 100_000.0,
    slippage_buy: float = 0.001,
    slippage_sell: float = 0.002,
    commission_rate: float = 0.00025,
    min_commission: float = 5.0,
    freq: str = "1D",
    progress: bool = False,
) -> GridSearchResult:
    """Vectorized grid search over strategy parameters.

    Evaluates ALL parameter combinations in a single vectorized pass.

    Args:
        close: OHLC DataFrame or Series (price data for backtest).
        signal_func: Callable that takes (close, **params) and returns
            entry_df, exit_df. Both are DataFrames with same index as close
            and same columns (each column = one param combo variant).
            True = trade signal, False = no signal.
            Alternatively, returns a single DataFrame of long/short signals.
        param_grid: Dict {param_name: [value1, value2, ...]}.
        init_cash: Starting capital.
        slippage_buy: Buy slippage (0.001 = 0.1%).
        slippage_sell: Sell slippage (0.002 = 0.2%).
        commission_rate: Commission rate (0.00025 = 0.025%).
        min_commission: Minimum commission per trade.
        freq: Rebalancing frequency ('1D', '1h', etc.).
        progress: Show progress bar.

    Returns:
        GridSearchResult with stats for every parameter combination.
    """
    if not _HAS_VBT:
        raise ImportError(
            "vectorbt is required. Install it with: pip install vectorbt"
        )

    if isinstance(close, pd.DataFrame):
        # Use first column if multi-column; grid search runs on single asset
        # Multi-asset grid search requires more complex setup
        price_series = close.iloc[:, 0]
    else:
        price_series = close

    # Compute entry/exit signals for all param combos
    entries, exits = signal_func(price_series, **param_grid)

    # Build portfolio: vectorbt automatically tests all signal column combos
    portfolio = vbt.Portfolio.from_signals(
        price_series,
        entries=entries,
        exits=exits,
        freq=freq,
        init_cash=init_cash,
        slippage=slippage_buy,  # vbt uses single slippage; use buy side as base
        fees=commission_rate,
    )

    # Extract statistics for every param combination
    stats = portfolio.stats(agg_func=None)  # returns wide DataFrame

    # Reshape stats into long format: each row = one param combo
    metrics = [
        "Total Return [%]",
        "Sharpe Ratio",
        "Max Drawdown [%]",
        "Win Rate [%]",
        "Expectancy",
        "Profit Factor",
    ]
    available_metrics = [m for m in metrics if m in stats.columns]
    stats_df = stats[available_metrics].copy()
    stats_df.columns = [c.replace(" [%]", "").replace(" ", "_").lower() for c in stats_df.columns]

    # Find best by Sharpe ratio
    sharpe_col = stats_df.columns[stats_df.columns.str.contains("sharpe", case=False)]
    if len(sharpe_col) > 0:
        best_idx = stats_df[sharpe_col[0]].idxmax()
        best_row = stats_df.loc[best_idx]
        best_sharpe = float(best_row[sharpe_col[0]])
        best_return = float(best_row.get("total_return", 0)) / 100.0
        best_drawdown = float(best_row.get("max_drawdown", 0)) / 100.0
    else:
        best_idx = 0
        best_sharpe = 0.0
        best_return = 0.0
        best_drawdown = 0.0

    # Extract best parameters from column name
    best_params = _parse_param_combo(best_idx, param_grid)

    # Compute Pareto front (non-dominated combos by return vs drawdown)
    pareto = _compute_pareto(stats_df)

    return GridSearchResult(
        stats_df=stats_df,
        best_params=best_params,
        best_sharpe=best_sharpe,
        best_return=best_return,
        best_drawdown=best_drawdown,
        pareto_front=pareto,
    )


def vbt_signal_to_portfolio(
    close: pd.DataFrame,
    signals: pd.DataFrame,
    init_cash: float = 100_000.0,
    slippage_buy: float = 0.001,
    slippage_sell: float = 0.002,
    commission_rate: float = 0.00025,
    min_commission: float = 5.0,
    freq: str = "1D",
) -> dict:
    """Convert AlphaPulse-A strategy signals to a vbt Portfolio and return metrics.

    This is the main cross-validation entry point: take our existing strategy
    signals and run them through vectorbt for comparison with VeighNa results.

    Args:
        close: OHLC price DataFrame (date index, asset columns).
        signals: Boolean DataFrame (same shape as close). True = enter/hold,
            False = exit/out. From AlphaPulse-A strategy output.
        init_cash: Starting capital.
        slippage_buy/sell: Slippage per direction.
        commission_rate/min_commission: Fee structure.
        freq: Rebalancing frequency.

    Returns:
        Dict with keys: 'portfolio' (vbt Portfolio), 'stats' (dict of key metrics),
        'trades' (DataFrame of individual trades).
    """
    if not _HAS_VBT:
        raise ImportError("vectorbt is required.")

    # For multi-asset: process each column separately and aggregate
    # For single-asset: use directly
    if isinstance(signals, pd.DataFrame) and signals.shape[1] > 1:
        # Multi-asset: build separate portfolios and aggregate
        portfolios = {}
        all_stats = []
        for col in signals.columns:
            p = vbt.Portfolio.from_signals(
                close[col] if isinstance(close, pd.DataFrame) else close,
                entries=signals[col].astype(bool),
                exits=~signals[col].astype(bool),
                freq=freq,
                init_cash=init_cash / signals.shape[1],  # equal capital per asset
                slippage=slippage_buy,
                fees=commission_rate,
            )
            portfolios[col] = p
            all_stats.append(p.stats())

        # Aggregate stats (simple average)
        agg_stats = pd.concat(all_stats, axis=1).mean(axis=1).to_dict()
        return {"portfolios": portfolios, "stats": agg_stats}
    else:
        # Single asset
        signal_series = (
            signals.iloc[:, 0] if isinstance(signals, pd.DataFrame) else signals
        )
        close_series = (
            close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
        )
        entries = signal_series.astype(bool)
        exits = ~entries

        portfolio = vbt.Portfolio.from_signals(
            close_series,
            entries=entries,
            exits=exits,
            freq=freq,
            init_cash=init_cash,
            slippage=slippage_buy,
            fees=commission_rate,
        )

        stats = portfolio.stats()
        return {
            "portfolio": portfolio,
            "stats": {
                "total_return": float(stats.get("Total Return [%]", 0)),
                "sharpe_ratio": float(stats.get("Sharpe Ratio", 0)),
                "max_drawdown": float(stats.get("Max Drawdown [%]", 0)),
                "win_rate": float(stats.get("Win Rate [%]", 0)),
                "profit_factor": float(stats.get("Profit Factor", 0)),
                "total_trades": int(stats.get("Total Trades", 0)),
            },
        }


def vbt_cross_validate(
    close: pd.DataFrame,
    signals: pd.DataFrame,
    vnpy_metrics: dict,
    init_cash: float = 100_000.0,
    discrepancy_threshold: float = 0.05,
) -> CrossValidationResult:
    """Cross-validate vbt backtest results against VeighNa results.

    Runs the same signals through both engines and compares metrics.
    Flags discrepancies > threshold for investigation.

    Args:
        close: OHLC price DataFrame.
        signals: Boolean signal DataFrame.
        vnpy_metrics: Dict of VeighNa-computed metrics:
            {'total_return_pct', 'sharpe', 'max_drawdown_pct', 'win_rate_pct'}.
        init_cash: Starting capital.
        discrepancy_threshold: Maximum acceptable metric difference (0.05 = 5%).

    Returns:
        CrossValidationResult with comparison and validity flag.
    """
    result = vbt_signal_to_portfolio(close, signals, init_cash=init_cash)
    vbt_metrics = result["stats"]

    # Map vbt metric names to vnpy metric names for comparison
    metric_map = {
        "total_return": "total_return_pct",
        "sharpe_ratio": "sharpe",
        "max_drawdown": "max_drawdown_pct",
        "win_rate": "win_rate_pct",
    }

    discrepancies = {}
    for vbt_key, vnpy_key in metric_map.items():
        vbt_val = vbt_metrics.get(vbt_key, 0)
        vnpy_val = vnpy_metrics.get(vnpy_key, 0)

        if abs(vnpy_val) > 1e-8:
            diff_pct = abs(vbt_val - vnpy_val) / abs(vnpy_val)
        else:
            diff_pct = abs(vbt_val - vnpy_val)
        discrepancies[vnpy_key] = diff_pct

    max_disc = max(discrepancies.values()) if discrepancies else 0
    is_valid = max_disc <= discrepancy_threshold

    logger.info(
        "Cross-validation: %d metrics compared, max discrepancy=%.2f%%, valid=%s",
        len(discrepancies),
        max_disc * 100,
        is_valid,
    )

    if not is_valid:
        for k, v in discrepancies.items():
            if v > discrepancy_threshold:
                logger.warning(
                    "  DISCREPANCY: %s: vbt=%.4f vs vnpy=%.4f (%.2f%%)",
                    k,
                    vbt_metrics.get(
                        {v: k for k, v in metric_map.items()}.get(k, ""), 0
                    ),
                    vnpy_metrics.get(k, 0),
                    v * 100,
                )

    return CrossValidationResult(
        vbt_metrics=vbt_metrics,
        vnpy_metrics=vnpy_metrics,
        discrepancies=discrepancies,
        is_valid=is_valid,
        threshold=discrepancy_threshold,
    )


# ---------------------------------------------------------------------------
# Signal generation helper for grid search
# ---------------------------------------------------------------------------


def make_param_sweep_signal_func(
    close: pd.Series,
    param_grid: dict[str, list],
    base_entry_condition: callable,
    base_exit_condition: callable | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate entry/exit DataFrames for all parameter combos.

    Each column represents one parameter combination. This is the
    vectorized equivalent of a nested for-loop over param_grid.

    Args:
        close: Price series.
        param_grid: Dict {param_name: [v1, v2, ...]}.
        base_entry_condition: callable(close, **params) -> pd.Series of bool
        base_exit_condition: callable(close, **params) -> pd.Series of bool
            If None, uses inverted entry signal.

    Returns:
        entry_df, exit_df: DataFrames with MultiIndex columns (param_name, value).
    """
    from itertools import product

    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    entry_cols = []
    exit_cols = []

    for combo in product(*param_values):
        params = dict(zip(param_names, combo))
        col_name = "_".join(f"{k}={v}" for k, v in params.items())

        entry_signal = base_entry_condition(close, **params)
        entry_signal.name = col_name
        entry_cols.append(entry_signal)

        if base_exit_condition:
            exit_signal = base_exit_condition(close, **params)
        else:
            exit_signal = ~entry_signal
        exit_signal.name = col_name
        exit_cols.append(exit_signal)

    entry_df = pd.concat(entry_cols, axis=1)
    exit_df = pd.concat(exit_cols, axis=1)

    return entry_df, exit_df


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_param_combo(idx: int | str, param_grid: dict[str, list]) -> dict:
    """Parse best parameter combination from the index."""
    if isinstance(idx, str) and "=" in str(idx):
        params = {}
        for part in str(idx).split("_"):
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    params[k] = float(v) if "." in v else int(v)
                except ValueError:
                    params[k] = v
        return params
    # Fallback: map numeric index to param_grid values
    return {
        name: values[0] for name, values in param_grid.items()
    }


def _compute_pareto(stats_df: pd.DataFrame) -> pd.DataFrame | None:
    """Compute Pareto front (non-dominated solutions) by return vs drawdown."""
    ret_col = next(
        (c for c in stats_df.columns if "return" in c.lower()), None
    )
    dd_col = next(
        (c for c in stats_df.columns if "drawdown" in c.lower()), None
    )

    if ret_col is None or dd_col is None:
        return None

    returns = stats_df[ret_col].values
    drawdowns = stats_df[dd_col].values

    # Pareto dominance: A dominates B if return_A >= return_B and dd_A <= dd_B
    n = len(returns)
    dominated = np.zeros(n, dtype=bool)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if returns[j] >= returns[i] and drawdowns[j] <= drawdowns[i]:
                if returns[j] > returns[i] or drawdowns[j] < drawdowns[i]:
                    dominated[i] = True
                    break

    pareto = stats_df[~dominated].copy()
    pareto = pareto.sort_values(ret_col, ascending=False)

    logger.debug("Pareto front: %d non-dominated solutions out of %d", len(pareto), n)
    return pareto


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pandas as pd
    import numpy as np

    # Generate synthetic price data
    np.random.seed(123)
    n_days = 504
    returns_sim = np.random.randn(n_days) * 0.02
    returns_sim = np.where(np.random.rand(n_days) < 0.02, -0.05, returns_sim)
    price = 100 * np.exp(np.cumsum(returns_sim))
    close = pd.Series(price, index=pd.date_range("2024-01-01", periods=n_days, freq="B"))
    close = close.clip(lower=1.0)

    print("=== vectorbt Adapter Test ===")

    # Test 1: Simple signal-based portfolio
    sma_fast = close.rolling(20).mean()
    sma_slow = close.rolling(60).mean()
    signals = (sma_fast > sma_slow).dropna()
    signals.name = "signal"
    close_aligned = close.loc[signals.index]

    result = vbt_signal_to_portfolio(close_aligned, signals)
    print("\nSingle-strategy metrics:")
    for k, v in result["stats"].items():
        print(f"  {k}: {v:.4f}")

    # Test 2: Cross-validation example
    vnpy_fake = {
        "total_return_pct": result["stats"]["total_return"],
        "sharpe": result["stats"]["sharpe_ratio"],
        "max_drawdown_pct": result["stats"]["max_drawdown"],
        "win_rate_pct": result["stats"]["win_rate"],
    }
    # Deliberately tweak one metric to test discrepancy detection
    vnpy_fake["total_return_pct"] *= 1.08  # 8% difference
    cv_result = vbt_cross_validate(close_aligned, signals, vnpy_fake)
    print(f"\nCross-validation valid: {cv_result.is_valid}")
    print(f"Discrepancies: {cv_result.discrepancies}")
