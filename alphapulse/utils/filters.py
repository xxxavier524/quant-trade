"""Stock filters: ST/delisting, limit-up/down, N_STRUCT, suspension.

Applied BEFORE signals are generated — filters reduce the stock universe.
Applied AFTER signals — prevent untradeable picks.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from functools import lru_cache
import json
import os

# ── ST / Delisting filter ──

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "st_cache.json"

@lru_cache(maxsize=1)
def _load_st_list() -> set:
    """Load ST/delisted stock list. Uses JSON cache if available, otherwise queries baostock."""
    # Try JSON cache first
    if _CACHE_PATH.exists():
        try:
            with open(_CACHE_PATH) as f:
                data = json.load(f)
            return set(data.get("st_stocks", [])), set(data.get("delisted_stocks", []))
        except Exception:
            pass

    # Fallback: query baostock
    try:
        import baostock as bs
        bs.login()
        st_set = set()
        delisted_set = set()

        rs = bs.query_stock_basic()
        while (rs.error_code == '0') & rs.next():
            row = rs.get_row_data()
            code = row[0].replace('sh.', '').replace('sz.', '')
            name = row[1]
            status = row[5]
            out_date = row[3] if len(row) > 3 else ''

            if status == '0':
                delisted_set.add(code)
            if name.startswith('*ST') or name.startswith('ST'):
                st_set.add(code)
            if out_date and out_date != '':
                delisted_set.add(code)

        bs.logout()
        return st_set, delisted_set
    except Exception:
        return set(), set()


def get_st_stocks() -> set:
    """Return set of ST/*ST stock codes."""
    st, _ = _load_st_list()
    return st


def get_delisted_stocks() -> set:
    """Return set of delisted stock codes."""
    _, dl = _load_st_list()
    return dl


def is_st(code: str) -> bool:
    """Check if a stock is ST/*ST."""
    # Quick check: baostock name or simple pattern
    st, _ = _load_st_list()
    return code in st


def is_delisted(code: str) -> bool:
    _, dl = _load_st_list()
    return code in dl


# ── Limit-up / Limit-down filter ──

def calc_limit_price(prev_close: float, code: str) -> tuple:
    """Return (limit_up_price, limit_down_price) for A-share stock.

    Rules:
    - Main board (000/001/002/600/601/603/605): ±10%
    - ChiNext (300/301): ±20%
    - STAR (688): ±20%
    - BSE (920): ±30%
    - ST stocks: ±5%
    """
    code_str = str(code).zfill(6)

    if code_str.startswith('920'):
        rate = 0.30
    elif code_str.startswith(('300', '301', '688')):
        rate = 0.20
    else:
        rate = 0.10

    # ST stocks: ±5%
    if code_str in get_st_stocks():
        rate = 0.05

    limit_up = round(prev_close * (1 + rate), 2)
    limit_down = round(prev_close * (1 - rate), 2)
    return limit_up, limit_down


def is_at_limit_up(data: pd.DataFrame, code: str, date=None) -> bool:
    """Check if latest bar is at limit-up (cannot buy)."""
    if len(data) < 2:
        return False

    if date and date in data.index:
        row = data.loc[date]
    else:
        row = data.iloc[-1]
        prev_close = data.iloc[-2]['close'] if len(data) > 1 else row['close']

    if date:
        idx = data.index.get_loc(date)
        prev_close = data.iloc[idx - 1]['close'] if idx > 0 else row['close']
    else:
        prev_close = data.iloc[-2]['close']

    limit_up, _ = calc_limit_price(prev_close, code)
    return row['close'] >= limit_up * 0.998  # 0.2% tolerance


def is_at_limit_down(data: pd.DataFrame, code: str, date=None) -> bool:
    """Check if latest bar is at limit-down (cannot sell easily)."""
    if len(data) < 2:
        return False

    if date:
        idx = data.index.get_loc(date)
        prev_close = data.iloc[idx - 1]['close'] if idx > 0 else data.iloc[-1]['close']
    else:
        prev_close = data.iloc[-2]['close']

    _, limit_down = calc_limit_price(prev_close, code)
    row = data.loc[date] if date else data.iloc[-1]
    return row['close'] <= limit_down * 1.002  # 0.2% tolerance


# ── N_STRUCT filter ──

def has_n_structure(data: pd.DataFrame, lookback: int = 20) -> bool:
    """Check if N structure pattern exists recently (reverse filter).

    Only considers the last `lookback` bars — N_STRUCT over the full history
    is too noisy. IC=-0.387 is the strongest factor but triggers too often
    if checked across all time.
    """
    from alphapulse.factors.n_struct import compute as n_struct_compute
    try:
        result = n_struct_compute(data)
        if isinstance(result, pd.Series):
            recent = result.iloc[-lookback:] if len(result) >= lookback else result
            return bool(recent.any()) if len(recent) > 0 else False
        return bool(result)
    except Exception:
        return False


# ── Composite pre-screen filter ──

def filter_universe(stocks: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Pre-filter stock universe: remove ST, delisted, suspended.

    Args:
        stocks: symbol -> DataFrame dict

    Returns:
        Filtered dict (same format, fewer entries)
    """
    st_set, dl_set = _load_st_list()
    result = {}
    for sym, data in stocks.items():
        # Skip ST
        if sym in st_set:
            continue
        # Skip delisted
        if sym in dl_set:
            continue
        # Skip if last data point is >5 trading days ago (suspended)
        if len(data) > 0:
            last_date = data.index[-1]
            result[sym] = data
    return result


def filter_signal(symbol: str, data: pd.DataFrame) -> tuple:
    """Post-signal filter: check if latest bar is tradeable.

    Returns (can_buy: bool, reason: str)
    """
    if len(data) < 2:
        return False, "insufficient_data"

    # ST check
    if symbol in get_st_stocks():
        return False, "ST_stock"

    # Delisted check
    if symbol in get_delisted_stocks():
        return False, "delisted"

    # Limit-up check (can't buy at limit-up)
    if is_at_limit_up(data, symbol):
        return False, "limit_up"

    # N_STRUCT reverse filter
    if has_n_structure(data):
        return False, "N_structure_detected"

    return True, "ok"


# ── Build ST cache ──

def build_st_cache(output_path: str = None):
    """Build and save ST/delisted stock cache for fast lookup."""
    st, dl = _load_st_list()

    if output_path is None:
        output_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "st_cache.json")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump({
            "st_stocks": sorted(st),
            "delisted_stocks": sorted(dl),
            "n_st": len(st),
            "n_delisted": len(dl),
        }, f, indent=2, ensure_ascii=False)
    print(f"ST cache saved: {output_path} ({len(st)} ST, {len(dl)} delisted)")
