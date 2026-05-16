"""回测辅助工具。

- 滑点模型：买入 +0.1%，卖出 -0.2%
- 手续费模型：万2.5，最低5元
- 仓位管理：单票 ≤ 20%，最多持有5只
"""

import numpy as np
import pandas as pd


def apply_slippage(price: float, direction: int) -> float:
    """应用滑点。

    Args:
        price: 原始价格
        direction: 1=买入 (+0.1%), -1=卖出 (-0.2%)

    Returns:
        滑点后价格
    """
    if direction == 1:
        return price * (1 + 0.001)
    elif direction == -1:
        return price * (1 - 0.002)
    return price


def calc_commission(trade_value: float) -> float:
    """计算手续费。

    Args:
        trade_value: 成交金额

    Returns:
        手续费（万2.5，最低5元）
    """
    fee = trade_value * 0.00025
    return max(fee, 5.0)


def calc_max_shares(price: float, total_capital: float) -> int:
    """计算单票最大可买股数（20%仓位限制，整手）。

    Args:
        price: 成交价（含滑点）
        total_capital: 当前总资金

    Returns:
        最大股数（100的整数倍）
    """
    max_value = total_capital * 0.20
    shares = int(max_value / price / 100) * 100
    return max(shares, 0)


def calc_position_pct(holdings: dict, total_capital: float, data: dict) -> dict[str, float]:
    """计算各持仓占资金比例。"""
    return {
        symbol: (h["shares"] * data[symbol].loc[h["entry_date"], "close"]) / total_capital
        for symbol, h in holdings.items()
        if symbol in data
    }
