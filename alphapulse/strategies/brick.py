"""砖型图（Renko）策略信号生成器。

使用固定2%振幅的Renko砖型图：
- 上涨砖：价格突破前砖收盘价 + 2%
- 下跌砖：价格跌破前砖收盘价 - 2%
- 买入信号：连续2个上涨砖（趋势确认）
- 卖出信号：连续2个下跌砖（趋势反转）
"""

import pandas as pd
import numpy as np


def _build_renko_bricks(
    close: pd.Series,
    brick_pct: float = 0.02,
) -> pd.DataFrame:
    """从收盘价序列构建Renko砖型图。

    Args:
        close: 收盘价序列
        brick_pct: 砖块振幅比例（2% = 0.02）

    Returns:
        DataFrame: 每块砖的 index（原始日期的最后一个）、open、close、direction
    """
    brick_size = close.iloc[0] * brick_pct
    bricks = []
    current_brick_open = close.iloc[0]
    current_brick_close = current_brick_open
    last_brick_idx = 0

    for i in range(1, len(close)):
        price = close.iloc[i]
        price_change = price - current_brick_close

        # 需要多少个砖块来吸收价格变动
        if abs(price_change) >= brick_size:
            num_bricks = int(abs(price_change) / brick_size)
            direction = 1 if price_change > 0 else -1

            for _ in range(num_bricks):
                new_brick_open = current_brick_close
                new_brick_close = new_brick_open + direction * brick_size
                bricks.append({
                    "date": close.index[i],
                    "brick_open": new_brick_open,
                    "brick_close": new_brick_close,
                    "direction": direction,
                })
                current_brick_close = new_brick_close

            last_brick_idx = i

    if not bricks:
        return pd.DataFrame(columns=["date", "brick_open", "brick_close", "direction"])

    return pd.DataFrame(bricks)


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    brick_pct: float = 0.02,
    confirm_bricks: int = 2,
) -> pd.DataFrame:
    """生成Renko砖型图策略信号。

    Args:
        data: 日线OHLCV DataFrame
        symbol: 股票代码
        brick_pct: 砖块振幅百分比（默认2%）
        confirm_bricks: 连续同向砖块数确认信号

    Returns:
        DataFrame: 含 symbol/date/signal/strategy/factor_snapshot
    """
    bricks = _build_renko_bricks(data["close"], brick_pct)

    if len(bricks) < confirm_bricks:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])

    # 检测连续同向砖块
    brick_dir = bricks["direction"].values
    signals = []

    for i in range(confirm_bricks - 1, len(brick_dir)):
        # 检查最近 confirm_bricks 个砖块是否同向
        recent = brick_dir[i - confirm_bricks + 1 : i + 1]
        if np.all(recent == 1):
            # 连续上涨砖 → 买入信号
            signals.append({
                "symbol": symbol,
                "date": bricks.iloc[i]["date"],
                "signal": 1,
                "strategy": "BRICK",
                "factor_snapshot": {
                    "brick_open": float(bricks.iloc[i]["brick_open"]),
                    "brick_close": float(bricks.iloc[i]["brick_close"]),
                    "brick_pct": brick_pct,
                    "consecutive_up": confirm_bricks,
                    "current_price": float(data["close"].iloc[-1]),
                },
            })
        elif np.all(recent == -1):
            # 连续下跌砖 → 卖出/空仓信号
            signals.append({
                "symbol": symbol,
                "date": bricks.iloc[i]["date"],
                "signal": -1,
                "strategy": "BRICK",
                "factor_snapshot": {
                    "brick_open": float(bricks.iloc[i]["brick_open"]),
                    "brick_close": float(bricks.iloc[i]["brick_close"]),
                    "brick_pct": brick_pct,
                    "consecutive_down": confirm_bricks,
                    "current_price": float(data["close"].iloc[-1]),
                },
            })

    if not signals:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])

    return pd.DataFrame(signals).set_index("date").sort_index()
