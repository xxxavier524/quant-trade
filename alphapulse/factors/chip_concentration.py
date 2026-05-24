"""筹码集中度因子。

识别筹码集中形态：低振幅 + 振幅加速收敛 + 换手率趋势下降。
返回 0-1 连续值，越高表示筹码越集中。
"""

import pandas as pd
import numpy as np


def compute(
    data: pd.DataFrame,
    window: int = 20,
    amplitude_max: float = 15.0,
) -> pd.Series:
    """计算筹码集中度得分。

    Agent 三条件：
    1. 20天振幅 < amplitude_max：整体波动收窄
    2. 10天振幅 < 20天振幅 × 0.6：近期振幅加速收敛
    3. 换手率趋势下降：筹码锁定，浮筹减少

    三条件等权合成 0-1 连续得分。

    Args:
        data: 含 'high','low','close','turnover' 列的 DataFrame
        window: 振幅计算窗口（默认 20）
        amplitude_max: 20天振幅上限百分比（默认 15.0）

    Returns:
        pd.Series: 0-1 连续值，越高筹码越集中
    """
    high = data["high"]
    low = data["low"]
    close = data["close"]
    turnover = data["turnover"]

    # --- 条件1: 20天区间振幅 < amplitude_max ---
    # 振幅定义: (N日最高-最低) / N日均价 × 100
    high_20 = high.rolling(window).max()
    low_20 = low.rolling(window).min()
    close_20 = close.rolling(window).mean()
    amp_20 = ((high_20 - low_20) / close_20.replace(0, np.nan)) * 100
    cond1 = (amp_20 < amplitude_max).astype(float)

    # --- 条件2: 10天振幅 < 20天振幅 × 0.6 ---
    # 振幅加速收敛：近期波动远小于远期中周期波动
    high_10 = high.rolling(10).max()
    low_10 = low.rolling(10).min()
    close_10 = close.rolling(10).mean()
    amp_10 = ((high_10 - low_10) / close_10.replace(0, np.nan)) * 100
    cond2 = (amp_10 < amp_20 * 0.6).astype(float)

    # --- 条件3: 换手率趋势下降 ---
    # 用5日均线斜率判断：近期5日均值 < 远期5日均值
    turnover_ma5 = turnover.rolling(5).mean()
    turnover_recent = turnover_ma5.rolling(5).mean()
    turnover_past = turnover_ma5.shift(window // 2).rolling(5).mean()
    cond3 = (turnover_recent < turnover_past).astype(float)

    # --- 三条件等权合成 ---
    score = (cond1 + cond2 + cond3) / 3.0

    return score.fillna(0.0).clip(0.0, 1.0)
