#!/usr/bin/env python3
"""卡死股恢复 — 对落后多日的股票用 baostock 前复权全量重下。

背景（2026-06-16 诊断）：5月末-6月初分红送转高峰，约600只股票除权除息后
CSV 前复权历史被回溯改写，而每日增量的 pytdx 备援是不复权裸价，重叠日 close
对不上（偏差可达255%）→ 一致性检查正确拒绝 → 这些股票卡死在除权日。
只有 baostock 能给前复权数据，但每日批量并发被限流；单只低频拉取是通的。

本脚本专门慢速恢复：找落后股 → pytdx 确认仍在交易（排除真停牌）→
baostock 前复权全量重下（2020至今，整段统一复权基准）→ 原子覆盖。
低并发 + 重试退避，绕开批量限流。可重复运行（每次啃一批）。

用法：
    python scripts/recover_stale.py [--lag-days 3] [--limit 800] [--start 2020-01-01]
"""

import argparse
import os
import socket
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

socket.setdefaulttimeout(30)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.config.settings import DATA_DIR  # 统一读settings(2026-07-05迁内置盘)
COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]


def read_last_date(fpath: Path) -> str | None:
    try:
        with open(fpath, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 200))
            last = f.read().decode("utf-8", "ignore").strip().splitlines()[-1]
        d = last.split(",")[0]
        return d if len(d) == 10 and d[4] == "-" else None
    except Exception:
        return None


def bs_code(sym: str) -> str:
    return f"sh.{sym}" if sym.startswith(("6", "9")) else f"sz.{sym}"


def bs_full(bs, sym: str, start: str, end: str, retries: int = 3):
    """baostock 前复权全量；失败重试+退避。"""
    for attempt in range(retries):
        rs = bs.query_history_k_data_plus(
            bs_code(sym), "date,open,high,low,close,volume,amount,turn",
            start_date=start, end_date=end, frequency="d", adjustflag="2")
        rows = []
        while rs.error_code == "0" and rs.next():
            r = rs.get_row_data()
            if r[0]:
                rows.append(r)
        if rows:
            df = pd.DataFrame(rows, columns=["date", "open", "high", "low",
                                             "close", "volume", "amount", "turn"])
            df = df.rename(columns={"turn": "turnover"})
            for c in ("amount", "turnover"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df[COLUMNS]
        time.sleep(2 + attempt * 3)  # 退避重试
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lag-days", type=int, default=3, help="落后最新交易日>N个文件日才恢复")
    ap.add_argument("--limit", type=int, default=800)
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    data_path = Path(args.data_dir)
    if not data_path.exists():
        sys.exit(f"数据目录不存在: {data_path}")

    files = sorted(data_path.glob("*.csv"))
    last_dates = {f.stem: read_last_date(f) for f in files}
    valid = [d for d in last_dates.values() if d]
    latest = Counter(valid).most_common(1)[0][0]
    print(f"最新交易日(众数)={latest}，全市场 {len(files)} 只")

    # 落后股 = 尾日 < latest（按字符串比较，日期格式统一）
    stale = sorted(s for s, d in last_dates.items() if d and d < latest)
    print(f"落后股 {len(stale)} 只，开始恢复（baostock前复权全量重下）...")
    stale = stale[:args.limit]

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"
    import baostock as bs
    from alphapulse.utils.tdx_source import fetch_recent_daily

    lg = bs.login()
    if lg.error_code != "0":
        sys.exit(f"baostock登录失败: {lg.error_msg}")
    today = datetime.now().strftime("%Y-%m-%d")

    recovered, suspended, failed = 0, 0, 0
    for i, sym in enumerate(stale):
        # 先用 pytdx 确认仍在交易（排除真停牌：pytdx也无新数据的跳过）
        try:
            probe = fetch_recent_daily(sym, n=3)
            if probe is None or probe.empty or probe["date"].iloc[-1] < latest:
                suspended += 1
                continue
        except Exception:
            pass  # pytdx探测失败不阻断，仍尝试baostock

        df = bs_full(bs, sym, args.start, today)
        if df is not None and len(df) >= 60 and df["date"].iloc[-1] >= latest:
            tmp = data_path / f"{sym}.csv.tmp"
            df.to_csv(tmp, index=False)
            os.replace(tmp, data_path / f"{sym}.csv")
            recovered += 1
        else:
            failed += 1
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(stale)}: 恢复{recovered} 停牌{suspended} 失败{failed}")
        time.sleep(0.4)  # 低频避免限流

    bs.logout()
    print(f"\n恢复完成: 重下 {recovered} 只 · 真停牌 {suspended} 只 · 失败 {failed} 只（下次续）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
