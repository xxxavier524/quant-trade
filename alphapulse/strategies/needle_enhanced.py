"""单针下30增强选股策略 — 融合知行洗盘短线。

单针下30类型（原needle + 知行洗盘短线）：
  原单针：  长下影 + J超卖 + 低位30% + 缩量 + 单针确认
  知行洗盘：四线归零/CROSS(短期,长期)/CROSS(短期,中期)/中长期>65

输出统一信号DataFrame。
"""

import pandas as pd
from alphapulse.strategies.needle import generate_signals as needle_signals
from alphapulse.factors.zhixing_washout import compute as washout_compute


def generate_signals(data: pd.DataFrame, symbol: str = "", mode: str = "all", **params) -> pd.DataFrame:
    """单针下30增强选股。

    Args:
        data: 日线OHLCV
        symbol: 股票代码
        mode: "needle" | "washout" | "all"（两者AND）
    """
    if mode == "needle":
        return needle_signals(data, symbol=symbol)
    if mode == "washout":
        sig = washout_compute(data)
        results = []
        for dt in data.index[sig]:
            results.append({
                "symbol": symbol, "date": dt, "signal": 1,
                "strategy": "NEEDLE_WASHOUT",
                "factor_snapshot": {"close": float(data.loc[dt, "close"])},
            })
        if not results:
            return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])
        return pd.DataFrame(results).set_index("date").sort_index()

    # mode == "all": needle AND washout
    needle_df = needle_signals(data, symbol=symbol)
    washout_sig = washout_compute(data)

    if len(needle_df) == 0:
        return needle_df

    # 过滤：只保留同时满足洗盘条件的needle信号
    needle_dates = set(needle_df.index)
    washout_dates = set(data.index[washout_sig])
    common = needle_dates & washout_dates

    result = needle_df[needle_df.index.isin(common)].copy()
    result["strategy"] = "NEEDLE_ENHANCED"
    return result
