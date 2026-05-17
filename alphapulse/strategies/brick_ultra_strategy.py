"""砖型图超短选股策略。

来源：砖型图超短选股.txt
选股逻辑：TDX砖型图指标昨绿柱→今红柱转换，红实体≥绿实体×2/3。
"""

import pandas as pd
from alphapulse.factors.brick_ultra import compute, compute_detail, compute_brick_indicator


def generate_signals(data: pd.DataFrame, symbol: str = "", **params) -> pd.DataFrame:
    """砖型图超短选股信号。

    Returns:
        DataFrame: symbol/date/signal/strategy/factor_snapshot
    """
    signal_series = compute(data, **params)
    detail = compute_detail(data)

    results = []
    for dt in data.index[signal_series]:
        row = detail.loc[dt] if dt in detail.index else None
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "BRICK_ULTRA",
            "factor_snapshot": {
                "brick_value": float(row["brick_value"]) if row is not None else None,
                "green_body": float(row["green_body"]) if row is not None else None,
                "red_body": float(row["red_body"]) if row is not None else None,
                "close": float(data.loc[dt, "close"]),
            },
        })

    if not results:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])
    return pd.DataFrame(results).set_index("date").sort_index()
