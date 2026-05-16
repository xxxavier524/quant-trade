#!/usr/bin/env python3
"""QMT 批量下单文件导出。

读取 daily_screener 的输出CSV，转换为 QMT 批量下单格式。

QMT 批量下单 CSV 格式:
    code, quantity, direction, price_type, price
    - code: 股票代码（如 600519.SH）
    - quantity: 委托数量（股）
    - direction: 1=买入, 2=卖出
    - price_type: 1=限价, 2=市价
    - price: 委托价格（市价填0）

用法:
    python scripts/export_qmt_csv.py --signals signals.csv --capital 1000000 --output qmt_orders.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alphapulse.config.settings import MAX_SINGLE_POSITION, MAX_HOLDINGS


def load_signals(signal_path: str) -> pd.DataFrame:
    """加载信号CSV。"""
    return pd.read_csv(signal_path, parse_dates=["date"])


def generate_qmt_orders(
    signals: pd.DataFrame,
    total_capital: float = 1_000_000,
    price_type: int = 2,
    limit_price: float = 0.0,
) -> pd.DataFrame:
    """生成 QMT 下单指令。

    仓位分配逻辑：
    - 买入信号：每个信号分配等额资金（总资金 / min(信号数, MAX_HOLDINGS)）
    - 卖出信号：全部卖出

    Args:
        signals: 信号DataFrame（daily_screener输出）
        total_capital: 总资金
        price_type: 1=限价, 2=市价
        limit_price: 限价（市价填0）

    Returns:
        DataFrame: QMT格式订单
    """
    buy_signals = signals[signals["signal"] == 1]
    sell_signals = signals[signals["signal"] == -1]

    orders = []

    # 卖出指令
    for _, row in sell_signals.iterrows():
        orders.append({
            "code": format_qmt_code(row["symbol"]),
            "quantity": 0,  # 全仓卖出由用户在QMT中设置
            "direction": 2,  # 卖出
            "price_type": price_type,
            "price": limit_price,
        })

    # 买入指令：等额分配
    n_buy = min(len(buy_signals), MAX_HOLDINGS)
    if n_buy > 0:
        per_stock_capital = total_capital * MAX_SINGLE_POSITION

        for _, row in buy_signals.iloc[:n_buy].iterrows():
            # 从factor_snapshot中尝试获取价格
            snap = row.get("factor_snapshot", {})
            if isinstance(snap, str):
                import json
                snap = json.loads(snap.replace("'", '"'))
            current_price = snap.get("close", 0)

            if current_price and current_price > 0:
                shares = int(per_stock_capital / current_price / 100) * 100  # 整手
            else:
                shares = 0

            orders.append({
                "code": format_qmt_code(row["symbol"]),
                "quantity": shares,
                "direction": 1,  # 买入
                "price_type": price_type,
                "price": current_price if price_type == 1 else 0,
            })

    return pd.DataFrame(orders, columns=["code", "quantity", "direction", "price_type", "price"])


def format_qmt_code(symbol: str) -> str:
    """将纯数字代码转为QMT格式。

    Args:
        symbol: 如 "600519" 或 "000001"

    Returns:
        如 "600519.SH" 或 "000001.SZ"
    """
    symbol = str(symbol).strip()
    if "." in symbol:
        return symbol

    if symbol.startswith(("6", "9")):
        return f"{symbol}.SH"
    elif symbol.startswith(("0", "3")):
        return f"{symbol}.SZ"
    return symbol


def main():
    parser = argparse.ArgumentParser(description="AlphaPulse-A QMT下单导出")
    parser.add_argument("--signals", required=True, help="信号CSV路径（daily_screener输出）")
    parser.add_argument("--capital", type=float, default=1_000_000, help="总资金")
    parser.add_argument("--price-type", type=int, default=2, choices=[1, 2], help="1=限价, 2=市价")
    parser.add_argument("--output", default="qmt_orders.csv", help="输出文件路径")
    args = parser.parse_args()

    print(f"[INFO] 加载信号: {args.signals}")
    signals = load_signals(args.signals)
    print(f"[INFO] 信号数: {len(signals)} （买入: {(signals['signal']==1).sum()}, 卖出: {(signals['signal']==-1).sum()}）")

    if len(signals) == 0:
        print("[WARN] 无信号，生成空文件。")

    orders = generate_qmt_orders(signals, args.capital, args.price_type)
    orders.to_csv(args.output, index=False)
    print(f"[INFO] QMT指令已保存至: {args.output}")
    print(f"[INFO] 共 {len(orders)} 条指令")

    # 预览
    if len(orders) > 0:
        print("\n预览:")
        print(orders.to_string())


if __name__ == "__main__":
    main()
