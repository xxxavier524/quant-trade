#!/usr/bin/env python3
"""
Smart Downloader for A-share daily data (2020-01-01 ~ today).

- Gets the real A-share stock list from akshare (~5,500 stocks)
- Alternates primary source between baostock and akshare every N codes
- If primary fails, falls back to the other source (3 retries each)
- Respects per-source rate limits with random jitter
- Progress table printed every 500 codes
- Logs to logs/smart_download.log

Rate limits (from research):
  - baostock: 60 req/min unauthenticated -> safe at 1.0s interval
  - akshare:  ~5 req/s from upstream (eastmoney) -> safe at 0.35s interval

Usage:
  source .venv/bin/activate
  no_proxy='*' python scripts/_smart_downloader.py
"""

import os
import sys
import time
import random
import logging
import atexit
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict

import pandas as pd

# v3.0: Use DataFetcher for multi-source fallback
try:
    from alphapulse.utils.data_fetcher import DataFetcher
    _fetcher = DataFetcher(max_workers=3)
    _HAS_V3 = True
except ImportError:
    _HAS_V3 = False

# ── Paths ──────────────────────────────────────────────────
DATA_DIR = "/Volumes/Mac-480g外接/quantan_data/day"
LOG_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
PID_FILE = os.path.join(LOG_DIR, "smart_downloader.pid")
START_DATE = "2020-01-01"
END_DATE   = date.today().strftime("%Y-%m-%d")
MIN_ROWS   = 60   # minimum trading days required

# ── Rate limits (conservative, from research) ──────────────
BS_INTERVAL      = 1.0     # seconds between baostock requests (safe: 60/min)
AK_INTERVAL      = 0.35    # seconds between akshare requests (safe: ~3/sec)
AK_BATCH_SIZE    = 100     # extra rest every N akshare requests
AK_BATCH_REST    = 1.0     # seconds extra rest (reduced for speed)

ALTERNATE_EVERY   = 10     # switch primary source every N codes
MAX_RETRIES       = 3      # attempts per source
PROGRESS_EVERY    = 200    # print progress table every N codes
AK_FAIL_THRESHOLD = 10     # consecutive akshare failures -> disable it (reduced)
BS_RELOGIN_EVERY  = 500    # re-login baostock every N requests (session ~30min)

# ── Logging ────────────────────────────────────────────────
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
LOG_FMT = logging.Formatter(
    '%(asctime)s [%(levelname)-7s] %(message)s', datefmt='%H:%M:%S'
)

file_handler = logging.FileHandler(
    os.path.join(LOG_DIR, 'smart_download.log'), encoding='utf-8'
)
file_handler.setFormatter(LOG_FMT)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(LOG_FMT)

log = logging.getLogger("smart_dl")
log.setLevel(logging.INFO)
log.addHandler(file_handler)
log.addHandler(stream_handler)


# ══════════════════════════════════════════════════════════════
#  STOCK LIST
# ══════════════════════════════════════════════════════════════

def get_real_stock_list() -> list[str]:
    """Get the actual A-share stock list from akshare (~5,500 stocks)."""
    try:
        import akshare as ak
        os.environ.setdefault('no_proxy', '*')
        df = ak.stock_info_a_code_name()
        codes = sorted(df['code'].astype(str).str.zfill(6).tolist())
        log.info(f"Got {len(codes)} real A-share stocks from akshare")
        return codes
    except Exception as e:
        log.warning(f"AKShare stock list failed: {e}")
        log.info("Falling back to candidate code generation...")
        return _generate_candidate_codes()


def _generate_candidate_codes() -> list[str]:
    """Fallback: generate all possible A-share codes."""
    codes = set()
    for i in range(600000, 606000): codes.add(f"{i:06d}")
    for i in range(688000, 690000): codes.add(f"{i:06d}")
    for i in range(1, 4000):       codes.add(f"{i:06d}")
    for i in range(300000, 302000): codes.add(f"{i:06d}")
    for i in range(830000, 880000): codes.add(f"{i:06d}")
    for i in range(920000, 930000): codes.add(f"{i:06d}")
    return sorted(codes)


def get_downloaded_codes(data_dir: str) -> set[str]:
    """Scan data directory for already-downloaded valid CSV files.

    Uses file size check (>800 bytes) as quick filter — more reliable
    than header parsing which can miss files with slightly different headers."""
    downloaded = set()
    dp = Path(data_dir)
    if not dp.exists():
        return downloaded
    for fp in dp.glob("*.csv"):
        if fp.stat().st_size >= 800:
            downloaded.add(fp.stem)
    return downloaded


# ══════════════════════════════════════════════════════════════
#  BAOSTOCK DOWNLOADER
# ══════════════════════════════════════════════════════════════

def _bs_code(symbol: str) -> str:
    first = symbol[0]
    if first in ('6', '9'): return f"sh.{symbol}"
    if first in ('0', '2', '3'): return f"sz.{symbol}"
    if first in ('4', '8'): return f"bj.{symbol}"
    return f"sh.{symbol}"


def download_one_bs(symbol: str, data_dir: str) -> tuple:
    """Download one stock via baostock. Returns (symbol, num_rows, status_tag)."""
    import baostock as bs

    target = Path(data_dir) / f"{symbol}.csv"
    # NOTE: baostock requires "YYYY-MM-DD" format (NOT "YYYYMMDD")
    fields = "date,open,high,low,close,volume,amount,turn"
    s_date = START_DATE   # already "2020-01-01"
    e_date = END_DATE     # already "2026-05-19"

    for attempt in range(MAX_RETRIES):
        try:
            rs = bs.query_history_k_data_plus(
                _bs_code(symbol), fields,
                start_date=s_date, end_date=e_date,
                frequency="d", adjustflag="2",
            )
            if rs.error_code != '0':
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.0 + attempt * 0.5)
                    continue
                return (symbol, 0, f"bs_err:{rs.error_msg[:60]}")

            rows = []
            while rs.next():
                rows.append(rs.get_row_data())

            if len(rows) < MIN_ROWS:
                return (symbol, len(rows), "skip_empty")

            df = pd.DataFrame(rows, columns=fields.split(","))
            for c in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
            df = df[df['volume'].astype(float) > 0]
            df['date'] = pd.to_datetime(df['date'])
            df = df.dropna(subset=['open', 'close', 'volume'])

            if len(df) < MIN_ROWS:
                return (symbol, len(df), "skip_empty")

            df_out = df[['date','open','high','low','close','volume','amount','turn']].copy()
            df_out = df_out.rename(columns={'turn': 'turnover'})
            df_out.to_csv(target, index=False)
            return (symbol, len(df_out), "ok_bs")

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                return (symbol, 0, f"bs_exc:{str(e)[:60]}")

    return (symbol, 0, "bs_fail")


# ══════════════════════════════════════════════════════════════
#  AKSHARE DOWNLOADER
# ══════════════════════════════════════════════════════════════

def _ak_code(symbol: str) -> str:
    first = symbol[0]
    if first in ('6', '9'): return f"sh{symbol}"
    if first in ('0', '2', '3'): return f"sz{symbol}"
    if first in ('4', '8'): return f"bj{symbol}"
    return f"sh{symbol}"


def download_one_ak(symbol: str, data_dir: str) -> tuple:
    """Download one stock via akshare. Returns (symbol, num_rows, status_tag)."""
    import akshare as ak

    target = Path(data_dir) / f"{symbol}.csv"
    ak_code = _ak_code(symbol)
    s_date = START_DATE.replace("-", "")
    e_date = END_DATE.replace("-", "")

    for attempt in range(MAX_RETRIES):
        try:
            os.environ.setdefault('no_proxy', '*')

            df = ak.stock_zh_a_daily(
                symbol=ak_code,
                start_date=s_date,
                end_date=e_date,
                adjust="qfq",
            )

            if df is None or len(df) < MIN_ROWS:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                return (symbol, len(df) if df is not None else 0, "skip_empty")

            # Standardize columns
            col_rename = {c: c for c in df.columns if c in [
                'date','open','high','low','close','volume','amount','turnover'
            ]}
            df = df.rename(columns={k: v for k, v in col_rename.items()})

            needed = ['date','open','high','low','close','volume','amount']
            available = [c for c in needed if c in df.columns]
            df_out = df[available].copy()

            for c in ['open','high','low','close','volume','amount']:
                if c in df_out.columns:
                    df_out[c] = pd.to_numeric(df_out[c], errors='coerce')

            df_out['date'] = pd.to_datetime(df_out['date'])
            df_out = df_out.dropna(subset=['open','close','volume'])

            if len(df_out) < MIN_ROWS:
                return (symbol, len(df_out), "skip_empty")

            if 'turnover' in df.columns:
                df_out['turnover'] = pd.to_numeric(df['turnover'], errors='coerce')
            else:
                df_out['turnover'] = 0.0

            df_out.to_csv(target, index=False)
            return (symbol, len(df_out), "ok_ak")

        except ImportError:
            return (symbol, 0, "ak_not_installed")
        except Exception as e:
            err_str = str(e)[:80]
            if any(kw in err_str for kw in [
                "RemoteDisconnected","ProxyError","ConnectionError",
                "MaxRetryError","SSLError","Timeout"
            ]):
                return (symbol, 0, f"ak_netblock:{err_str}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                return (symbol, 0, f"ak_exc:{err_str}")

    return (symbol, 0, "ak_fail")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def print_progress_table(i: int, n: int, stats: dict, elapsed: float,
                         bs_avail: bool, ak_avail: bool, ak_cf: int):
    """Print a formatted progress report."""
    total_ok = stats.get('ok_bs', 0) + stats.get('ok_ak', 0)
    total_processed = i + 1
    ok_rate = total_ok / total_processed * 100 if total_processed > 0 else 0
    rate = total_processed / elapsed if elapsed > 0 else 0
    eta = (n - total_processed) / rate if rate > 0 else 0

    lines = [
        "",
        "=" * 72,
        f"  PROGRESS  {total_processed}/{n} ({100*total_processed/n:.1f}%)",
        f"  Elapsed: {elapsed/60:.1f}min | Rate: {rate:.2f}/s | ETA: {eta/60:.1f}min",
        f"  Skipped (existing): {stats.get('skip_existing', 0):,}",
        "-" * 72,
        f"  {'Source':<12} {'OK':>7} {'Skipped':>8} {'Failed':>7}  {'Status'}",
        f"  {'baostock':<12} {stats.get('ok_bs',0):>7} {stats.get('skip_bs',0):>8} "
        f"{stats.get('fail_bs',0):>7}  {'ON' if bs_avail else 'OFF'}",
        f"  {'akshare':<12} {stats.get('ok_ak',0):>7} {stats.get('skip_ak',0):>8} "
        f"{stats.get('fail_ak',0):>7}  {'ON' if ak_avail else 'OFF'}"
        f"{' (CF:'+str(ak_cf)+')' if ak_cf > 0 else ''}",
        "-" * 72,
        f"  Total OK: {total_ok} | Success rate: {ok_rate:.1f}%",
        "=" * 72,
        "",
    ]
    log.info("\n".join(lines))


def main():
    import baostock as bs

    # ── PID lock: prevent duplicate instances ───────────────
    if os.path.exists(PID_FILE):
        try:
            old_pid = int(Path(PID_FILE).read_text().strip())
            os.kill(old_pid, 0)  # check if process exists
            log.error(f"Another instance is already running (PID {old_pid}). Exiting.")
            return 1
        except (OSError, ValueError):
            # Stale PID file — remove and continue
            os.remove(PID_FILE)
    Path(PID_FILE).write_text(str(os.getpid()))
    atexit.register(lambda: os.remove(PID_FILE) if os.path.exists(PID_FILE) else None)

    log.info("=" * 60)
    log.info("SMART DOWNLOADER - A-share daily data")
    log.info(f"Date range: {START_DATE} ~ {END_DATE}")
    log.info(f"Data dir:   {DATA_DIR}")
    log.info(f"Started:    {datetime.now().isoformat()}")
    log.info("=" * 60)

    # ── Step 1: Get stock list ──────────────────────────────
    all_codes  = get_real_stock_list()
    downloaded = get_downloaded_codes(DATA_DIR)
    remaining  = [c for c in all_codes if c not in downloaded]

    log.info(f"Real A-share stocks:  {len(all_codes):,}")
    log.info(f"Already downloaded:   {len(downloaded):,}")
    log.info(f"Remaining to download: {len(remaining):,}")

    if not remaining:
        log.info("All stocks already downloaded!")
        return 0

    # Estimate time
    avg_delay = (BS_INTERVAL + AK_INTERVAL) / 2 + 0.15  # average jitter
    est_seconds = len(remaining) * avg_delay
    # Add batch rest for akshare
    ak_batches = (len(remaining) // 2) // AK_BATCH_SIZE
    est_seconds += ak_batches * AK_BATCH_REST
    log.info(f"Estimated total time: {est_seconds/60:.0f} min ({est_seconds/3600:.1f} h)")

    # ── Step 2: Health checks ──────────────────────────────
    # --- Baostock ---
    bs_available = False
    try:
        lg = bs.login()
        if lg.error_code == '0':
            bs_available = True
            log.info("[HEALTH] baostock login OK")
        else:
            log.warning(f"[HEALTH] baostock login failed: {lg.error_msg}")
    except Exception as e:
        log.warning(f"[HEALTH] baostock init error: {e}")

    # --- AKShare ---
    ak_available = False
    try:
        import akshare as ak
        os.environ['no_proxy'] = '*'
        test_df = ak.stock_zh_a_daily(
            symbol="sz000001", start_date="20250102",
            end_date="20250103", adjust="qfq"
        )
        if test_df is not None and len(test_df) > 0:
            ak_available = True
            log.info("[HEALTH] akshare test OK")
        else:
            log.warning("[HEALTH] akshare test returned empty")
    except Exception as e:
        log.warning(f"[HEALTH] akshare unavailable: {e}")

    if not bs_available and not ak_available:
        log.error("FATAL: Both sources unavailable.")
        return 1

    # ── Step 3: Source mode ────────────────────────────────
    # AKShare is ~20x faster than baostock for bulk downloads.
    # Use akshare as primary; only fall back to baostock if akshare is unavailable.
    if ak_available:
        mode = "ak_only"
        log.info("MODE: AKSHARE-PRIMARY (baostock as fallback only)")
        log.info(f"  AK interval={AK_INTERVAL}s | BS fallback interval={BS_INTERVAL}s")
    elif bs_available:
        mode = "bs_only"
        log.info("MODE: BAOSTOCK-ONLY (akshare unavailable)")
    else:
        log.error("FATAL: Neither source available.")
        return 1

    # ── Step 4: Download loop ──────────────────────────────
    stats = defaultdict(int)
    ak_disabled = not ak_available
    ak_consec_fail = 0
    bs_req_count = 0
    start_time = time.time()
    n = len(remaining)

    try:
      for i, symbol in enumerate(remaining):
        try:
            # Skip if already exists on disk (from other processes or previous runs)
            target_path = Path(DATA_DIR) / f"{symbol}.csv"
            if target_path.exists() and target_path.stat().st_size >= 800:
                stats['skip_existing'] += 1
                time.sleep(0.02)
                # Progress report
                if (i + 1) % PROGRESS_EVERY == 0:
                    elapsed = time.time() - start_time
                    print_progress_table(i, n, stats, elapsed,
                                        bs_available, ak_available and not ak_disabled,
                                        ak_consec_fail)
                continue

            # Determine primary source
            if mode == "bs_only":
                primary = "bs"
            elif mode == "ak_only":
                primary = "ak"
            else:
                primary = "bs" if (i // ALTERNATE_EVERY) % 2 == 0 else "ak"

            if ak_disabled and primary == "ak":
                primary = "bs"

            fallback = "ak" if primary == "bs" else "bs"

            # ── Attempt primary ──
            downloaded_ok = False
            is_empty = False

            if primary == "bs" and bs_available:
                sym, rows, status = download_one_bs(symbol, DATA_DIR)
                bs_req_count += 1
                if status == "ok_bs":
                    stats['ok_bs'] += 1; downloaded_ok = True
                elif status == "skip_empty":
                    stats['skip_bs'] += 1; is_empty = True
                else:
                    stats['fail_bs'] += 1

            elif primary == "ak" and ak_available and not ak_disabled:
                sym, rows, status = download_one_ak(symbol, DATA_DIR)
                if status == "ok_ak":
                    stats['ok_ak'] += 1; downloaded_ok = True
                    ak_consec_fail = 0
                elif status == "skip_empty":
                    stats['skip_ak'] += 1; is_empty = True
                elif status.startswith("ak_netblock"):
                    stats['fail_ak'] += 1; ak_consec_fail += 1
                else:
                    stats['fail_ak'] += 1; ak_consec_fail += 1
            else:
                stats[f'fail_{primary}'] += 1

            # ── Fallback ──
            if not downloaded_ok and not is_empty:
                fb_avail = (fallback == "bs" and bs_available) or \
                           (fallback == "ak" and ak_available and not ak_disabled)

                if fb_avail:
                    if fallback == "bs":
                        sym2, rows2, status2 = download_one_bs(symbol, DATA_DIR)
                        bs_req_count += 1
                        if status2 == "ok_bs":
                            stats['ok_bs'] += 1; downloaded_ok = True
                        elif status2 == "skip_empty":
                            stats['skip_bs'] += 1; is_empty = True
                        else:
                            stats['fail_bs'] += 1
                    else:
                        sym2, rows2, status2 = download_one_ak(symbol, DATA_DIR)
                        if status2 == "ok_ak":
                            stats['ok_ak'] += 1; downloaded_ok = True
                            ak_consec_fail = 0
                        elif status2 == "skip_empty":
                            stats['skip_ak'] += 1; is_empty = True
                        elif status2.startswith("ak_netblock"):
                            stats['fail_ak'] += 1; ak_consec_fail += 1
                        else:
                            stats['fail_ak'] += 1; ak_consec_fail += 1

            # ── Rate-limit delay ──
            if downloaded_ok:
                delay = BS_INTERVAL if primary == "bs" else AK_INTERVAL
                delay += random.uniform(0, 0.15)
            else:
                delay = 0.15 + random.uniform(0, 0.1)

            time.sleep(delay)

            # Extra akshare batch rest
            if primary == "ak" and (i + 1) % AK_BATCH_SIZE == 0:
                time.sleep(AK_BATCH_REST)

            # ── Periodic baostock re-login ──
            if bs_available and bs_req_count > 0 and bs_req_count % BS_RELOGIN_EVERY == 0:
                try:
                    bs.logout()
                    time.sleep(1)
                    lg = bs.login()
                    if lg.error_code == '0':
                        log.info(f"[RELOGIN] baostock OK at req #{bs_req_count}")
                    else:
                        log.warning(f"[RELOGIN] baostock failed: {lg.error_msg}")
                except Exception as e:
                    log.warning(f"[RELOGIN] baostock error: {e}")

            # ── Disable akshare after consecutive failures ──
            if not ak_disabled and ak_consec_fail >= AK_FAIL_THRESHOLD:
                log.warning(f"[DISABLE] AKShare after {AK_FAIL_THRESHOLD} consecutive fails")
                ak_disabled = True

            # ── Progress report ──
            if (i + 1) % PROGRESS_EVERY == 0:
                elapsed = time.time() - start_time
                print_progress_table(i, n, stats, elapsed,
                                    bs_available, ak_available and not ak_disabled,
                                    ak_consec_fail)
        except Exception as e:
            log.error(f"Unhandled error at code {i} ({symbol}): {e}", exc_info=True)
            stats['fatal_errors'] += 1
            time.sleep(1.0)
            continue
    except KeyboardInterrupt:
        log.warning("Interrupted by user (Ctrl+C)")
    except Exception as e:
        log.error(f"FATAL error in main loop: {e}", exc_info=True)

    # ── Step 5: Final report ───────────────────────────────
    if bs_available:
        try:
            bs.logout()
        except Exception:
            pass

    elapsed = time.time() - start_time
    final_count = len(get_downloaded_codes(DATA_DIR))
    total_ok = stats.get('ok_bs', 0) + stats.get('ok_ak', 0)
    total_skip = stats.get('skip_bs', 0) + stats.get('skip_ak', 0)
    total_fail = stats.get('fail_bs', 0) + stats.get('fail_ak', 0)
    total_skip_existing = stats.get('skip_existing', 0)

    log.info("")
    log.info("=" * 60)
    log.info("SMART DOWNLOADER - COMPLETE")
    log.info(f"Finished:   {datetime.now().isoformat()}")
    log.info(f"Duration:   {elapsed/60:.1f} min ({elapsed/3600:.2f} h)")
    log.info(f"Processed:  {n:,} codes")
    log.info(f"  Already existed: {total_skip_existing:,}")
    log.info(f"  baostock OK:     {stats.get('ok_bs',0):,}")
    log.info(f"  akshare OK:      {stats.get('ok_ak',0):,}")
    log.info(f"  Empty/skipped:   {total_skip:,}")
    log.info(f"  Failed:          {total_fail:,}")
    log.info(f"  Files before:    {len(downloaded):,}")
    log.info(f"  Files after:     {final_count:,}")
    log.info(f"  Net new:         {final_count - len(downloaded):,}")
    if total_ok + total_fail > 0:
        log.info(f"  Success rate:  {100*total_ok/(total_ok+total_fail):.1f}%")
    log.info("=" * 60)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
