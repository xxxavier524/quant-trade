"""B1策略信号生成器。

多因子条件组合策略：
1. 成交量缩量至异动量的1/4以下
2. KDJ J值处于低位（超卖）
3. MACD处于多头或零轴上死叉
4. 近5日出现放量异动（量能先行）
5. 周线MA多头排列（中长期趋势确认）

全部条件满足时生成买入信号。
"""

import pandas as pd
from alphapulse.factors import (
    shrink_to_abnormal,
    kdj_j_low,
    macd_bull_dead,
    abnormal_vol,
    weekly_ma_bull,
)


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    shrink_ratio: float = 0.25,
    j_threshold: float = 13.0,
    abnormal_k: float = 2.0,
    abnormal_m: int = 60,
    abnormal_x: int = 3,
    abnormal_y: int = 5,
) -> pd.DataFrame:
    """生成B1策略当日信号。

    Args:
        data: 日线OHLCV DataFrame，需包含 open/high/low/close/volume
        symbol: 股票代码
        shrink_ratio: 缩量比例阈值
        j_threshold: J值低位阈值
        abnormal_k: 放量异动倍量
        abnormal_m: 均量窗口
        abnormal_x: 最小异动次数
        abnormal_y: 异动检查窗口

    Returns:
        DataFrame，包含字段:
        - symbol: 股票代码
        - date: 信号日期
        - signal: 1=买入, 0=无信号
        - strategy: "B1"
        - factor_snapshot: 各因子当前值（dict）
    """
    # 计算各因子
    cond_shrink = shrink_to_abnormal.compute(data, ratio=shrink_ratio, M=abnormal_m, K=abnormal_k)
    cond_j_low = kdj_j_low.compute(data, j_threshold=j_threshold)
    cond_macd = macd_bull_dead.compute(data)
    cond_abnormal = abnormal_vol.compute(data, M=abnormal_m, K=abnormal_k, X=abnormal_x, Y=abnormal_y)
    cond_weekly = weekly_ma_bull.compute(data)

    # B1信号：全部条件满足
    signal_mask = cond_shrink & cond_j_low & cond_macd & cond_abnormal & cond_weekly

    # 构建输出DataFrame
    results = []
    signal_dates = data.index[signal_mask]

    for dt in signal_dates:
        snapshot = {
            "shrink": bool(cond_shrink[dt]),
            "j_low": bool(cond_j_low[dt]),
            "macd_bull_dead": bool(cond_macd[dt]),
            "abnormal_vol": bool(cond_abnormal[dt]),
            "weekly_ma_bull": bool(cond_weekly[dt]),
            "close": float(data.loc[dt, "close"]),
            "volume": float(data.loc[dt, "volume"]),
        }
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1",
            "factor_snapshot": snapshot,
        })

    if not results:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])

    return pd.DataFrame(results).set_index("date").sort_index()
