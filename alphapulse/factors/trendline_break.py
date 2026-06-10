"""趋势线跌破因子。

基于知行趋势线的卖出信号：
- 白线: EMA(EMA(C,10),10) —— 知行短期趋势线
- 黄线: (MA20+MA60+MA120+MA250)/4 —— 知行多空线

信号：
- break_white: 收盘跌破白线（前日还在白线上方）
- break_yellow: 收盘跌破黄线（前日还在黄线上方）
- fake_break: 跌破白线后次日重新站上 → 假跌破

全部使用 shift(1) 防止未来函数。

Returns:
    pd.DataFrame: 含 break_white / break_yellow / fake_break 列
"""

import pandas as pd
import numpy as np

from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line


def compute(data: pd.DataFrame) -> pd.DataFrame:
    """检测趋势线跌破信号。

    Args:
        data: 含 close 的 DataFrame，index=date

    Returns:
        pd.DataFrame:
            - break_white (bool): 收盘跌破白线
            - break_yellow (bool): 收盘跌破黄线
            - fake_break (bool): 跌破白线后次日重新站上（假跌破）
    """
    close = data["close"].astype(float)

    n = len(data)
    if n < 10:
        return pd.DataFrame({
            "break_white": pd.Series(False, index=data.index),
            "break_yellow": pd.Series(False, index=data.index),
            "fake_break": pd.Series(False, index=data.index),
        })

    # ---- 计算两条趋势线 ----
    white_line = compute_short_trend(close)  # EMA(EMA(C,10),10)
    yellow_line = compute_bull_bear_line(close)  # (MA14+MA28+MA57+MA114)/4

    # ---- 跌破信号（shift(1)防未来函数） ----
    # 跌破白线: 昨日收盘 < 昨日白线 且 前日收盘 >= 前日白线
    break_white = (
        (close.shift(1) < white_line.shift(1))
        & (close.shift(2) >= white_line.shift(2))
    )

    # 跌破黄线: 昨日收盘 < 昨日黄线 且 前日收盘 >= 前日黄线
    break_yellow = (
        (close.shift(1) < yellow_line.shift(1))
        & (close.shift(2) >= yellow_line.shift(2))
    )

    # ---- 假跌破: 跌破后次日重新站上白线 ----
    # 前日跌破白线 且 昨日收盘回到白线上方
    fake_break = break_white.shift(1) & (close.shift(1) >= white_line.shift(1))

    return pd.DataFrame({
        "break_white": break_white.fillna(False),
        "break_yellow": break_yellow.fillna(False),
        "fake_break": fake_break.fillna(False),
    }, index=data.index)
