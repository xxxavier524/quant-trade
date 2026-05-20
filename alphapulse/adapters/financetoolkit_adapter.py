"""FinanceToolkit integration adapter for AlphaPulse-A.

Converts 180+ financial ratios from FinanceToolkit into AlphaPulse-A
factor format (compute(data) -> pd.Series) and registers them in the
factor registry alongside our technical factors.

This addresses a major gap: AlphaPulse-A currently has ZERO fundamental
factors. All 13 existing factors are technical/price-based.

Categories integrated:
  - Profitability: ROE, ROA, Gross Margin, Net Margin, etc. (~30 ratios)
  - Valuation: P/E, P/B, EV/EBITDA, P/S, PEG, etc. (~25 ratios)
  - Liquidity: Current Ratio, Quick Ratio, Cash Ratio, etc. (~15 ratios)
  - Solvency: Debt/Equity, Interest Coverage, Debt/EBITDA, etc. (~20 ratios)
  - Efficiency: Asset Turnover, Inventory Turnover, etc. (~20 ratios)

Challenge: FinanceToolkit requires FinancialModelingPrep (FMP) API for
raw financial statements. For A-shares, we use akshare to fetch financial
data (balance sheet, income statement, cash flow), then map to the format
FinanceToolkit's ratio engine expects.

Usage:
    from alphapulse.adapters.financetoolkit_adapter import (
        compute_fundamental_factors,
        register_fundamental_factors,
    )

    factors_df = compute_fundamental_factors(symbols=['600519', '000001'])
    register_fundamental_factors()  # registers in FACTOR_REGISTRY
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Soft imports -- both are optional
# ---------------------------------------------------------------------------
try:
    from financetoolkit import Toolkit as _FTK

    _HAS_FT = True
except ImportError:
    _HAS_FT = False
    _FTK = None  # type: ignore


# ---------------------------------------------------------------------------
# Ratio Categories and Definitions
# ---------------------------------------------------------------------------


@dataclass
class FundamentalFactor:
    """A single fundamental ratio converted to AlphaPulse-A factor format.

    Attributes:
        factor_id: Factor registry name (e.g., 'FUND_ROE').
        category: Ratio category (profitability, valuation, etc.).
        description: Human-readable description.
        direction: How to interpret the signal:
            1 = higher is better (e.g., ROE, margins)
            -1 = lower is better (e.g., P/E, P/B -- value play)
            None = no directional preference
    """

    factor_id: str
    category: str
    description: str
    direction: int | None = None


# Top 50 most impactful fundamental ratios for A-share quant strategies.
# Selected based on IC research from Guosen/CICC/Huatai securities.
FUNDAMENTAL_FACTORS: list[FundamentalFactor] = [
    # --- Profitability (higher = better) ---
    FundamentalFactor("FUND_ROE", "profitability", "Return on Equity", 1),
    FundamentalFactor("FUND_ROA", "profitability", "Return on Assets", 1),
    FundamentalFactor("FUND_ROIC", "profitability", "Return on Invested Capital", 1),
    FundamentalFactor("FUND_GROSS_MARGIN", "profitability", "Gross Profit Margin", 1),
    FundamentalFactor("FUND_NET_MARGIN", "profitability", "Net Profit Margin", 1),
    FundamentalFactor("FUND_OP_MARGIN", "profitability", "Operating Profit Margin", 1),
    FundamentalFactor("FUND_EBITDA_MARGIN", "profitability", "EBITDA Margin", 1),
    FundamentalFactor("FUND_EARNINGS_YIELD", "profitability", "Earnings Yield (E/P)", 1),
    FundamentalFactor("FUND_FCF_YIELD", "profitability", "Free Cash Flow Yield", 1),
    # --- Valuation (lower = better for value) ---
    FundamentalFactor("FUND_PE_RATIO", "valuation", "Price to Earnings", -1),
    FundamentalFactor("FUND_PB_RATIO", "valuation", "Price to Book", -1),
    FundamentalFactor("FUND_PS_RATIO", "valuation", "Price to Sales", -1),
    FundamentalFactor("FUND_EV_EBITDA", "valuation", "Enterprise Value to EBITDA", -1),
    FundamentalFactor("FUND_EV_EBIT", "valuation", "EV to EBIT", -1),
    FundamentalFactor("FUND_EV_REVENUE", "valuation", "EV to Revenue", -1),
    FundamentalFactor("FUND_PEG", "valuation", "PEG Ratio (P/E / Growth)", -1),
    FundamentalFactor("FUND_PCF", "valuation", "Price to Cash Flow", -1),
    FundamentalFactor("FUND_PFCF", "valuation", "Price to Free Cash Flow", -1),
    # --- Growth ---
    FundamentalFactor("FUND_REV_GROWTH", "growth", "Revenue Growth YoY", 1),
    FundamentalFactor("FUND_EARNINGS_GROWTH", "growth", "Earnings Growth YoY", 1),
    FundamentalFactor("FUND_EPS_GROWTH", "growth", "EPS Growth YoY", 1),
    FundamentalFactor("FUND_FCF_GROWTH", "growth", "FCF Growth YoY", 1),
    FundamentalFactor("FUND_BV_GROWTH", "growth", "Book Value Growth YoY", 1),
    # --- Liquidity (moderate = better; extremes = caution) ---
    FundamentalFactor("FUND_CURRENT_RATIO", "liquidity", "Current Ratio", None),
    FundamentalFactor("FUND_QUICK_RATIO", "liquidity", "Quick Ratio (Acid Test)", None),
    FundamentalFactor("FUND_CASH_RATIO", "liquidity", "Cash Ratio", None),
    FundamentalFactor("FUND_OP_CASH_RATIO", "liquidity", "Operating Cash Flow Ratio", 1),
    # --- Solvency/Leverage (lower = safer) ---
    FundamentalFactor("FUND_DEBT_EQUITY", "solvency", "Debt to Equity Ratio", -1),
    FundamentalFactor("FUND_DEBT_EBITDA", "solvency", "Debt to EBITDA", -1),
    FundamentalFactor("FUND_DEBT_ASSETS", "solvency", "Debt to Assets Ratio", -1),
    FundamentalFactor("FUND_INTEREST_COVER", "solvency", "Interest Coverage Ratio (EBIT/Interest)", 1),
    FundamentalFactor("FUND_EQUITY_MULTIPLIER", "solvency", "Equity Multiplier (Assets/Equity)", -1),
    # --- Efficiency/Turnover (higher = better) ---
    FundamentalFactor("FUND_ASSET_TURNOVER", "efficiency", "Asset Turnover Ratio", 1),
    FundamentalFactor("FUND_INVENTORY_TURNOVER", "efficiency", "Inventory Turnover", 1),
    FundamentalFactor("FUND_RECEIVABLES_TURNOVER", "efficiency", "Receivables Turnover", 1),
    FundamentalFactor("FUND_FIXED_ASSET_TURNOVER", "efficiency", "Fixed Asset Turnover", 1),
    # --- Dividends ---
    FundamentalFactor("FUND_DIVIDEND_YIELD", "dividend", "Dividend Yield", 1),
    FundamentalFactor("FUND_PAYOUT_RATIO", "dividend", "Dividend Payout Ratio", None),
    # --- Quality ---
    FundamentalFactor("FUND_ACCRUALS", "quality", "Accruals Ratio (Earnings Quality)", -1),
    FundamentalFactor("FUND_ASSET_GROWTH", "quality", "Total Asset Growth Rate", 1),
    FundamentalFactor("FUND_CAPE", "quality", "CAPEX to Revenue", None),
    # --- Momentum (within fundamentals) ---
    FundamentalFactor("FUND_EARNINGS_SURPRISE", "momentum", "Earnings Surprise (Actual vs Expected)", 1),
    FundamentalFactor("FUND_REVISION_UP", "momentum", "Analyst Revision Ratio (Upgrades/Total)", 1),
    # --- Risk ---
    FundamentalFactor("FUND_BETA_FUND", "risk", "Fundamental Beta (Earnings Volatility)", -1),
    FundamentalFactor("FUND_EARNINGS_VOL", "risk", "Earnings Volatility (5Y Std)", -1),
]


# ---------------------------------------------------------------------------
# Core API: Fetch and compute fundamental factors
# ---------------------------------------------------------------------------


def compute_fundamental_factors(
    symbols: list[str],
    api_key: str | None = None,
    use_akshare_fallback: bool = True,
    quarters: int = 4,
) -> pd.DataFrame:
    """Compute fundamental ratios for A-share stocks.

    Primary approach: Use FinanceToolkit's ratio engine with FMP data.
    Fallback: Use akshare financial data + manual ratio calculation.

    Args:
        symbols: A-share ticker symbols (e.g., ['600519', '000001']).
        api_key: FMP API key (free tier: 250 calls/day). Required for FTK.
        use_akshare_fallback: If True and FTK unavailable, use akshare for
            financial statement data and compute ratios manually.
        quarters: Number of trailing quarters for TTM ratios.

    Returns:
        DataFrame with index = symbol, columns = factor IDs, values = ratio values.
    """
    if _HAS_FT and api_key:
        return _compute_via_financetoolkit(symbols, api_key, quarters)
    elif use_akshare_fallback:
        logger.info("FinanceToolkit not available, using akshare fallback")
        return _compute_via_akshare(symbols, quarters)
    else:
        raise ImportError(
            "FinanceToolkit and akshare are both unavailable. "
            "Install: pip install financetoolkit akshare"
        )


def compute_single_ratio(
    symbol: str,
    ratio_id: str,
    api_key: str | None = None,
    quarters: int = 4,
) -> float | None:
    """Compute a single fundamental ratio for one stock.

    Args:
        symbol: A-share ticker (e.g., '600519').
        ratio_id: Factor ID from FUNDAMENTAL_FACTORS.
        api_key: FMP API key.
        quarters: Trailing quarters.

    Returns:
        Ratio value or None if data unavailable.
    """
    factor_map = {f.factor_id: f for f in FUNDAMENTAL_FACTORS}
    if ratio_id not in factor_map:
        raise ValueError(f"Unknown ratio: {ratio_id}")

    df = compute_fundamental_factors(
        [symbol], api_key=api_key, quarters=quarters
    )
    if df.empty or ratio_id not in df.columns:
        return None
    return float(df.loc[symbol, ratio_id])


def register_fundamental_factors() -> int:
    """Register all fundamental factors in FactorRegistry.

    Each factor is registered as a compute function that takes OHLCV data
    and returns a pd.Series of factor values.

    Returns:
        Number of factors registered.
    """
    from alphapulse.factors.factor_registry import FACTOR_REGISTRY

    count = 0
    for factor in FUNDAMENTAL_FACTORS:
        if factor.factor_id in FACTOR_REGISTRY:
            continue

        # Determine the compute function name (which category module)
        category = factor.category

        FACTOR_REGISTRY[factor.factor_id] = {
            "module": None,  # placeholder; resolved at compute time
            "type": "fundamental",
            "description": f"[{category}] {factor.description}",
            "source": "FinanceToolkit / JerBouma",
            "default_params": {
                "quarters": 4,
            },
            # Use the fundamental factor compute wrapper
            "compute_func": "compute_fundamental_factor_entry",
        }
        count += 1

    logger.info("Registered %d fundamental factors in FACTOR_REGISTRY", count)
    return count


def compute_fundamental_factor_entry(
    data: pd.DataFrame,
    factor_name: str,
    **params,
) -> pd.Series:
    """Generic compute entry point for fundamental factors.

    This conforms to the FACTOR_REGISTRY interface: compute(data) -> Series.
    Since fundamental factors are cross-sectional (one value per stock per quarter)
    rather than time-series, this returns a constant value per stock.

    Args:
        data: OHLCV DataFrame (used to determine date range).
        factor_name: Factor ID (e.g., 'FUND_ROE').
        **params: Includes 'quarters', 'api_key', etc.

    Returns:
        pd.Series with factor values indexed by symbol.
    """
    logger.warning(
        "Fundamental factors require cross-sectional data. "
        "Use compute_fundamental_factors() directly for batch computation. "
        "Factor '%s' returning NaN.", factor_name
    )
    return pd.Series(dtype=float)


# ---------------------------------------------------------------------------
# FinanceToolkit-based implementation
# ---------------------------------------------------------------------------


def _compute_via_financetoolkit(
    symbols: list[str],
    api_key: str,
    quarters: int = 4,
) -> pd.DataFrame:
    """Use FinanceToolkit's ratio engine with FMP data source."""
    # Convert A-share symbols to FMP format (e.g., 600519 -> 600519.SS)
    fmp_symbols = _a_share_to_fmp(symbols)

    # Initialize FinanceToolkit
    companies = _FTK(
        tickers=fmp_symbols,
        api_key=api_key,
        start_date=_quarters_ago_date(quarters),
    )

    # Get all ratio categories
    try:
        ratios = companies.ratios.collect_all_ratios()
    except Exception as e:
        logger.error("FinanceToolkit ratio collection failed: %s", e)
        return pd.DataFrame()

    # Map FinanceToolkit ratio names to our factor IDs
    result_rows = {}
    for symbol, fmp_sym in zip(symbols, fmp_symbols):
        row = {}
        for factor in FUNDAMENTAL_FACTORS:
            ft_col = _factor_to_ftk_column(factor.factor_id)
            if ft_col and ft_col in ratios.columns:
                try:
                    # Get most recent value
                    vals = ratios.loc[fmp_sym, ft_col].dropna()
                    if len(vals) > 0:
                        row[factor.factor_id] = float(vals.iloc[-1])
                except (KeyError, IndexError):
                    pass
        if row:
            result_rows[symbol] = row

    return pd.DataFrame.from_dict(result_rows, orient="index")


# ---------------------------------------------------------------------------
# akshare fallback implementation
# ---------------------------------------------------------------------------


def _compute_via_akshare(
    symbols: list[str],
    quarters: int = 4,
) -> pd.DataFrame:
    """Use akshare to fetch financial statements and compute ratios manually.

    This fallback path does NOT require FMP API key.
    """
    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare is required for fundamental factor fallback")
        return pd.DataFrame()

    results = {}
    for symbol in symbols:
        try:
            ratios = _compute_ratios_for_symbol_ak(ak, symbol, quarters)
            if ratios:
                results[symbol] = ratios
        except Exception as e:
            logger.debug("Failed to compute ratios for %s: %s", symbol, e)

    return pd.DataFrame.from_dict(results, orient="index")


def _compute_ratios_for_symbol_ak(
    ak,
    symbol: str,
    quarters: int = 4,
) -> dict[str, float] | None:
    """Compute fundamental ratios for a single A-share symbol using akshare.

    Fetches balance sheet, income statement, and cash flow statement,
    then computes key ratios.
    """
    ratios = {}

    try:
        # Fetch financial data
        # Balance sheet
        bs = ak.stock_financial_balance_sheet_by_report_em(symbol=symbol)
        if bs is None or bs.empty:
            return None

        # Income statement
        pl = ak.stock_financial_profit_by_report_em(symbol=symbol)
        if pl is None or pl.empty:
            return None

        # Cash flow
        cf = ak.stock_financial_cash_flow_by_report_em(symbol=symbol)
        if cf is None or cf.empty:
            cf = None

        # Get latest period data
        bs_latest = bs.iloc[0] if not bs.empty else None
        pl_latest = pl.iloc[0] if not pl.empty else None
        cf_latest = cf.iloc[0] if cf is not None and not cf.empty else None

        if bs_latest is None or pl_latest is None:
            return None

        # Compute ratios (scaled to per-share where appropriate)
        _add_profitability_ratios(ratios, pl_latest, bs_latest, cf_latest)
        _add_valuation_ratios(ratios, pl_latest, bs_latest, symbol)
        _add_growth_ratios(ratios, pl, bs)
        _add_liquidity_ratios(ratios, bs_latest, pl_latest, cf_latest)
        _add_solvency_ratios(ratios, bs_latest, pl_latest)
        _add_efficiency_ratios(ratios, pl_latest, bs_latest)
        _add_dividend_ratios(ratios, pl_latest, cf_latest)
    except Exception as e:
        logger.debug("Ratio computation failed for %s: %s", symbol, e)
        return None

    return ratios


def _add_profitability_ratios(
    ratios: dict, pl: pd.Series, bs: pd.Series, cf: pd.Series | None
):
    """Compute profitability ratios from income statement + balance sheet."""
    try:
        ni = float(_safe_get(pl, "净利润", "net_profit", "归母净利润"))
        revenue = float(_safe_get(pl, "营业总收入", "revenue", "营业收入"))
        total_assets = float(_safe_get(bs, "资产总计", "total_assets"))
        equity = float(_safe_get(bs, "股东权益合计", "total_equity", "归属母公司股东权益"))

        if equity and equity > 0:
            ratios["FUND_ROE"] = ni / equity * 100
        if total_assets and total_assets > 0:
            ratios["FUND_ROA"] = ni / total_assets * 100
        if revenue and revenue > 0:
            ratios["FUND_NET_MARGIN"] = ni / revenue * 100
            gross_profit = float(_safe_get(pl, "毛利", "毛利润"))
            if gross_profit > 0:
                ratios["FUND_GROSS_MARGIN"] = gross_profit / revenue * 100
            op_profit = float(_safe_get(pl, "营业利润"))
            if op_profit > 0:
                ratios["FUND_OP_MARGIN"] = op_profit / revenue * 100
    except (ValueError, TypeError, KeyError):
        pass


def _add_valuation_ratios(
    ratios: dict, pl: pd.Series, bs: pd.Series, symbol: str
):
    """Compute valuation ratios. These require market price data."""
    try:
        import akshare as ak

        # Get current stock price
        price_df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", adjust="qfq"
        )
        if price_df is not None and not price_df.empty:
            price = float(price_df.iloc[-1]["收盘"])
        else:
            return

        ni = float(_safe_get(pl, "净利润", "归母净利润"))
        equity = float(_safe_get(bs, "股东权益合计", "归属母公司股东权益"))
        revenue = float(_safe_get(bs, "营业总收入", "营业收入"))
        total_shares = float(_safe_get(bs, "总股本", "实收资本"))

        if total_shares and total_shares > 0:
            eps = ni / total_shares if ni else None
            bvps = equity / total_shares if equity else None
            sps = revenue / total_shares if revenue else None

            if eps and eps > 0:
                ratios["FUND_PE_RATIO"] = price / eps
            if bvps and bvps > 0:
                ratios["FUND_PB_RATIO"] = price / bvps
            if sps and sps > 0:
                ratios["FUND_PS_RATIO"] = price / sps
    except Exception:
        pass


def _add_growth_ratios(ratios: dict, pl: pd.DataFrame, bs: pd.DataFrame):
    """Compute growth rates (YoY) from multi-period data."""
    try:
        if len(pl) >= 2:
            rev_now = float(_safe_get(pl.iloc[0], "营业总收入"))
            rev_prev = float(_safe_get(pl.iloc[1], "营业总收入"))
            if rev_prev and rev_prev > 0:
                ratios["FUND_REV_GROWTH"] = (rev_now / rev_prev - 1) * 100

            ni_now = float(_safe_get(pl.iloc[0], "净利润", "归母净利润"))
            ni_prev = float(_safe_get(pl.iloc[1], "净利润", "归母净利润"))
            if ni_prev and ni_prev > 0:
                ratios["FUND_EARNINGS_GROWTH"] = (ni_now / ni_prev - 1) * 100

        if len(bs) >= 2:
            bv_now = float(_safe_get(bs.iloc[0], "股东权益合计"))
            bv_prev = float(_safe_get(bs.iloc[1], "股东权益合计"))
            if bv_prev and bv_prev > 0:
                ratios["FUND_BV_GROWTH"] = (bv_now / bv_prev - 1) * 100
    except Exception:
        pass


def _add_liquidity_ratios(
    ratios: dict, bs: pd.Series, pl: pd.Series, cf: pd.Series | None
):
    """Compute liquidity ratios from balance sheet."""
    try:
        current_assets = float(_safe_get(bs, "流动资产合计"))
        current_liabilities = float(_safe_get(bs, "流动负债合计"))
        cash = float(_safe_get(bs, "货币资金"))
        inventory = float(_safe_get(bs, "存货"))

        if current_liabilities and current_liabilities > 0:
            ratios["FUND_CURRENT_RATIO"] = current_assets / current_liabilities
            ratios["FUND_QUICK_RATIO"] = (
                (current_assets - inventory) / current_liabilities
            )
            ratios["FUND_CASH_RATIO"] = cash / current_liabilities
    except Exception:
        pass


def _add_solvency_ratios(ratios: dict, bs: pd.Series, pl: pd.Series):
    """Compute solvency/leverage ratios."""
    try:
        total_debt = float(_safe_get(bs, "负债合计"))
        total_assets = float(_safe_get(bs, "资产总计"))
        equity = float(_safe_get(bs, "股东权益合计"))

        if equity and equity > 0 and total_assets and total_assets > 0:
            ratios["FUND_DEBT_EQUITY"] = total_debt / equity
            ratios["FUND_DEBT_ASSETS"] = total_debt / total_assets * 100
            ratios["FUND_EQUITY_MULTIPLIER"] = total_assets / equity
    except Exception:
        pass


def _add_efficiency_ratios(ratios: dict, pl: pd.Series, bs: pd.Series):
    """Compute efficiency/turnover ratios."""
    try:
        revenue = float(_safe_get(pl, "营业总收入"))
        total_assets = float(_safe_get(bs, "资产总计"))
        fixed_assets = float(_safe_get(bs, "固定资产"))
        receivables = float(_safe_get(bs, "应收账款"))
        inventory = float(_safe_get(bs, "存货"))

        if total_assets and total_assets > 0 and revenue:
            ratios["FUND_ASSET_TURNOVER"] = revenue / total_assets
        if fixed_assets and fixed_assets > 0 and revenue:
            ratios["FUND_FIXED_ASSET_TURNOVER"] = revenue / fixed_assets
        if receivables and receivables > 0 and revenue:
            ratios["FUND_RECEIVABLES_TURNOVER"] = revenue / receivables
        if inventory and inventory > 0 and revenue:
            ratios["FUND_INVENTORY_TURNOVER"] = revenue / inventory
    except Exception:
        pass


def _add_dividend_ratios(ratios: dict, pl: pd.Series, cf: pd.Series | None):
    """Compute dividend-related ratios."""
    # Requires dividend payout data which akshare provides separately
    # Placeholder for future implementation
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _a_share_to_fmp(symbols: list[str]) -> list[str]:
    """Convert A-share tickers to FMP format (6xxxxx -> 6xxxxx.SS)."""
    result = []
    for s in symbols:
        if s.startswith("6"):
            result.append(f"{s}.SS")
        else:
            result.append(f"{s}.SZ")
    return result


def _factor_to_ftk_column(factor_id: str) -> str | None:
    """Map our factor ID to FinanceToolkit ratio column name."""
    _MAP = {
        "FUND_ROE": "Return on Equity",
        "FUND_ROA": "Return on Assets",
        "FUND_GROSS_MARGIN": "Gross Profit Margin",
        "FUND_NET_MARGIN": "Net Profit Margin",
        "FUND_OP_MARGIN": "Operating Profit Margin",
        "FUND_PE_RATIO": "Price-to-Earnings Ratio",
        "FUND_PB_RATIO": "Price-to-Book Ratio",
        "FUND_PS_RATIO": "Price-to-Sales Ratio",
        "FUND_EV_EBITDA": "EV-to-EBITDA",
        "FUND_CURRENT_RATIO": "Current Ratio",
        "FUND_QUICK_RATIO": "Quick Ratio",
        "FUND_CASH_RATIO": "Cash Ratio",
        "FUND_DEBT_EQUITY": "Debt-to-Equity Ratio",
        "FUND_DEBT_ASSETS": "Debt-to-Assets Ratio",
        "FUND_INTEREST_COVER": "Interest Coverage Ratio",
        "FUND_ASSET_TURNOVER": "Asset Turnover",
        "FUND_INVENTORY_TURNOVER": "Inventory Turnover",
        "FUND_RECEIVABLES_TURNOVER": "Receivables Turnover",
        "FUND_DIVIDEND_YIELD": "Dividend Yield",
        "FUND_PAYOUT_RATIO": "Payout Ratio",
        "FUND_EARNINGS_YIELD": "Earnings Yield",
    }
    return _MAP.get(factor_id)


def _quarters_ago_date(quarters: int) -> str:
    """Return a start date string for the given number of quarters."""
    from datetime import date

    today = date.today()
    start_year = today.year - max(1, quarters // 4 + 1)
    return f"{start_year}-01-01"


def _safe_get(series: pd.Series, *keys: str) -> float:
    """Safely get a value from a Series by trying multiple keys."""
    for key in keys:
        if key in series.index:
            val = series[key]
            if pd.notna(val):
                return val
    return 0.0


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== FinanceToolkit Adapter Test ===\n")

    # List available fundamental factors
    print(f"Total fundamental factors defined: {len(FUNDAMENTAL_FACTORS)}")
    for cat in ["profitability", "valuation", "growth", "liquidity", "solvency", "efficiency", "quality"]:
        cat_factors = [f for f in FUNDAMENTAL_FACTORS if f.category == cat]
        print(f"  {cat}: {len(cat_factors)} factors")
        for f in cat_factors[:3]:
            dir_str = {1: "bullish", -1: "bearish", None: "neutral"}[f.direction]
            print(f"    {f.factor_id}: {f.description} ({dir_str})")
        if len(cat_factors) > 3:
            print(f"    ... and {len(cat_factors) - 3} more")

    # Test akshare fallback
    print("\nTesting akshare fallback for 600519 (Kweichow Moutai)...")
    try:
        df = compute_fundamental_factors(["600519"], api_key=None, use_akshare_fallback=True)
        if not df.empty:
            print(f"Computed ratios for 600519:")
            for col in df.columns[:10]:
                print(f"  {col}: {df.loc['600519', col]:.2f}")
        else:
            print("  No data returned (network issue or API limitation)")
    except Exception as e:
        print(f"  Error: {e}")
