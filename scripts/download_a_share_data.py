#!/usr/bin/env python3
"""A股日线数据批量下载脚本。

使用 akshare 下载全A股日线数据（2020-01-01 ~ 今），
存为 data/day/{symbol}.csv。

特性：
- 限流：每次请求间隔 0.5s，批量每 50 只休息 5s
- 断点续传：跳过已下载的股票（检查 CSV 是否存在且包含目标日期范围）
- 进度条：显示已下载/总数/耗时

用法:
    python scripts/download_a_share_data.py                    # 全部A股
    python scripts/download_a_share_data.py --start 100        # 从第100只开始
    python scripts/download_a_share_data.py --symbols 600519,000001  # 指定代码
    python scripts/download_a_share_data.py --sample 20        # 随机抽样20只（测试用）
"""

import argparse
import sys
import time
from pathlib import Path
from datetime import datetime, date

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alphapulse.config.settings import DATA_DIR

# 下载参数
DEFAULT_START_DATE = "20200101"
DEFAULT_END_DATE = date.today().strftime("%Y%m%d")
REQUEST_INTERVAL = 0.5       # 单次请求间隔（秒）
BATCH_SIZE = 50              # 每批次数量
BATCH_REST = 5.0             # 批次间休息（秒）
MIN_REQUIRED_DAYS = 60       # 最少交易日数（不够的跳过）


def get_stock_list() -> pd.DataFrame:
    """获取全A股列表（含代码、名称、上市日期）。"""
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    df = df.rename(columns={
        "代码": "symbol",
        "名称": "name",
    })
    df["symbol"] = df["symbol"].astype(str).str.strip()
    return df[["symbol", "name"]]


def download_single_stock(
    symbol: str,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    output_dir: str = None,
    retries: int = 3,
) -> tuple[str, int, str]:
    """下载单只股票的日线数据。

    Args:
        symbol: 股票代码（如 "600519"）
        start_date: 起始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
        output_dir: 输出目录
        retries: 重试次数

    Returns:
        (symbol, rows, status): status = "ok" / "skip_empty" / "error"
    """
    import akshare as ak

    output_path = Path(output_dir or DATA_DIR) / f"{symbol}.csv"

    for attempt in range(retries):
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",  # 前复权
            )

            if df is None or len(df) == 0:
                return (symbol, 0, "skip_empty")

            # 标准化列名
            col_map = {
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "振幅": "amplitude",
                "涨跌幅": "pct_change",
                "涨跌额": "change",
                "换手率": "turnover",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

            # 确保日期格式
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])

            if len(df) < MIN_REQUIRED_DAYS:
                return (symbol, len(df), "skip_empty")

            Path(output_dir).mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False)
            return (symbol, len(df), "ok")

        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                return (symbol, 0, f"error: {str(e)[:80]}")

    return (symbol, 0, "error")


def is_already_downloaded(symbol: str, output_dir: str, min_rows: int = MIN_REQUIRED_DAYS) -> bool:
    """检查是否已下载且数据完整。"""
    output_path = Path(output_dir) / f"{symbol}.csv"
    if not output_path.exists():
        return False
    try:
        df = pd.read_csv(output_path)
        return len(df) >= min_rows
    except Exception:
        return False


def download_batch(
    symbols: list[str],
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    output_dir: str = None,
    skip_existing: bool = True,
):
    """批量下载股票数据。

    Args:
        symbols: 股票代码列表
        start_date: 起始日期
        end_date: 结束日期
        output_dir: 输出目录
        skip_existing: 是否跳过已存在的
    """
    out_dir = output_dir or str(DATA_DIR)
    total = len(symbols)
    results = {"ok": 0, "skip_empty": 0, "skip_existing": 0, "error": 0}
    start_time = time.time()

    print(f"[INFO] 目标: {total} 只股票")
    print(f"[INFO] 日期范围: {start_date} ~ {end_date}")
    print(f"[INFO] 输出目录: {out_dir}")
    print(f"[INFO] 断点续传: {'开' if skip_existing else '关'}")
    print()

    for i, symbol in enumerate(symbols):
        # 断点续传
        if skip_existing and is_already_downloaded(symbol, out_dir):
            results["skip_existing"] += 1
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                done = i + 1
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] {results} | 速率 {rate:.1f}/s | ETA {eta:.0f}s")
            continue

        # 下载
        sym, rows, status = download_single_stock(symbol, start_date, end_date, out_dir)
        results[status.split(":")[0] if ":" in status else status] = results.get(
            status.split(":")[0] if ":" in status else status, 0
        ) + 1

        # 进度输出
        done = i + 1
        if done % 10 == 0:
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            print(f"  [{done}/{total}] {results} | 速率 {rate:.1f}/s | ETA {eta:.0f}s")

        # 单次请求间隔
        time.sleep(REQUEST_INTERVAL)

        # 批次休息
        if (i + 1) % BATCH_SIZE == 0 and i + 1 < total:
            time.sleep(BATCH_REST)

    elapsed = time.time() - start_time
    print()
    print(f"[DONE] 完成！总耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"[DONE] 结果: {results}")
    print(f"[DONE] 数据目录: {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="A股日线数据批量下载")
    parser.add_argument("--start", type=int, default=0, help="起始索引（断点续传用）")
    parser.add_argument("--end", type=int, default=None, help="结束索引")
    parser.add_argument("--symbols", default=None, help="逗号分隔的股票代码（如 600519,000001）")
    parser.add_argument("--sample", type=int, default=None, help="随机抽样N只（测试用）")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="起始日期 YYYYMMDD")
    parser.add_argument("--end-date", default=DEFAULT_END_DATE, help="结束日期 YYYYMMDD")
    parser.add_argument("--output-dir", default=str(DATA_DIR), help="输出目录")
    parser.add_argument("--no-skip", action="store_true", help="不跳过已存在的文件（强制重新下载）")
    args = parser.parse_args()

    # 获取股票列表
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
        print(f"[INFO] 指定代码: {len(symbols)} 只")
    else:
        print("[INFO] 获取全A股列表...")
        stock_list = get_stock_list()
        print(f"[INFO] 全A股共 {len(stock_list)} 只")
        symbols = stock_list["symbol"].tolist()

        if args.sample:
            import random
            random.seed(42)
            symbols = random.sample(symbols, min(args.sample, len(symbols)))
            print(f"[INFO] 随机抽样: {len(symbols)} 只")

    # 截取范围
    end_idx = args.end or len(symbols)
    symbols = symbols[args.start:end_idx]
    print(f"[INFO] 本次下载: {len(symbols)} 只（索引 {args.start}~{end_idx}）")

    download_batch(
        symbols=symbols,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        skip_existing=not args.no_skip,
    )


if __name__ == "__main__":
    main()
