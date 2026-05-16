"""单针下三十策略信号生成器。

检测「单针探底」形态 —— 长下影线出现在价格低位区域：
- 下影线长度 / 实体长度 > 阈值（长下影确认）
- J值处于超卖区
- 价格位于近N日波幅的下30%区域
- 成交量配合缩量确认

买入信号：全部条件满足。
"""

import pandas as pd
import numpy as np
from alphapulse.factors.kdj_j_low import compute_kdj
from alphapulse.factors import vol_cont_shrink


def _lower_shadow_ratio(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.Series:
    """计算下影线占比。

    下影线 = min(open, close) - low
    实体 = abs(close - open)
    全天振幅 = high - low

    Returns:
        pd.Series: 下影线 / 全天振幅
    """
    body_low = pd.concat([open_, close], axis=1).min(axis=1)
    lower_shadow = body_low - low
    total_range = high - low

    ratio = lower_shadow / total_range.replace(0, np.nan)
    return ratio.fillna(0)


def _price_position_in_range(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    N: int = 60,
) -> pd.Series:
    """计算价格在近N日波动区间内的相对位置。

    Returns:
        pd.Series: 0~1之间的值，<0.3 表示价格在区间下30%
    """
    range_high = high.rolling(N).max()
    range_low = low.rolling(N).min()
    position = (close - range_low) / (range_high - range_low).replace(0, np.nan)
    return position.fillna(0.5)


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    shadow_ratio_threshold: float = 0.6,
    j_threshold: float = 13.0,
    position_threshold: float = 0.30,
    position_lookback: int = 60,
    shrink_ratio: float = 0.25,
    shrink_period: int = 5,
) -> pd.DataFrame:
    """生成单针下三十策略信号。

    检测条件：
    1. 下影线占比 > shadow_ratio_threshold（长下影线）
    2. J值 < j_threshold（超卖）
    3. 价格在近N日区间下30%（低位）
    4. 成交量缩量（量缩确认）

    Args:
        data: 日线OHLCV DataFrame
        symbol: 股票代码
        shadow_ratio_threshold: 下影线占比阈值
        j_threshold: KDJ J值超卖阈值
        position_threshold: 价格位置阈值（下30%）
        position_lookback: 位置判断回溯窗口
        shrink_ratio: 缩量比例
        shrink_period: 缩量窗口

    Returns:
        DataFrame: 含 symbol/date/signal/strategy/factor_snapshot
    """
    # 1. 长下影线
    shadow_ratio = _lower_shadow_ratio(
        data["open"], data["high"], data["low"], data["close"]
    )
    cond_shadow = shadow_ratio > shadow_ratio_threshold

    # 2. J值超卖
    _, _, j = compute_kdj(data["high"], data["low"], data["close"])
    cond_j_low = j < j_threshold

    # 3. 价格低位（下30%）
    price_pos = _price_position_in_range(
        data["close"], data["high"], data["low"], position_lookback
    )
    cond_low_position = price_pos < position_threshold

    # 4. 成交量缩量确认
    cond_shrink = vol_cont_shrink.compute(data, shrink_ratio=shrink_ratio, recent_period=shrink_period)

    # 全部条件满足 → 买入信号
    signal_mask = cond_shadow & cond_j_low & cond_low_position & cond_shrink

    # 额外：确认前一日非长下影（单针，非连续下影）
    prev_shadow = shadow_ratio.shift(1)
    signal_mask &= prev_shadow <= shadow_ratio_threshold

    results = []
    signal_dates = data.index[signal_mask]

    for dt in signal_dates:
        snapshot = {
            "shadow_ratio": round(float(shadow_ratio[dt]), 4),
            "j_value": round(float(j[dt]), 2),
            "price_position": round(float(price_pos[dt]), 4),
            "shrink": bool(cond_shrink[dt]),
            "close": float(data.loc[dt, "close"]),
            "volume": float(data.loc[dt, "volume"]),
        }
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "NEEDLE",
            "factor_snapshot": snapshot,
        })

    if not results:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])

    return pd.DataFrame(results).set_index("date").sort_index()
