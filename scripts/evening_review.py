#!/usr/bin/env python3
"""晚间复盘脚本。

比对本日信号与实际涨跌，生成胜率统计：
- 信号命中率（信号方向与实际涨跌一致的比例）
- 各策略独立统计
- 当日信号列表与结果对照

用法:
    python scripts/evening_review.py --signals signals_2025-01-15.csv --data-dir ./data/day
"""

import argparse
import sys
from pathlib import Path
from datetime import date

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alphapulse.config.settings import DATA_DIR


def load_signal_file(signal_path: str) -> pd.DataFrame:
    """加载信号CSV文件，自动处理date列或索引。"""
    df = pd.read_csv(signal_path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    else:
        # 尝试第一列为日期
        first_col = df.columns[0]
        try:
            df["date"] = pd.to_datetime(df[first_col])
            df = df.drop(columns=[first_col])
        except Exception:
            df["date"] = pd.NaT
    return df


def compute_actual_returns(
    signals: pd.DataFrame,
    data_dir: str,
    forward_days: int = 1,
) -> pd.DataFrame:
    """计算信号发出后 forward_days 天的实际收益。

    Args:
        signals: 信号DataFrame，需含 symbol/date/signal
        data_dir: 日线数据目录
        forward_days: 前看天数

    Returns:
        DataFrame: 原信号表 + actual_return 列
    """
    results = []
    for _, row in signals.iterrows():
        symbol = row["symbol"]
        signal_date = pd.Timestamp(row["date"])
        signal_val = row["signal"]

        csv_path = Path(data_dir) / f"{symbol}.csv"
        if not csv_path.exists():
            results.append({**row.to_dict(), "actual_return": np.nan, "hit": np.nan})
            continue

        stock_data = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
        future_data = stock_data[stock_data.index > signal_date]

        if len(future_data) < forward_days:
            results.append({**row.to_dict(), "actual_return": np.nan, "hit": np.nan})
            continue

        future_close = future_data.iloc[forward_days - 1]["close"]
        signal_close = stock_data.loc[signal_date, "close"] if signal_date in stock_data.index else np.nan

        if pd.isna(signal_close) or signal_close == 0:
            results.append({**row.to_dict(), "actual_return": np.nan, "hit": np.nan})
            continue

        actual_return = (future_close - signal_close) / signal_close
        hit = (actual_return > 0 and signal_val == 1) or (actual_return < 0 and signal_val == -1)

        results.append({
            **row.to_dict(),
            "actual_return": round(actual_return, 4),
            "hit": hit,
        })

    return pd.DataFrame(results)


def generate_review_report(results: pd.DataFrame, target_date: str) -> str:
    """生成复盘Markdown报告。"""
    valid = results.dropna(subset=["hit"])

    lines = [
        f"# AlphaPulse-A 晚间复盘",
        f"",
        f"**信号日期**: {target_date}",
        f"**总信号数**: {len(results)}",
        f"**有效信号**: {len(valid)}（有后续数据的）",
        f"",
    ]

    if len(valid) == 0:
        lines.append("> 无有效信号可供统计。")
        return "\n".join(lines)

    # 整体统计
    overall_win_rate = valid["hit"].mean()
    buy_signals = valid[valid["signal"] == 1]
    sell_signals = valid[valid["signal"] == -1]

    lines.extend([
        f"## 整体统计",
        f"",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 总命中率 | {overall_win_rate:.1%} |",
        f"| 买入信号数 | {len(buy_signals)} |",
        f"| 买入胜率 | {buy_signals['hit'].mean():.1%}" if len(buy_signals) > 0 else "| 买入胜率 | N/A |",
        f"| 卖出信号数 | {len(sell_signals)} |",
        f"| 卖出胜率 | {sell_signals['hit'].mean():.1%}" if len(sell_signals) > 0 else "| 卖出胜率 | N/A |",
        f"| 平均收益 | {valid['actual_return'].mean():.4%} |",
        f"",
    ])

    # 各策略统计
    lines.append("## 各策略表现")
    lines.append("")
    lines.append("| 策略 | 信号数 | 命中率 | 平均收益 |")
    lines.append("|------|--------|--------|----------|")
    for strategy in valid["strategy"].unique():
        subset = valid[valid["strategy"] == strategy]
        lines.append(
            f"| {strategy} | {len(subset)} | "
            f"{subset['hit'].mean():.1%} | "
            f"{subset['actual_return'].mean():.4%} |"
        )
    lines.append("")

    # 信号明细
    lines.append("## 信号明细")
    lines.append("")
    lines.append("| 代码 | 策略 | 信号 | 实际收益 | 命中 |")
    lines.append("|------|------|------|----------|------|")
    for _, row in results.iterrows():
        hit_str = "✅" if row.get("hit") is True else "❌" if row.get("hit") is False else "—"
        ret_str = f"{row['actual_return']:.2%}" if not pd.isna(row.get("actual_return")) else "—"
        signal_str = "买" if row["signal"] == 1 else "卖"
        lines.append(f"| {row['symbol']} | {row['strategy']} | {signal_str} | {ret_str} | {hit_str} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AlphaPulse-A 晚间复盘")
    parser.add_argument("--signals", required=True, help="信号CSV文件路径")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="日线CSV数据目录")
    parser.add_argument("--date", default=date.today().isoformat(), help="信号日期")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--forward", type=int, default=1, help="前看天数")
    args = parser.parse_args()

    print(f"[INFO] 加载信号文件: {args.signals}")
    signals = load_signal_file(args.signals)
    print(f"[INFO] 信号数量: {len(signals)}")

    if len(signals) == 0:
        print("[WARN] 信号文件为空。")
        return

    results = compute_actual_returns(signals, args.data_dir, args.forward)
    report = generate_review_report(results, args.date)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[INFO] 报告已保存至: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
