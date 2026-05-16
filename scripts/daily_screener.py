#!/usr/bin/env python3
"""每日选股器。

从数据目录加载所有股票的日线CSV，运行B1/砖型图/单针下三十
三大策略，输出当日信号的Markdown列表。

用法:
    python scripts/daily_screener.py                    # 当日数据
    python scripts/daily_screener.py --date 2025-01-15  # 指定日期
    python scripts/daily_screener.py --data-dir ./data/day --output signals.md
"""

import argparse
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.strategies.b1 import generate_signals as b1_signals
from alphapulse.strategies.brick import generate_signals as brick_signals
from alphapulse.strategies.needle import generate_signals as needle_signals
from alphapulse.config.settings import DATA_DIR, FACTOR_PARAMS


def load_stock_data(data_dir: str, target_date: str, min_days: int = 120) -> dict[str, pd.DataFrame]:
    """加载所有股票的日线数据，截取到目标日期。

    Returns:
        dict: symbol -> DataFrame（数据截至target_date）
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"[ERROR] 数据目录不存在: {data_dir}")
        return {}

    stocks = {}
    for csv_file in sorted(data_path.glob("*.csv")):
        symbol = csv_file.stem
        try:
            df = pd.read_csv(csv_file)
            # 尝试将第一列解析为日期索引
            first_col = df.columns[0]
            try:
                maybe_dates = pd.to_datetime(df[first_col])
                if len(maybe_dates.dropna()) > 0.8 * len(df):
                    df["date"] = maybe_dates
                    df = df.set_index("date")
                elif "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")
            except Exception:
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")

            if not isinstance(df.index, pd.DatetimeIndex):
                continue

            df = df[df.index <= target_date]
            if len(df) >= min_days:
                stocks[symbol] = df.sort_index()
        except Exception as e:
            print(f"[WARN] 跳过 {symbol}: {e}")

    return stocks


def run_screener(
    stocks: dict[str, pd.DataFrame],
    target_date: str,
) -> pd.DataFrame:
    """运行三大策略，汇总所有信号。

    Returns:
        DataFrame: 所有信号合并，含 symbol/date/signal/strategy/factor_snapshot
    """
    all_signals = []

    for symbol, data in stocks.items():
        # B1策略
        try:
            b1_result = b1_signals(data, symbol=symbol)
            b1_result = b1_result[b1_result.index == target_date] if target_date in b1_result.index else b1_result.iloc[:0]
            all_signals.append(b1_result)
        except Exception as e:
            print(f"[WARN] B1 {symbol}: {e}")

        # 砖型图策略
        try:
            brick_result = brick_signals(data, symbol=symbol)
            brick_result = brick_result[brick_result.index == target_date] if target_date in brick_result.index else brick_result.iloc[:0]
            all_signals.append(brick_result)
        except Exception as e:
            print(f"[WARN] BRICK {symbol}: {e}")

        # 单针策略
        try:
            needle_result = needle_signals(data, symbol=symbol)
            needle_result = needle_result[needle_result.index == target_date] if target_date in needle_result.index else needle_result.iloc[:0]
            all_signals.append(needle_result)
        except Exception as e:
            print(f"[WARN] NEEDLE {symbol}: {e}")

    if not all_signals:
        return pd.DataFrame()

    return pd.concat(all_signals, ignore_index=False).sort_index()


def format_markdown(signals: pd.DataFrame, target_date: str) -> str:
    """将信号DataFrame格式化为Markdown报告。"""
    if len(signals) == 0:
        return f"# AlphaPulse-A 每日选股报告\n\n**日期**: {target_date}\n\n> 无信号。"

    lines = [
        f"# AlphaPulse-A 每日选股报告",
        f"",
        f"**日期**: {target_date}",
        f"**信号总数**: {len(signals)}",
        f"",
        f"## 信号列表",
        f"",
    ]

    # 按策略分组
    for strategy in ["B1", "BRICK", "NEEDLE"]:
        subset = signals[signals["strategy"] == strategy]
        if len(subset) == 0:
            continue
        lines.append(f"### {strategy} ({len(subset)} 个)")
        lines.append("")
        lines.append("| 代码 | 信号 | 关键信息 |")
        lines.append("|------|------|----------|")
        for _, row in subset.iterrows():
            snap = row.get("factor_snapshot", {})
            key_info = ", ".join(f"{k}={v}" for k, v in snap.items())
            signal_str = "买入" if row["signal"] == 1 else "卖出" if row["signal"] == -1 else "-"
            lines.append(f"| {row['symbol']} | {signal_str} | {key_info} |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AlphaPulse-A 每日选股")
    parser.add_argument("--date", default=None, help="目标日期 (YYYY-MM-DD)，默认当日")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="日线CSV数据目录")
    parser.add_argument("--output", default=None, help="输出文件路径，默认打印到stdout")
    args = parser.parse_args()

    target_date = args.date or date.today().isoformat()
    print(f"[INFO] 数据目录: {args.data_dir}")
    print(f"[INFO] 目标日期: {target_date}")

    stocks = load_stock_data(args.data_dir, target_date)
    print(f"[INFO] 已加载 {len(stocks)} 只股票")

    if not stocks:
        print("[WARN] 无可用数据。请确保 data/day/ 下有CSV文件。")
        return

    signals = run_screener(stocks, target_date)
    report = format_markdown(signals, target_date)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[INFO] 报告已保存至: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
