#!/usr/bin/env python3
"""A股日线数据批量下载脚本（baostock 数据源）。

使用 baostock 下载全A股日线数据（2020-01-01 ~ 今），
存为 {output_dir}/{symbol}.csv。

特性：
- 限流：每次请求间隔 0.3s，批量每 30 只休息 3s
- 断点续传：跳过已下载的股票
- 进度条：显示已下载/总数/耗时
- 自动重试：单只失败重试3次

用法:
    python scripts/download_a_share_data.py                    # 全部A股
    python scripts/download_a_share_data.py --sample 100       # 随机抽样100只
    python scripts/download_a_share_data.py --symbols 600519,000001  # 指定代码
    python scripts/download_a_share_data.py --start 500        # 从第500只继续
"""

import argparse
import sys
import time
from pathlib import Path
from datetime import date
from io import StringIO

import pandas as pd
import numpy as np
import baostock as bs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alphapulse.config.settings import DATA_DIR

DEFAULT_START_DATE = "2020-01-01"
DEFAULT_END_DATE = date.today().strftime("%Y-%m-%d")

# 日期格式转换（支持 YYYYMMDD -> YYYY-MM-DD）
def _fmt_date(d: str) -> str:
    d = d.replace("-", "")
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d
REQUEST_INTERVAL = 0.3
BATCH_SIZE = 30
BATCH_REST = 3.0
MIN_REQUIRED_DAYS = 60

# 沪深两市股票代码前缀映射
CODE_PREFIX_MAP = {
    "6": "sh",   # 上海主板
    "9": "sh",   # 上海B股（极少）
    "0": "sz",   # 深圳主板
    "3": "sz",   # 深圳创业板
    "2": "sz",   # 深圳（少数）
    "4": "bj",   # 北交所
    "8": "bj",   # 北交所/新三板
}
# 北交所代码以 83/87/88 开头，科创板以 688 开头
BS_CODE_CACHE = {}  # symbol -> baostock_code


def _resolve_bs_code_fast(symbol: str) -> str:
    """根据股票代码快速推断 baostock 格式。"""
    if symbol[0] in ("6", "9"):
        return f"sh.{symbol}"
    elif symbol[0] in ("0", "2", "3"):
        return f"sz.{symbol}"
    elif symbol[0] in ("4", "8"):
        return f"bj.{symbol}"
    else:
        return f"sh.{symbol}"  # 默认上海


def get_stock_list() -> list[str]:
    """快速生成全A股代码列表（覆盖所有可能范围）。

    替代慢速的 bs.query_stock_basic()——逐个下载时会自动过滤无效代码。
    """
    symbols = set()
    # 上海主板 600000-605999
    for i in range(600000, 606000): symbols.add(f"{i:06d}")
    # 上海科创板 688000-689999
    for i in range(688000, 690000): symbols.add(f"{i:06d}")
    # 深圳主板 000001-003999
    for i in range(1, 4000): symbols.add(f"{i:06d}")
    # 深圳创业板 300000-301999
    for i in range(300000, 302000): symbols.add(f"{i:06d}")
    # 北交所 830000-879999 + 920000-929999
    for i in range(830000, 880000): symbols.add(f"{i:06d}")
    for i in range(920000, 930000): symbols.add(f"{i:06d}")
    # 预缓存 baostock code 格式
    for sym in list(symbols):
        BS_CODE_CACHE[sym] = _resolve_bs_code_fast(sym)
    return sorted(symbols)


def download_single_stock(
    symbol: str,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    output_dir: str = None,
    retries: int = 3,
) -> tuple[str, int, str]:
    """下载单只股票日线数据。

    Returns:
        (symbol, rows, status)
    """
    output_dir = output_dir or str(DATA_DIR)
    output_path = Path(output_dir) / f"{symbol}.csv"

    bs_code = BS_CODE_CACHE.get(symbol, _resolve_bs_code_fast(symbol))

    fields = "date,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg"
    s_date = _fmt_date(start_date)
    e_date = _fmt_date(end_date)

    for attempt in range(retries):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code, fields,
                start_date=s_date,
                end_date=e_date,
                frequency="d",
                adjustflag="2",  # 前复权
            )

            if rs.error_code != "0":
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return (symbol, 0, f"error: {rs.error_msg[:60]}")

            rows = []
            while rs.next():
                rows.append(rs.get_row_data())

            if not rows or len(rows) < MIN_REQUIRED_DAYS:
                return (symbol, len(rows), "skip_empty")

            df = pd.DataFrame(rows, columns=fields.split(","))

            # 过滤掉空数据行（tradestatus=0表示停牌）
            df = df[df["tradestatus"] == "1"].copy()
            if len(df) < MIN_REQUIRED_DAYS:
                return (symbol, len(df), "skip_empty")

            # 转换数据类型
            for col in ["open", "high", "low", "close", "preclose", "volume", "amount"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df["date"] = pd.to_datetime(df["date"])
            df = df.dropna(subset=["open", "high", "low", "close", "volume"])

            # 标准化输出列
            out_cols = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]
            df_out = df[["date", "open", "high", "low", "close", "volume", "amount", "turn"]].copy()
            df_out = df_out.rename(columns={"turn": "turnover"})

            Path(output_dir).mkdir(parents=True, exist_ok=True)
            df_out.to_csv(output_path, index=False)
            return (symbol, len(df_out), "ok")

        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                return (symbol, 0, f"error: {str(e)[:80]}")

    return (symbol, 0, "error")


def is_already_downloaded(symbol: str, output_dir: str, min_rows: int = MIN_REQUIRED_DAYS) -> bool:
    output_path = Path(output_dir) / f"{symbol}.csv"
    if not output_path.exists():
        return False
    try:
        return len(pd.read_csv(output_path)) >= min_rows
    except Exception:
        return False


def get_stock_list() -> list[str]:
    """快速生成全A股代码列表（覆盖所有可能范围，不查询baostock）。

    无效代码在下载时由 download_single_stock 自然过滤（返回 empty/error）。
    """
    symbols = set()
    for i in range(600000, 606000): symbols.add(f"{i:06d}")
    for i in range(688000, 690000): symbols.add(f"{i:06d}")
    for i in range(1, 4000): symbols.add(f"{i:06d}")
    for i in range(300000, 302000): symbols.add(f"{i:06d}")
    for i in range(830000, 880000): symbols.add(f"{i:06d}")
    for i in range(920000, 930000): symbols.add(f"{i:06d}")
    # 预缓存 baostock code 格式
    for sym in list(symbols):
        BS_CODE_CACHE[sym] = f"sh.{sym}" if sym[0] in "69" else f"sz.{sym}"
    return sorted(symbols)


def download_batch(
    symbols: list[str],
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    output_dir: str = None,
    skip_existing: bool = True,
):
    out_dir = output_dir or str(DATA_DIR)
    total = len(symbols)
    results = {"ok": 0, "skip_empty": 0, "skip_existing": 0, "skip_no_code": 0, "error": 0}
    start_time = time.time()

    print(f"[INFO] 数据源: baostock")
    print(f"[INFO] 目标: {total} 只")
    print(f"[INFO] 日期: {start_date} ~ {end_date}")
    print(f"[INFO] 输出: {out_dir}")
    print()

    bs.login()

    for i, symbol in enumerate(symbols):
        if skip_existing and is_already_downloaded(symbol, out_dir):
            results["skip_existing"] += 1
            if (i + 1) % 50 == 0:
                elapsed = time.time() - start_time
                done = i + 1
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] {results} | {rate:.1f}/s | ETA {eta:.0f}s")
            continue

        sym, rows, status = download_single_stock(symbol, start_date, end_date, out_dir)
        key = status.split(":")[0] if ":" in status else status
        results[key] = results.get(key, 0) + 1

        done = i + 1
        if done % 10 == 0:
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            print(f"  [{done}/{total}] {results} | {rate:.1f}/s | ETA {eta:.0f}s")

        time.sleep(REQUEST_INTERVAL)
        if (i + 1) % BATCH_SIZE == 0 and i + 1 < total:
            time.sleep(BATCH_REST)

    bs.logout()

    elapsed = time.time() - start_time
    print(f"\n[DONE] {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"[DONE] {results}")


def main():
    parser = argparse.ArgumentParser(description="A股日线批量下载 (baostock)")
    parser.add_argument("--start", type=int, default=0, help="起始索引")
    parser.add_argument("--end", type=int, default=None, help="结束索引")
    parser.add_argument("--symbols", default=None, help="逗号分隔代码")
    parser.add_argument("--sample", type=int, default=None, help="随机抽样N只")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="起始日期")
    parser.add_argument("--end-date", default=DEFAULT_END_DATE, help="结束日期")
    parser.add_argument("--output-dir", default=str(DATA_DIR), help="输出目录")
    parser.add_argument("--no-skip", action="store_true", help="强制重新下载")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        print("[INFO] 获取A股列表...")
        symbols = get_stock_list()
        print(f"[INFO] 共 {len(symbols)} 只")
        if args.sample:
            import random
            random.seed(42)
            symbols = random.sample(symbols, min(args.sample, len(symbols)))

    end_idx = args.end or len(symbols)
    symbols = symbols[args.start:end_idx]
    print(f"[INFO] 本次: {len(symbols)} 只")

    download_batch(
        symbols=symbols,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        skip_existing=not args.no_skip,
    )


if __name__ == "__main__":
    main()
