"""yfinance adapter for A-share equity data.

Provides a unified interface for fetching A-share stock data via Yahoo Finance.
Serves as a secondary/alternative data source alongside the primary baostock/akshare
pipeline.

Known limitations:
- Requires network access to Yahoo Finance (may need proxy/VPN in mainland China)
- Rate-limited: avoid >2 requests/second, use moderate batch sizes
- A-share data quality/stability below domestic sources (akshare, baostock)
- Not recommended as the PRIMARY A-share data source for production quant systems

Symbol format:
- Shanghai (6xxxxx): 600519.SS
- Shenzhen (0xxxxx, 3xxxxx): 000001.SZ, 300750.SZ
- STAR Market / 科创板 (688xxx): 688981.SS (Shanghai exchange)
- Beijing Stock Exchange (8xxxxx): Not supported by Yahoo Finance
"""

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHANGHAI_PREFIXES: tuple[str, ...] = ("6", "688", "689")
SHENZHEN_PREFIXES: tuple[str, ...] = ("0", "2", "3")
BEIJING_PREFIXES: tuple[str, ...] = ("8", "4")

# Columns we standardise on; yfinance returns slightly different names
# depending on auto_adjust / actions flags.
YFINANCE_COLUMN_MAP: dict[str, str] = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------


def normalize_a_share_symbol(code: str) -> str:
    """Convert a 6-digit A-share code to Yahoo Finance ticker format.

    Args:
        code: 6-character numeric string, e.g. "600519" or "000001".

    Returns:
        Yahoo Finance ticker, e.g. "600519.SS" or "000001.SZ".

    Raises:
        ValueError: If *code* is not a 6-digit numeric string.
    """
    code = str(code).strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise ValueError(
            f"Invalid A-share code: {code!r}. Expected a 6-digit numeric string."
        )

    if code.startswith("6"):
        return f"{code}.SS"
    if code.startswith("0") or code.startswith("2") or code.startswith("3"):
        return f"{code}.SZ"
    # Beijing Stock Exchange / NEEQ -- not supported by Yahoo Finance
    return f"{code}.SS"  # best-effort fallback


def denormalize_symbol(yahoo_symbol: str) -> str:
    """Strip the exchange suffix, returning the raw 6-digit code.

    >>> denormalize_symbol("600519.SS")
    "600519"
    """
    return yahoo_symbol.split(".")[0]


def is_shanghai(code: str) -> bool:
    """Return True if the 6-digit code belongs to Shanghai Stock Exchange."""
    code = str(code).strip().zfill(6)
    return code.startswith("6")


def is_shenzhen(code: str) -> bool:
    """Return True if the 6-digit code belongs to Shenzhen Stock Exchange."""
    code = str(code).strip().zfill(6)
    return code.startswith("0") or code.startswith("2") or code.startswith("3")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class StockMeta:
    """Normalised stock metadata returned by the adapter."""

    symbol: str  # raw 6-digit code
    yahoo_symbol: str
    name: str
    market_cap: Optional[float] = None  # CNY
    sector: Optional[str] = None
    industry: Optional[str] = None
    pe_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None


# ---------------------------------------------------------------------------
# Core adapter
# ---------------------------------------------------------------------------


class YFinanceAdapter:
    """Adapter that wraps yfinance for A-share data retrieval.

    Usage::

        adapter = YFinanceAdapter()
        df = adapter.get_history("600519", start="2024-01-01", end="2024-03-31")
        meta = adapter.get_metadata("600519")

    Notes:
        - This adapter is designed for **lightweight/ad-hoc** A-share queries.
        - For batch/historical A-share data, prefer **akshare** or **baostock**.
    """

    def __init__(
        self,
        rate_limit_delay: float = 0.5,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
    ) -> None:
        """Initialise the adapter.

        Args:
            rate_limit_delay: Minimum seconds between API calls (default 0.5).
            max_retries: Max retries on transient errors.
            retry_backoff: Backoff multiplier per retry (exponential).
        """
        self._rate_limit_delay = rate_limit_delay
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_history(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: str = "max",
        interval: str = "1d",
        auto_adjust: bool = True,
    ) -> pd.DataFrame:
        """Download historical OHLCV data for an A-share stock.

        Args:
            symbol: 6-digit A-share code or full yahoo ticker.
            start: Start date (YYYY-MM-DD). If None, uses *period*.
            end: End date (YYYY-MM-DD). If None, uses today.
            period: Predefined period if *start* is None
                    (1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max).
            interval: Bar interval (1d, 1wk, 1mo).
            auto_adjust: If True, open/high/low/close are already adjusted
                         (same as 'Adj Close').

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date, sorted ascending. Empty DataFrame on failure.
        """
        yahoo_symbol = _resolve_yahoo_symbol(symbol)
        start = _sanitise_start(start)
        end = _sanitise_end(end)

        import yfinance as yf

        self._rate_limit_wait()

        for attempt in range(self._max_retries):
            try:
                ticker = yf.Ticker(yahoo_symbol)
                df = ticker.history(
                    start=start,
                    end=end,
                    period=period,
                    interval=interval,
                    auto_adjust=auto_adjust,
                )
                if df.empty:
                    logger.warning(
                        "yfinance returned empty DataFrame for %s (%s - %s, period=%s)",
                        yahoo_symbol,
                        start,
                        end,
                        period,
                    )
                    return pd.DataFrame()

                df = self._normalise_columns(df)
                self._last_call = time.monotonic()
                return df

            except Exception as exc:
                logger.warning(
                    "yfinance request failed for %s (attempt %d/%d): %s",
                    yahoo_symbol,
                    attempt + 1,
                    self._max_retries,
                    exc,
                )
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_backoff ** attempt)
                else:
                    logger.error(
                        "All retries exhausted for %s", yahoo_symbol
                    )
                    return pd.DataFrame()

        return pd.DataFrame()  # unreachable, satisfies type checker

    def get_metadata(self, symbol: str) -> Optional[StockMeta]:
        """Fetch basic company metadata for an A-share stock.

        Returns None if the ticker is not found or all fields are empty.
        """
        yahoo_symbol = _resolve_yahoo_symbol(symbol)

        import yfinance as yf

        self._rate_limit_wait()

        try:
            ticker = yf.Ticker(yahoo_symbol)
            info = ticker.info
            self._last_call = time.monotonic()
        except Exception as exc:
            logger.error("Failed to fetch metadata for %s: %s", yahoo_symbol, exc)
            return None

        if not info or info.get("trailingPegRatio") is None and not info.get("shortName"):
            logger.debug("No metadata returned for %s", yahoo_symbol)
            return None

        return StockMeta(
            symbol=denormalize_symbol(yahoo_symbol),
            yahoo_symbol=yahoo_symbol,
            name=info.get("shortName") or info.get("longName") or "",
            market_cap=info.get("marketCap"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            pe_ratio=info.get("trailingPE") or info.get("forwardPE"),
            dividend_yield=info.get("dividendYield"),
        )

    def get_dividends(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch dividend history."""
        yahoo_symbol = _resolve_yahoo_symbol(symbol)

        import yfinance as yf

        self._rate_limit_wait()
        try:
            ticker = yf.Ticker(yahoo_symbol)
            divs = ticker.dividends
            self._last_call = time.monotonic()
            if divs is None or divs.empty:
                return pd.DataFrame(columns=["date", "dividends"])
            df = divs.reset_index()
            df.columns = ["date", "dividends"]
            if start:
                df = df[df["date"] >= start]
            if end:
                df = df[df["date"] <= end]
            return df.sort_values("date").reset_index(drop=True)
        except Exception as exc:
            logger.error("Failed to fetch dividends for %s: %s", yahoo_symbol, exc)
            return pd.DataFrame(columns=["date", "dividends"])

    def get_splits(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch stock splits history."""
        yahoo_symbol = _resolve_yahoo_symbol(symbol)

        import yfinance as yf

        self._rate_limit_wait()
        try:
            ticker = yf.Ticker(yahoo_symbol)
            splits = ticker.splits
            self._last_call = time.monotonic()
            if splits is None or splits.empty:
                return pd.DataFrame(columns=["date", "splits"])
            df = splits.reset_index()
            df.columns = ["date", "splits"]
            if start:
                df = df[df["date"] >= start]
            if end:
                df = df[df["date"] <= end]
            return df.sort_values("date").reset_index(drop=True)
        except Exception as exc:
            logger.error("Failed to fetch splits for %s: %s", yahoo_symbol, exc)
            return pd.DataFrame(columns=["date", "splits"])

    def batch_get_history(
        self,
        symbols: list[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: str = "max",
        interval: str = "1d",
        group_by: str = "ticker",
        threads: bool = False,
    ) -> pd.DataFrame:
        """Batch download using ``yf.download`` (multi-ticker in one call).

        Args:
            symbols: List of 6-digit codes or yahoo tickers.
            start/end/period/interval: As in :meth:`get_history`.
            group_by: 'ticker' returns MultiIndex columns; 'column' groups by field.
            threads: If True, use yfinance's built-in threading.

        Returns:
            Multi-ticker DataFrame or empty DataFrame on failure.
        """
        yahoo_symbols = [_resolve_yahoo_symbol(s) for s in symbols]

        import yfinance as yf

        self._rate_limit_wait()
        try:
            df = yf.download(
                yahoo_symbols,
                start=_sanitise_start(start),
                end=_sanitise_end(end),
                period=period,
                interval=interval,
                group_by=group_by,
                threads=threads,
                auto_adjust=True,
            )
            self._last_call = time.monotonic()

            if df.empty:
                return pd.DataFrame()

            # Flatten multi-level column names
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ["_".join(col).strip() for col in df.columns.values]
                rename_map: dict[str, str] = {}
                for col in df.columns:
                    for orig, target in YFINANCE_COLUMN_MAP.items():
                        if orig in col:
                            suffix = col.split(orig)[-1]
                            rename_map[col] = (
                                f"{target}{suffix}".rstrip("_")
                            )
                    if col not in rename_map:
                        rename_map[col] = col.lower()
                df.rename(columns=rename_map, inplace=True)

            return df

        except Exception as exc:
            logger.error("Batch download failed: %s", exc)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rate_limit_wait(self) -> None:
        """Enforce minimum delay between API calls."""
        if self._last_call:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._rate_limit_delay:
                time.sleep(self._rate_limit_delay - elapsed)

    @staticmethod
    def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Rename yfinance columns to lowercase and drop empty rows."""
        df = df.rename(columns=YFINANCE_COLUMN_MAP)
        # Keep only standard columns
        keep = [c for c in YFINANCE_COLUMN_MAP.values() if c in df.columns]
        df = df[keep]
        if df.index.name is not None and df.index.name.lower() in ("date", "datetime"):
            df.index.name = "date"
        return df


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def _resolve_yahoo_symbol(symbol: str) -> str:
    """Convert a user-provided symbol to a Yahoo Finance ticker."""
    symbol = symbol.strip()
    if "." in symbol:  # already has exchange suffix
        return symbol
    return normalize_a_share_symbol(symbol)


def _sanitise_start(start: Optional[str]) -> Optional[str]:
    """Return a valid start date string or today - 5y."""
    if start is None:
        return (date.today() - timedelta(days=5 * 365)).isoformat()
    # Validate
    datetime.strptime(start, "%Y-%m-%d")
    return start


def _sanitise_end(end: Optional[str]) -> Optional[str]:
    """Return a valid end date string or today."""
    if end is None:
        return date.today().isoformat()
    datetime.strptime(end, "%Y-%m-%d")
    return end


# ---------------------------------------------------------------------------
# Degraded-mode detection
# ---------------------------------------------------------------------------


def is_yfinance_available() -> bool:
    """Check if yfinance can reach Yahoo Finance (lightweight connectivity test).

    Returns True if the library is importable and a simple request succeeds.
    """
    try:
        import yfinance as yf  # noqa: F401
    except ImportError:
        return False

    # Lightweight check: try to access a well-known ticker
    try:
        tk = yf.Ticker("AAPL")
        _ = tk.history(period="1d")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public convenience functions (module-level)
# ---------------------------------------------------------------------------

# Cached symbol resolution to avoid recomputing .SS/.SZ mapping
@lru_cache(maxsize=512)
def resolve_symbol_cached(code: str) -> str:
    """Cached version of normalize_a_share_symbol."""
    return normalize_a_share_symbol(code)
