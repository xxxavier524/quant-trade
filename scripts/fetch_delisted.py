#!/usr/bin/env python3
"""退市股历史K线下载（幸存者偏差修正，2026-07-12）。

baostock 保留退市股的日线历史（实测2020年后退市的222只覆盖5/5，
更早的部分无数据会被自动跳过）。下载到主数据目录的兄弟目录 delisted/，
与生产选股完全隔离——只有回测经 --include-delisted 显式加载。

用法：
    python scripts/fetch_delisted.py               # 全部退市股（无数据自动跳过）
    python scripts/fetch_delisted.py --since 2019-01-01  # 只拉此日期后退市的
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alphapulse.config.settings import DATA_DIR  # noqa: E402

DELISTED_DIR = Path(DATA_DIR).parent / "delisted"

# 与主数据目录 CSV 完全同构，回测端可无差别加载
COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]


def fetch_all(since: str) -> dict:
    import baostock as bs
    bs.login()
    try:
        rs = bs.query_stock_basic()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        basic = pd.DataFrame(rows, columns=rs.fields)
        delisted = basic[(basic["type"] == "1") & (basic["status"] == "0")
                         & (basic["outDate"] >= since)].copy()
        print(f"退市股清单: {len(delisted)} 只（退市日 ≥ {since}）", flush=True)

        DELISTED_DIR.mkdir(parents=True, exist_ok=True)
        stats = {"downloaded": 0, "skipped_exists": 0, "no_data": 0, "failed": 0}
        meta_rows = []
        for i, (_, r) in enumerate(delisted.iterrows(), 1):
            code, out_date, name = r["code"], r["outDate"], r["code_name"]
            symbol = code.split(".")[1]
            path = DELISTED_DIR / f"{symbol}.csv"
            meta_rows.append({"symbol": symbol, "name": name,
                              "ipo": r["ipoDate"], "out": out_date})
            if path.exists() and path.stat().st_size > 1000:
                stats["skipped_exists"] += 1
                continue
            try:
                rk = bs.query_history_k_data_plus(
                    code, "date,open,high,low,close,volume,amount,turn",
                    start_date="2015-01-01", end_date=out_date,
                    frequency="d", adjustflag="2")
                kd = []
                while rk.error_code == "0" and rk.next():
                    kd.append(rk.get_row_data())
                if len(kd) < 60:
                    stats["no_data"] += 1
                    continue
                df = pd.DataFrame(kd, columns=["date", "open", "high", "low",
                                               "close", "volume", "amount", "turnover"])
                df = df[(df["close"] != "") & (df["volume"] != "")]
                df.to_csv(path, index=False)
                stats["downloaded"] += 1
            except Exception as e:
                stats["failed"] += 1
                print(f"  失败 {code}: {e}", flush=True)
            if i % 25 == 0:
                print(f"  进度 {i}/{len(delisted)} {stats}", flush=True)
            time.sleep(0.1)
        pd.DataFrame(meta_rows).to_csv(DELISTED_DIR / "_delisted_meta.csv", index=False)
        return stats
    finally:
        bs.logout()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2018-01-01",
                    help="只拉此日期之后退市的（更早的baostock多无数据）")
    args = ap.parse_args()
    t0 = time.monotonic()
    stats = fetch_all(args.since)
    print(f"完成 @ {DELISTED_DIR}: {stats}，耗时 {(time.monotonic()-t0)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
