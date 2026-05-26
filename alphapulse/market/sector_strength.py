"""Sector strength ranking and filtering using East Money industry classification."""
import concurrent.futures
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Hard timeout for each individual network call (seconds)
_NET_TIMEOUT = 8


def _network_call(func, timeout=_NET_TIMEOUT, *args, **kwargs):
    """Execute *func* in a daemon thread with a hard timeout.

    Returns the function's return value on success, or ``None`` on timeout /
    unhandled exception.  The calling thread is **never** blocked longer than
    *timeout* seconds because the thread pool is torn down with
    ``wait=False``.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.warning("Network call timed out after %ss", timeout)
            return None
        except Exception:
            logger.debug("Network call failed", exc_info=True)
            return None
    finally:
        pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_sector_data() -> pd.DataFrame:
    """Fetch all East Money industry board list via akshare, fallback to THS."""

    def _try_em():
        import akshare as ak
        return ak.stock_board_industry_name_em()

    def _try_ths():
        import akshare as ak
        return ak.stock_board_industry_summary_ths()

    for source_name, source_func in [("EM", _try_em), ("THS", _try_ths)]:
        result = _network_call(source_func)
        if result is not None and isinstance(result, pd.DataFrame) and len(result) > 0:
            return result
        logger.debug("%s sector list fetch returned empty or None", source_name)

    logger.warning("All sector data sources failed – returning empty DataFrame")
    return pd.DataFrame()


def fetch_sector_history(sector_code: str, days: int = 20) -> pd.DataFrame:
    """Fetch sector index history for *days* days, fallback East Money -> THS."""

    def _try_em():
        import akshare as ak
        df = ak.stock_board_industry_hist_em(symbol=sector_code, adjust="")
        return df if (df is not None and len(df) > 0) else pd.DataFrame()

    def _try_ths():
        import akshare as ak
        df = ak.stock_board_industry_index_ths(
            symbol=sector_code, start_date="", end_date=""
        )
        return df if (df is not None and len(df) > 0) else pd.DataFrame()

    for source_name, source_func in [("EM", _try_em), ("THS", _try_ths)]:
        result = _network_call(source_func)
        if result is not None and isinstance(result, pd.DataFrame) and len(result) > 0:
            return result.tail(days)
        logger.debug("%s history fetch for %s returned empty", source_name, sector_code)

    return pd.DataFrame()


def compute_sector_strength(
    sector_code: str, sector_name: str, benchmark_return: float = 0.0,
) -> dict:
    """Compute strength score for a single sector (0-100).

    Score formula
    -------------
    * Excess return scoring  –  0-40
    * MA trend alignment      –  0-30  (MA5/10/20)
    * Volume trend            –  0-30  (vol MA5 vs MA10)

    Returns
    -------
    dict with keys: code, name, score, excess_return, trend_score, vol_score
    """
    df = fetch_sector_history(sector_code, days=20)

    # --- Validate DataFrame --------------------------------------------------
    if df is None or df.empty:
        return _zero_result(sector_code, sector_name)

    # Detect close column
    close_col = _find_column(df, ("收盘", "close", "Close", "CLOSE"))
    if close_col is None:
        return _zero_result(sector_code, sector_name)

    # Detect volume column
    vol_col = _find_column(df, ("成交量", "volume", "Volume", "VOLUME"))

    closes = pd.to_numeric(df[close_col], errors="coerce").dropna()
    if len(closes) < 5:
        return _zero_result(sector_code, sector_name)

    # --- Excess return scoring (0-40) ----------------------------------------
    sector_return = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
    excess = sector_return - benchmark_return
    # Map: excess = -10 -> 0, excess = 0 -> 20, excess = 10 -> 40
    excess_score = min(max(excess * 2 + 20, 0), 40)

    # --- MA trend scoring (0-30) ---------------------------------------------
    ma5 = closes.rolling(5).mean().iloc[-1]
    ma10 = closes.rolling(10).mean().iloc[-1]
    ma20 = closes.rolling(min(20, len(closes))).mean().iloc[-1]

    trend_score = 0
    if pd.notna(ma5) and pd.notna(ma10):
        if ma5 > ma10:
            trend_score += 15
        if pd.notna(ma20) and len(closes) >= 10:
            if ma10 > ma20:
                trend_score += 15
            else:
                trend_score += 8
        else:
            trend_score += 8
    else:
        trend_score = 15

    # --- Volume trend scoring (0-30) -----------------------------------------
    if vol_col is not None:
        vols = pd.to_numeric(df[vol_col], errors="coerce").dropna()
        if len(vols) >= 10:
            vol_ma5 = vols.rolling(5).mean().iloc[-1]
            vol_ma10 = vols.rolling(10).mean().iloc[-1]
            if pd.notna(vol_ma5) and pd.notna(vol_ma10) and vol_ma10 > 0:
                if vol_ma5 > vol_ma10 * 1.1:
                    vol_score = 30
                elif vol_ma5 > vol_ma10:
                    vol_score = 20
                else:
                    vol_score = 10
            else:
                vol_score = 15
        elif len(vols) >= 5:
            vol_score = 20
        else:
            vol_score = 15
    else:
        vol_score = 15

    total = excess_score + trend_score + vol_score

    return {
        "code": sector_code,
        "name": sector_name,
        "score": round(total, 1),
        "excess_return": round(excess, 2),
        "trend_score": trend_score,
        "vol_score": vol_score,
    }


def rank_sectors() -> pd.DataFrame:
    """Rank all sectors by strength score (descending).

    Iterates every East Money industry board, computes ``compute_sector_strength``
    for each, and returns a DataFrame sorted by score descending.  Entries with
    score == 0 are excluded.
    """
    df = fetch_sector_data()
    if df.empty:
        logger.warning("Cannot rank sectors – sector list is empty")
        return pd.DataFrame()

    code_col, name_col = _detect_code_name_columns(df)
    if code_col is None or name_col is None:
        return pd.DataFrame()

    results: list[dict] = []
    total = len(df)

    for i, (_, row) in enumerate(df.iterrows()):
        code = str(row[code_col])
        name = str(row[name_col])
        logger.debug("Ranking sector %s/%s: %s", i + 1, total, name)
        res = compute_sector_strength(code, name)
        if res.get("score", 0) > 0:
            results.append(res)

    if not results:
        return pd.DataFrame()

    return (
        pd.DataFrame(results)
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )


def get_strong_sectors(top_pct: float = 0.5) -> list:
    """Return the names of the top *top_pct* sectors by strength score.

    Parameters
    ----------
    top_pct : float
        Fraction of top-ranked sectors to keep (0.0 – 1.0).

    Returns
    -------
    list[str]
        Sector names.  **May be empty** when the network is down or no data is
        available.
    """
    df = rank_sectors()
    if df.empty:
        return []
    cutoff = max(1, int(len(df) * top_pct))
    return df.head(cutoff)["name"].tolist()


def map_stock_to_sector(symbol: str) -> str:
    """Map a stock ticker to its East Money industry sector name.

    Parameters
    ----------
    symbol : str
        Stock code (e.g. ``"000001"``, ``"600519"``).

    Returns
    -------
    str
        Sector name, or ``"未知"`` if the mapping cannot be determined.
    """
    def _lookup():
        import akshare as ak
        boards = fetch_sector_data()
        if boards.empty:
            return None

        code_col = "板块代码" if "板块代码" in boards.columns else "code"
        name_col = "板块名称" if "板块名称" in boards.columns else "name"

        for _, row in boards.iterrows():
            try:
                cons = ak.stock_board_industry_cons_em(symbol=str(row[code_col]))
                if cons is not None and symbol in cons.values:
                    return str(row.get(name_col, ""))
            except Exception:
                continue
        return None

    result = _network_call(_lookup)
    return result if isinstance(result, str) else "未知"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _zero_result(sector_code: str, sector_name: str) -> dict:
    return {
        "code": sector_code,
        "name": sector_name,
        "score": 0,
        "excess_return": 0,
        "trend_score": 0,
        "vol_score": 0,
    }


def _find_column(df: pd.DataFrame, candidates: tuple) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _detect_code_name_columns(df: pd.DataFrame) -> tuple:
    code_col = _find_column(df, ("板块代码", "code", "Code", "CODE"))
    name_col = _find_column(df, ("板块名称", "name", "Name", "NAME"))
    if code_col is None and len(df.columns) > 0:
        code_col = df.columns[0]
    if name_col is None and len(df.columns) > 1:
        name_col = df.columns[1]
    elif name_col is None and len(df.columns) > 0:
        name_col = df.columns[0]
    return code_col, name_col
