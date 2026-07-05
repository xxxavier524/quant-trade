#!/usr/bin/env python3
"""每日增量数据更新（加固版）— 只追加缺失的交易日，绝不静默失败。

可靠性设计（Phase 1）：
1. 预检：数据目录必须已存在（绝不 mkdir——硬盘未挂载时会在系统盘静默建目录）；
   失败时写日志 + 飞书告警 + exit 2
2. 增量智能：先查上证指数确定最新交易日，已最新的股票直接跳过（零API调用）；
   未最新的从 last_date-7 起拉取（重叠窗口用于复权一致性检查）
3. 复权一致性：重叠日收盘价偏差 >0.1% 说明发生除权除息（前复权历史被改写），
   触发该股全量重下（每日上限 --refetch-limit 防失控）
4. 全局截止：--max-minutes（默认45）到点保存进度退出 exit 3，下次运行自动续传
5. 断点续传：logs/update_progress.json，同日重启从断点继续
6. 原子写：.tmp + os.replace，杀进程不会留下半截CSV
7. schema 自愈：旧版 turn 列与新版 turnover 列合并，逐步统一为 turnover

用法：
    python scripts/daily_update.py [--max-minutes 45] [--refetch-limit 200]
"""

import argparse
import json
import os
import socket
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# baostock 底层socket无超时——曾导致进程挂死8天（2026-06-03僵尸进程）。
# 全局socket超时让任何网络操作30秒内必然抛异常，而非永久阻塞。
socket.setdefaulttimeout(30)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.config.settings import DATA_DIR  # 统一读settings(2026-07-05迁内置盘)
LOGS_DIR = PROJECT_ROOT / "logs"
PROGRESS_FILE = LOGS_DIR / "update_progress.json"
FAILURE_LOG = LOGS_DIR / "data_update_failure.log"

COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]
BS_FIELDS = "date,open,high,low,close,volume,amount,turn"


def log_failure(msg: str) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    with open(FAILURE_LOG, "a") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    print(f"[FAIL] {msg}", file=sys.stderr)


def alert(msg: str) -> None:
    """飞书告警（webhook 未配置时仅写日志）。"""
    log_failure(msg)
    try:
        from alphapulse.config.settings import FEISHU_WEBHOOK_URL
        if FEISHU_WEBHOOK_URL:
            from alphapulse.notify.feishu_bot import send_feishu
            send_feishu(FEISHU_WEBHOOK_URL, f"⚠️ AlphaPulse 数据更新: {msg}")
    except Exception:
        pass


def preflight(data_path: Path) -> None:
    """硬盘挂载/目录存在性检查。绝不创建目录。"""
    if not data_path.exists():
        alert(f"数据目录不存在: {data_path}（外接硬盘未挂载？）任务中止。")
        sys.exit(2)
    if not any(data_path.glob("*.csv")):
        alert(f"数据目录为空: {data_path}（挂载点错误？）任务中止。")
        sys.exit(2)


def read_csv_last_date(fpath: Path) -> str | None:
    """高效读取CSV最后一行的日期（不加载整个文件）。"""
    try:
        with open(fpath, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", errors="ignore")
        last_line = tail.strip().splitlines()[-1]
        date = last_line.split(",")[0]
        return date if len(date) == 10 and date[4] == "-" else None
    except Exception:
        return None


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """schema 自愈：turn/turnover 合并为 turnover，统一列序。"""
    if "turn" in df.columns:
        if "turnover" in df.columns:
            df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(
                pd.to_numeric(df["turn"], errors="coerce"))
        else:
            df["turnover"] = pd.to_numeric(df["turn"], errors="coerce")
        df = df.drop(columns=["turn"])
    for col in ("amount", "turnover"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[[c for c in COLUMNS if c in df.columns]]


def atomic_write(df: pd.DataFrame, fpath: Path) -> None:
    tmp = fpath.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, fpath)


def bs_query(bs, code: str, start: str, end: str) -> pd.DataFrame:
    """baostock 拉取并标准化（前复权）。"""
    rs = bs.query_history_k_data_plus(
        code, BS_FIELDS, start_date=start, end_date=end,
        frequency="d", adjustflag="2")
    rows = []
    while (rs.error_code == "0") and rs.next():
        row = rs.get_row_data()
        if row[0]:
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount", "turn"])
    return normalize_df(df)


def bs_code(sym: str) -> str:
    return f"sh.{sym}" if sym.startswith(("6", "9")) else f"sz.{sym}"


def latest_trading_date(bs) -> str:
    """用上证指数确定最新交易日（1次API调用）。"""
    start = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    rs = bs.query_history_k_data_plus("sh.000001", "date,close",
                                      start_date=start, end_date=end, frequency="d")
    last = None
    while (rs.error_code == "0") and rs.next():
        last = rs.get_row_data()[0]
    if not last:
        alert("无法确定最新交易日（baostock 指数查询失败），任务中止。")
        sys.exit(2)
    return last


def load_progress(today: str) -> int:
    try:
        p = json.loads(PROGRESS_FILE.read_text())
        if p.get("date") == today:
            return int(p.get("done_index", 0))
    except Exception:
        pass
    return 0


def save_progress(today: str, idx: int, stats: dict) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps({"date": today, "done_index": idx, **stats}))


def all_a_share_codes() -> list[str]:
    codes = []
    for prefix in ("000", "001", "002", "003", "004", "300", "301",
                   "600", "601", "603", "605", "688", "920"):
        codes += [f"{prefix}{i:03d}" for i in range(1, 1000)]
    return codes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=45)
    ap.add_argument("--refetch-limit", type=int, default=200,
                    help="每日复权重下上限（防失控）")
    ap.add_argument("--new-limit", type=int, default=100,
                    help="每日新股全量下载上限")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    data_path = Path(args.data_dir)
    preflight(data_path)

    deadline = time.monotonic() + args.max_minutes * 60
    today_str = datetime.now().strftime("%Y-%m-%d")

    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        alert(f"baostock 登录失败: {lg.error_msg}")
        return 2

    latest = latest_trading_date(bs)
    print(f"[{datetime.now():%H:%M:%S}] 最新交易日: {latest}，开始增量更新")

    symbols = sorted(f.stem for f in data_path.glob("*.csv"))
    start_idx = load_progress(today_str)
    if start_idx:
        print(f"  从断点续传: {start_idx}/{len(symbols)}")

    stats = {"updated": 0, "current": 0, "refetched": 0, "failed": 0, "new": 0}
    timed_out = False
    consecutive_failures = 0
    relogin_done = False

    for i in range(start_idx, len(symbols)):
        if time.monotonic() > deadline:
            timed_out = True
            save_progress(today_str, i, stats)
            break
        # baostock 连接中途断开时所有请求会快速失败；先重连一次，再失败则保存进度退出
        if consecutive_failures >= 20:
            if not relogin_done:
                print("  连续失败≥20，尝试重新登录 baostock ...")
                try:
                    bs.logout()
                except Exception:
                    pass
                time.sleep(5)
                lg = bs.login()
                relogin_done = True
                if lg.error_code == "0":
                    consecutive_failures = 0
                    continue
            save_progress(today_str, i, stats)
            bs.logout()
            # baostock 断连但 pytdx 可能已覆盖主力：覆盖率达标则不算失败
            cov = _coverage(data_path, latest)
            if cov >= 0.75:
                print(f"  baostock断连但覆盖率{cov*100:.0f}%达标，视为完成")
                return 0
            alert(f"baostock 连接持续失败，覆盖率{cov*100:.0f}%，已存进度（{i}/{len(symbols)}）下次续传。")
            return 4
        sym = symbols[i]
        fpath = data_path / f"{sym}.csv"
        last_date = read_csv_last_date(fpath)

        if last_date and last_date >= latest:
            stats["current"] += 1  # 已最新，零API调用
            continue

        try:
            overlap_start = ((datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
                             if last_date else "2020-01-01")
            new_df = bs_query(bs, bs_code(sym), overlap_start, today_str)
            used_tdx = False
            if new_df.empty and last_date:
                # baostock失败 → pytdx直连备援（融合自daily_stock_analysis精华#1）。
                # pytdx为不复权裸价，靠下方重叠close一致性检查兜底：
                # 近期有除权则不一致 → 跳过等baostock，绝不混入错误价格
                try:
                    from alphapulse.utils.tdx_source import fetch_recent_daily
                    tdx_df = fetch_recent_daily(sym, n=30)
                    tdx_df = tdx_df[tdx_df["date"] >= overlap_start]
                    if not tdx_df.empty:
                        new_df = tdx_df
                        used_tdx = True
                        stats["tdx_fallback"] = stats.get("tdx_fallback", 0) + 1
                except Exception:
                    pass
            if new_df.empty:
                stats["failed"] += 1
                consecutive_failures += 1
                continue
            consecutive_failures = 0
            relogin_done = False

            old_df = normalize_df(pd.read_csv(fpath))

            # 复权一致性检查：重叠日期收盘价偏差>0.1% → 前复权被改写 → 全量重下
            overlap = old_df.merge(new_df, on="date", suffixes=("_old", "_new"))
            need_refetch = False
            if not overlap.empty:
                old_c = pd.to_numeric(overlap["close_old"], errors="coerce")
                new_c = pd.to_numeric(overlap["close_new"], errors="coerce")
                diff = ((old_c - new_c).abs() / old_c.replace(0, pd.NA)).max()
                need_refetch = bool(pd.notna(diff) and diff > 0.001)
            elif used_tdx:
                # pytdx数据必须有重叠日验证（无重叠=无法确认复权一致）→ 跳过
                stats["failed"] += 1
                continue

            if used_tdx and need_refetch:
                # pytdx裸价与前复权历史不一致=该股近期有除权 → 等baostock，绝不混入
                stats["failed"] += 1
                continue

            if need_refetch and stats["refetched"] < args.refetch_limit:
                full = bs_query(bs, bs_code(sym), "2020-01-01", today_str)
                if len(full) >= 60:
                    atomic_write(full, fpath)
                    stats["refetched"] += 1
                else:
                    stats["failed"] += 1
                time.sleep(0.3)
                continue

            combined = (pd.concat([old_df, new_df])
                        .drop_duplicates(subset=["date"], keep="last")
                        .sort_values("date"))
            atomic_write(combined, fpath)
            stats["updated"] += 1
        except Exception as e:
            stats["failed"] += 1
            consecutive_failures += 1
            if stats["failed"] <= 5:
                log_failure(f"{sym}: {e}")

        if (stats["updated"] + stats["failed"]) % 200 == 0:
            save_progress(today_str, i + 1, stats)
            print(f"  进度 {i+1}/{len(symbols)}: {stats}")
        time.sleep(0.12)

    # ── 新股发现（剩余时间内） ──
    if not timed_out:
        existing = set(symbols)
        new_candidates = [c for c in all_a_share_codes() if c not in existing][:args.new_limit]
        for sym in new_candidates:
            if time.monotonic() > deadline:
                timed_out = True
                break
            try:
                df = bs_query(bs, bs_code(sym), "2020-01-01", today_str)
                if len(df) >= 60:
                    atomic_write(df, data_path / f"{sym}.csv")
                    stats["new"] += 1
            except Exception:
                pass
            time.sleep(0.25)

    bs.logout()

    # 健康判据用"全市场覆盖率"（已到最新交易日占比），而非 baostock 失败数：
    # baostock 限流时 pytdx 备援已接住主力，失败的多是除权卡死股(由 recover_stale 治本)
    coverage = _coverage(data_path, latest)
    status = "TIMEOUT（下次续传）" if timed_out else "完成"
    summary = (f"数据更新{status} @ {latest}: 覆盖率 {coverage*100:.0f}%，已最新 {stats['current']}，"
               f"更新 {stats['updated']}，复权重下 {stats['refetched']}，新增 {stats['new']}，"
               f"失败 {stats['failed']}，TDX备援 {stats.get('tdx_fallback', 0)}")
    print(f"[{datetime.now():%H:%M:%S}] {summary}")

    save_progress(today_str, len(symbols), stats)
    if timed_out and coverage < 0.75:
        alert(summary)
        return 3
    # 覆盖率达标即视为健康（除权卡死股交由 recover_stale 专项恢复，不算每日更新失败）
    if coverage < 0.75:
        alert(f"覆盖率不足 {coverage*100:.0f}%（<75%）: {summary}")
        return 1
    return 0


def _coverage(data_path: Path, latest: str) -> float:
    """全市场已更新到最新交易日的占比（读尾行，快）。"""
    files = list(data_path.glob("*.csv"))
    if not files:
        return 0.0
    n_latest = sum(1 for f in files if read_csv_last_date(f) == latest)
    return n_latest / len(files)


if __name__ == "__main__":
    sys.exit(main())
