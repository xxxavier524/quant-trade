"""B1公式选股策略 — 通达信B1选股公式的Python实现。

6条件全部满足时生成买入信号。输出统一信号DataFrame。
"""

import pandas as pd
from alphapulse.factors.b1_formula import compute as b1_compute, compute_detail


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    **params,
) -> pd.DataFrame:
    """生成B1公式选股信号。

    Args:
        data: 日线OHLCV DataFrame
        symbol: 股票代码
        **params: 覆盖默认参数

    Returns:
        DataFrame: symbol/date/signal/strategy/factor_snapshot
    """
    signal_series = b1_compute(data, **params)
    detail = compute_detail(data, **params)

    results = []
    signal_dates = data.index[signal_series]

    for dt in signal_dates:
        row = detail.loc[dt] if dt in detail.index else None
        snapshot = {
            "pct_change": float(row["pct_change"]) if row is not None else None,
            "amplitude": float(row["amplitude"]) if row is not None else None,
            "kdj_j": float(row["kdj_j"]) if row is not None else None,
            "macd_dif": float(row["macd_dif"]) if row is not None else None,
            "white_line": float(row["white_line"]) if row is not None else None,
            "yellow_line": float(row["yellow_line"]) if row is not None else None,
            "close": float(data.loc[dt, "close"]),
        }
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1_FORMULA",
            "factor_snapshot": snapshot,
        })

    if not results:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])

    return pd.DataFrame(results).set_index("date").sort_index()
