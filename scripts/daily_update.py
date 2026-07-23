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
5. 断点续传：logs/update_progress.json，同日同交易日重启从断点继续；
   覆盖率不达标时清除断点（防一次坏运行锁死当天重试，2026-07-10修正）
6. 原子写：.tmp + os.replace，杀进程不会留下半截CSV
7. schema 自愈：旧版 turn 列与新版 turnover 列合并，逐步统一为 turnover

用法：
    python scripts/daily_update.py [--max-minutes 45] [--refetch-limit 200]
"""

import argparse
import atexit
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
PID_FILE = LOGS_DIR / "daily_update.pid"
_QUIET = False  # --quiet：抑制飞书告警（仅写文件日志），供 data_catchup 每小时静默续传

COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]
BS_FIELDS = "date,open,high,low,close,volume,amount,turn"


def log_failure(msg: str) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    with open(FAILURE_LOG, "a") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    print(f"[FAIL] {msg}", file=sys.stderr)


def alert(msg: str) -> None:
    """飞书告警（webhook 未配置时仅写日志）。--quiet 模式只写文件日志、不推飞书。"""
    log_failure(msg)
    if _QUIET:
        return
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


def latest_trading_date(bs, data_path: Path | None = None) -> str:
    """用上证指数确定最新交易日。baostock 不可用时退回 akshare 指数 / 现有CSV众数。"""
    start = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    if bs is not None:
        rs = bs.query_history_k_data_plus("sh.000001", "date,close",
                                          start_date=start, end_date=end, frequency="d")
        last = None
        while (rs.error_code == "0") and rs.next():
            last = rs.get_row_data()[0]
        if last:
            return last
    # 兜底1：akshare 指数
    try:
        from alphapulse.utils.source_chain import fetch_daily
        res = fetch_daily("000001", start, end, ctx={}, per_source_timeout=15,
                          chain=[("akshare", __import__(
                              "alphapulse.utils.source_chain", fromlist=["_src_akshare"]
                          )._src_akshare, True)])
        if len(res.df):
            return str(res.df["date"].iloc[-1])[:10]
    except Exception:
        pass
    # 兜底2：现有CSV最后日期众数
    if data_path is not None:
        dates = [d for d in (read_csv_last_date(f) for f in data_path.glob("*.csv")) if d]
        if dates:
            return pd.Series(dates).mode().iloc[0]
    alert("无法确定最新交易日（所有源失败且无本地数据），任务中止。")
    sys.exit(2)


def load_progress(today: str, latest: str) -> int:
    try:
        p = json.loads(PROGRESS_FILE.read_text())
        # 断点须同时匹配运行日与最新交易日：晚间 baostock 发布新交易日后，
        # 下午写的"已完成"断点自动失效，22:00 重试得以拉取当日K线
        if p.get("date") == today and p.get("latest") == latest:
            return int(p.get("done_index", 0))
    except Exception:
        pass
    return 0


def save_progress(today: str, idx: int, stats: dict, latest: str) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    tmp = PROGRESS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(
        {"date": today, "done_index": idx, "latest": latest, **stats}))
    os.replace(tmp, PROGRESS_FILE)  # 原子替换：杀进程不留半截进度文件（H3）


def acquire_singleton_lock() -> None:
    """PID 锁：防止 15:30 与 20:30 两个 launchd 任务并发跑同一更新，互相踩
    update_progress.json 并把失败日志重复写两遍（H3，复用 _smart_downloader 模式）。
    已有存活实例则退出 2；陈旧锁自动清理。"""
    LOGS_DIR.mkdir(exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            os.kill(old_pid, 0)  # 进程存活则不抛异常
            alert(f"另一 daily_update 实例仍在运行（PID {old_pid}），本次退出避免并发踩踏。")
            sys.exit(2)
        except (OSError, ValueError):
            PID_FILE.unlink(missing_ok=True)  # 陈旧锁，清掉继续
    PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: PID_FILE.unlink(missing_ok=True))


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
    ap.add_argument("--source-timeout", type=float, default=15.0,
                    help="每个数据源的单次超时秒数（超时自动切下一个源）")
    ap.add_argument("--quiet", action="store_true",
                    help="抑制飞书告警（仅写文件日志）——供 data_catchup 每小时静默续传")
    args = ap.parse_args()
    per_source_timeout = args.source_timeout
    global _QUIET
    _QUIET = args.quiet

    acquire_singleton_lock()  # 防 15:30/20:30 并发踩踏（H3）
    data_path = Path(args.data_dir)
    preflight(data_path)

    deadline = time.monotonic() + args.max_minutes * 60
    today_str = datetime.now().strftime("%Y-%m-%d")

    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        alert(f"baostock 登录失败: {lg.error_msg}")
        # baostock 登录失败不再直接退出：多源链里还有 akshare/pytdx/腾讯兜底
        print("  baostock 登录失败，继续用 akshare/pytdx/腾讯 多源兜底")
        bs = None

    from alphapulse.utils.source_chain import fetch_daily

    latest = latest_trading_date(bs, data_path)
    print(f"[{datetime.now():%H:%M:%S}] 最新交易日: {latest}，开始增量更新")

    symbols = sorted(f.stem for f in data_path.glob("*.csv"))
    start_idx = load_progress(today_str, latest)
    if start_idx:
        print(f"  从断点续传: {start_idx}/{len(symbols)}")

    stats = {"updated": 0, "current": 0, "refetched": 0, "failed": 0, "new": 0}
    breaker: dict = {}   # 跨股票共享的源熔断状态（某源夜间宕机→连续失败达阈值即跳过）
    timed_out = False
    consecutive_failures = 0
    relogin_done = False

    for i in range(start_idx, len(symbols)):
        if time.monotonic() > deadline:
            timed_out = True
            save_progress(today_str, i, stats, latest)
            break
        # 连续失败≥20：baostock 若在用先重连一次；多源链下裸价源/akshare 仍可工作，
        # 故仅在覆盖率不足时才退出续传（bs=None 时跳过重连逻辑）。
        if consecutive_failures >= 20:
            if bs is not None and not relogin_done:
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
            save_progress(today_str, i, stats, latest)
            if bs is not None:
                try:
                    bs.logout()
                except Exception:
                    pass
            # 主源断连但裸价源/akshare 可能已覆盖主力：覆盖率达标则不算失败
            cov = _coverage(data_path, latest)
            if cov >= 0.75:
                print(f"  主源持续失败但覆盖率{cov*100:.0f}%达标，视为完成")
                return 0
            alert(f"多源持续失败，覆盖率{cov*100:.0f}%，已存进度（{i}/{len(symbols)}）下次续传。")
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
            # 多源故障切换取数：baostock→akshare→pytdx→腾讯，逐源独立超时自动切换。
            # 前复权源(baostock/akshare)可直接采信；裸价源(pytdx/腾讯)标记 used_raw，
            # 靠下方重叠close一致性检查兜底：近期有除权则不一致 → 跳过等复权源。
            res = fetch_daily(sym, overlap_start, today_str,
                              ctx={"bs": bs}, per_source_timeout=per_source_timeout,
                              stats=stats, breaker=breaker)
            new_df = res.df
            used_tdx = not res.adjusted        # 沿用下方裸价校验分支的变量名
            # 只摄入已确认交易日（≤latest）的K线：盘中运行时裸价源返回当日
            # 形成中的半截K线，一旦写入且 last_date>=latest 会被永远跳过不再修正
            if not new_df.empty:
                new_df = new_df[new_df["date"] <= latest]
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
            save_progress(today_str, i + 1, stats, latest)
            print(f"  进度 {i+1}/{len(symbols)}: {stats}")
        time.sleep(0.12)

    # ── 新股发现（剩余时间内，走多源链） ──
    if not timed_out:
        existing = set(symbols)
        new_candidates = [c for c in all_a_share_codes() if c not in existing][:args.new_limit]
        for sym in new_candidates:
            if time.monotonic() > deadline:
                timed_out = True
                break
            try:
                res = fetch_daily(sym, "2020-01-01", today_str, ctx={"bs": bs},
                                  per_source_timeout=per_source_timeout,
                                  stats=stats, breaker=breaker)
                if len(res.df) >= 60:
                    atomic_write(res.df, data_path / f"{sym}.csv")
                    stats["new"] += 1
            except Exception:
                pass
            time.sleep(0.25)

    if bs is not None:
        try:
            bs.logout()
        except Exception:
            pass

    # 健康判据用"全市场覆盖率"（已到最新交易日占比），而非 baostock 失败数：
    # baostock 限流时 pytdx 备援已接住主力，失败的多是除权卡死股(由 recover_stale 治本)
    coverage = _coverage(data_path, latest)
    status = "TIMEOUT（下次续传）" if timed_out else "完成"
    src_hits = " ".join(f"{k[4:]}={v}" for k, v in sorted(stats.items())
                        if k.startswith("src_"))
    tripped = [k[len("tripped_"):] for k in stats if k.startswith("tripped_")]
    if tripped:
        src_hits += f" | 熔断源:{','.join(tripped)}"
    summary = (f"数据更新{status} @ {latest}: 覆盖率 {coverage*100:.0f}%，已最新 {stats['current']}，"
               f"更新 {stats['updated']}，复权重下 {stats['refetched']}，新增 {stats['new']}，"
               f"失败 {stats['failed']}，超时切换 {stats.get('timeout', 0)}，"
               f"源命中[{src_hits or '无'}]")
    print(f"[{datetime.now():%H:%M:%S}] {summary}")

    # 断点语义（2026-07-10修正）：只有"跑完且覆盖率达标"才写满 done_index。
    # 此前无条件写满 → 一次坏运行(覆盖率0%)锁死当天所有重试（07-07/07-09两次复现）
    if timed_out:
        # 循环内已 save_progress(done_index=i)，保留供同日续传
        if coverage < 0.75:
            alert(summary)
            return 3
        return 0
    if coverage < 0.75:
        PROGRESS_FILE.unlink(missing_ok=True)  # 清断点：当天重试可全量重扫
        alert(f"覆盖率不足 {coverage*100:.0f}%（<75%）: {summary}")
        return 1
    # 覆盖率达标即视为健康（除权卡死股交由 recover_stale 专项恢复，不算每日更新失败）
    save_progress(today_str, len(symbols), stats, latest)
    return 0


def _coverage(data_path: Path, latest: str) -> float:
    """全市场已更新到最新交易日的占比（读尾行，快）。"""
    files = list(data_path.glob("*.csv"))
    if not files:
        return 0.0
    n_latest = sum(1 for f in files if (read_csv_last_date(f) or "") >= latest)
    return n_latest / len(files)


if __name__ == "__main__":
    sys.exit(main())
