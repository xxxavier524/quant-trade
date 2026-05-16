#!/usr/bin/env python3
"""风控监控脚本。

接收持仓CSV，检查每个持仓是否触发减仓条件：
- 单票仓位超过20%
- 持仓数超过5只
- 个股从最高点回撤超过15%
- 组合整体回撤超过10%
- 单日亏损超过5%

用法:
    python scripts/risk_monitor.py --positions positions.csv --data-dir ./data/day
"""

import argparse
import sys
from pathlib import Path
from datetime import date

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alphapulse.config.settings import (
    MAX_SINGLE_POSITION,
    MAX_HOLDINGS,
    DATA_DIR,
)


def load_positions(positions_path: str) -> pd.DataFrame:
    """加载持仓CSV。

    期望列: symbol, shares, cost_price, current_price (可选), entry_date
    """
    df = pd.read_csv(positions_path)
    required = {"symbol", "shares", "cost_price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"持仓CSV缺少必要列: {missing}")
    return df


def check_positions(
    positions: pd.DataFrame,
    data_dir: str,
    total_capital: float = 1_000_000,
) -> list[dict]:
    """逐项检查风控条件。

    Returns:
        list[dict]: 每条警报含 symbol/level/rule/message
    """
    alerts = []

    # 1. 持仓数检查
    if len(positions) > MAX_HOLDINGS:
        alerts.append({
            "symbol": "*",
            "level": "WARN",
            "rule": f"持仓数 > {MAX_HOLDINGS}",
            "message": f"当前持仓 {len(positions)} 只，超过上限 {MAX_HOLDINGS}。建议减仓至 {MAX_HOLDINGS} 只。",
        })

    for _, row in positions.iterrows():
        symbol = row["symbol"]
        shares = row["shares"]
        cost_price = row["cost_price"]

        # 获取最新价格
        current_price = row.get("current_price", np.nan)
        if pd.isna(current_price) or current_price is None:
            csv_path = Path(data_dir) / f"{symbol}.csv"
            if csv_path.exists():
                stock_data = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
                if len(stock_data) > 0:
                    current_price = float(stock_data.iloc[-1]["close"])

        if pd.isna(current_price) or current_price == 0:
            alerts.append({
                "symbol": symbol,
                "level": "WARN",
                "rule": "无法获取最新价格",
                "message": f"{symbol}: 无法从数据目录获取最新价格。",
            })
            continue

        current_value = shares * current_price

        # 2. 单票仓位检查
        position_pct = current_value / total_capital
        if position_pct > MAX_SINGLE_POSITION:
            alerts.append({
                "symbol": symbol,
                "level": "CRITICAL",
                "rule": f"单票仓位 > {MAX_SINGLE_POSITION:.0%}",
                "message": f"{symbol}: 当前仓位 {position_pct:.1%}（{current_value:.0f}元），超过上限 {MAX_SINGLE_POSITION:.0%}。建议减至 {shares * MAX_SINGLE_POSITION / position_pct:.0f} 股。",
            })

        # 3. 个股回撤检查（需历史数据）
        csv_path = Path(data_dir) / f"{symbol}.csv"
        if csv_path.exists():
            stock_data = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
            if len(stock_data) > 0:
                historical_high = stock_data["high"].max()
                drawdown = (historical_high - current_price) / historical_high
                if drawdown > 0.15:
                    alerts.append({
                        "symbol": symbol,
                        "level": "WARN",
                        "rule": "个股回撤 > 15%",
                        "message": f"{symbol}: 最高价 {historical_high:.2f}，当前 {current_price:.2f}，回撤 {drawdown:.1%}。",
                    })

        # 4. 个股盈亏检查
        pnl_pct = (current_price - cost_price) / cost_price
        if pnl_pct < -0.05:
            alerts.append({
                "symbol": symbol,
                "level": "INFO",
                "rule": "单日亏损 > 5%",
                "message": f"{symbol}: 成本 {cost_price:.2f}，当前 {current_price:.2f}，浮动盈亏 {pnl_pct:.1%}。",
            })

    # 5. 组合回撤（简化：所有持仓加权盈亏）
    total_cost = (positions["shares"] * positions["cost_price"]).sum()
    total_value = 0
    for _, row in positions.iterrows():
        symbol = row["symbol"]
        csv_path = Path(data_dir) / f"{symbol}.csv"
        if csv_path.exists():
            stock_data = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
            if len(stock_data) > 0:
                total_value += row["shares"] * float(stock_data.iloc[-1]["close"])
    if total_cost > 0:
        portfolio_dd = (total_cost - total_value) / total_cost
        if portfolio_dd > 0.10:
            alerts.append({
                "symbol": "*",
                "level": "CRITICAL",
                "rule": "组合回撤 > 10%",
                "message": f"组合总成本 {total_cost:.0f}，当前市值 {total_value:.0f}，整体回撤 {portfolio_dd:.1%}。建议减仓或止损。",
            })

    return sorted(alerts, key=lambda a: {"CRITICAL": 0, "WARN": 1, "INFO": 2}.get(a["level"], 3))


def format_alerts_markdown(alerts: list[dict], target_date: str) -> str:
    """格式化风控报告。"""
    if not alerts:
        return f"# AlphaPulse-A 风控报告\n\n**日期**: {target_date}\n\n> ✅ 无风险警报。所有仓位在安全范围内。"

    critical = [a for a in alerts if a["level"] == "CRITICAL"]
    warn = [a for a in alerts if a["level"] == "WARN"]
    info = [a for a in alerts if a["level"] == "INFO"]

    lines = [
        f"# AlphaPulse-A 风控报告",
        f"",
        f"**日期**: {target_date}",
        f"**总警报**: {len(alerts)}（🔴 CRITICAL: {len(critical)} / 🟡 WARN: {len(warn)} / 🔵 INFO: {len(info)}）",
        f"",
    ]

    for level, emoji, label in [
        ("CRITICAL", "🔴", "严重警报"),
        ("WARN", "🟡", "警告"),
        ("INFO", "🔵", "提示"),
    ]:
        subset = [a for a in alerts if a["level"] == level]
        if not subset:
            continue
        lines.append(f"## {emoji} {label} ({len(subset)})")
        lines.append("")
        lines.append("| 代码 | 规则 | 详情 |")
        lines.append("|------|------|------|")
        for a in subset:
            lines.append(f"| {a['symbol']} | {a['rule']} | {a['message']} |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AlphaPulse-A 风控监控")
    parser.add_argument("--positions", required=True, help="持仓CSV文件路径")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="日线CSV数据目录")
    parser.add_argument("--capital", type=float, default=1_000_000, help="总资金")
    parser.add_argument("--date", default=date.today().isoformat(), help="检查日期")
    parser.add_argument("--output", default=None, help="输出文件路径")
    args = parser.parse_args()

    print(f"[INFO] 加载持仓文件: {args.positions}")
    positions = load_positions(args.positions)
    print(f"[INFO] 持仓数量: {len(positions)}")

    alerts = check_positions(positions, args.data_dir, args.capital)
    report = format_alerts_markdown(alerts, args.date)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[INFO] 报告已保存至: {args.output}")
    else:
        print(report)

    # 有 CRITICAL 时 exit 1
    if any(a["level"] == "CRITICAL" for a in alerts):
        sys.exit(1)


if __name__ == "__main__":
    main()
