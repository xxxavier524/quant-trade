"""动态止损因子。

止损价 = min(入场日最低价-3价位, 前N型结构低点-3价位)
最小变动价位 = 0.01（A股）

在AlphaPulse-A中用于持仓风险管理：当价格跌破止损价时触发卖出。
"""

import pandas as pd
import numpy as np

TICK_SIZE = 0.01
TICK_OFFSET = 3


def compute(
    data: pd.DataFrame,
    entry_date=None,
    entry_price: float = None,
    n_pattern_low: float = None,
) -> float:
    """计算动态止损价。

    止损价取两个候选值的较小者：
      候选1 = 入场日最低价 - 3个最小变动价位
      候选2 = 前N型结构低点 - 3个最小变动价位（如果提供）

    Args:
        data: OHLCV DataFrame，index 为日期（DatetimeIndex）
        entry_date: 入场日期（str / pd.Timestamp / datetime-like），
                    默认取 data 最后一个交易日
        entry_price: 入场价格，默认取 data 最后一日的收盘价
        n_pattern_low: 前N型结构低点价格，若为 None 则仅使用入场日最低价

    Returns:
        float: 止损价格
    """
    if entry_date is None:
        entry_date = data.index[-1]
    entry_date = pd.Timestamp(entry_date)

    # --- 候选1: 入场日最低价 ---
    if entry_date in data.index:
        entry_low = float(data.loc[entry_date, "low"])
    else:
        # 日期不在索引中时，取最近的前一个交易日
        pos = data.index.get_indexer([entry_date], method="ffill")[0]
        if pos < 0:
            raise ValueError(f"入场日期 {entry_date} 早于数据起始日期 {data.index[0]}")
        entry_low = float(data.iloc[pos]["low"])

    stop1 = entry_low - TICK_OFFSET * TICK_SIZE

    # --- 候选2: N型结构低点 ---
    if n_pattern_low is not None:
        stop2 = float(n_pattern_low) - TICK_OFFSET * TICK_SIZE
        return round(min(stop1, stop2), 2)

    return round(stop1, 2)
