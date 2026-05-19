#!/usr/bin/env python3
"""
Smart Downloader for A-share daily data (2020-01-01 ~ today).

Alternates primary source between baostock and akshare every N codes.
If primary fails, falls back to the other source (3 retries each).
Respects per-source rate limits with random jitter.
Progress table printed every 500 codes.

Rate limits (from research):
  - baostock: 60 req/min unauthenticated -> safe at 1.0s interval
  - akshare:  ~5 req/s recommended   -> safe at 0.35s interval + batch rest

Usage:
  source .venv/bin/activate
  no_proxy='*' python scripts/_smart_downloader.py
"""

import os
import sys
import time
import random
import logging
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict

import pandas as pd
import baostock as bs

# ── Paths ──────────────────────────────────────────────────
DATA_DIR = "/Volumes/Mac-480g外接/quantan_data/day"
LOG_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
START_DATE = "2020-01-01"
END_DATE   = date.today().strftime("%Y-%m-%d")
MIN_ROWS   = 60   # minimum trading days required

# ── Rate limits ────────────────────────────────────────────
BS_INTERVAL      = 1.0     # seconds between baostock requests
BS_INTERVAL_FAST = 0.15    # seconds when result is empty (invalid code)
AK_INTERVAL      = 0.35    # seconds between akshare requests
AK_BATCH_SIZE    = 50      # extra rest every N akshare requests
AK_BATCH_REST    = 2.0     # seconds extra rest

ALTERNATE_EVERY   = 10     # switch primary source every N codes
MAX_RETRIES       = 3      # attempts per source
PROGRESS_EVERY    = 500    # print progress table every N codes
AK_FAIL_THRESHOLD = 50     # consecutive akshare failures before disabling it
BS_RELOGIN_EVERY  = 500    # re-login baostock every N requests (session timeout ~30min)

# ── Logging ────────────────────────────────────────────────
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
LOG_FMT = logging.Formatter('%(asctime)s [%(levelname)-7s] %(message)s', datefmt='%H:%M:%S')

file_handler = logging.FileHandler(os.path.join(LOG_DIR, 'smart_download.log'), encoding='utf-8')
file_handler.setFormatter(LOG_FMT)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(LOG_FMT)

log = logging.getLogger("smart_dl")
log.setLevel(logging.INFO)
log.addHandler(file_handler)
log.addHandler(stream_handler)


# ══════════════════════════════════════════════════════════════
#  STOCK LIST GENERATION
# ══════════════════════════════════════════════════════════════

def generate_candidate_codes() -> list[str]:
    """Generate all possible A-share codes. Invalid ones filtered at download time."""
    codes = set()
    for i in range(600000, 606000): codes.add(f"{i:06d}")   # SSE main
    for i in range(688000, 690000): codes.add(f"{i:06d}")   # STAR
    for i in range(1, 4000):       codes.add(f"{i:06d}")    # SZSE main
    for i in range(300000, 302000): codes.add(f"{i:06d}")   # ChiNext
    for i in range(830000, 880000): codes.add(f"{i:06d}")   # BSE old
    for i in range(920000, 930000): codes.add(f"{i:06d}")   # BSE new
    return sorted(codes)


def get_downloaded_codes(data_dir: str) -> set[str]:
    """Scan data directory for already-downloaded valid CSV files."""
    downloaded = set()
    dp = Path(data_dir)
    if not dp.exists():
        return downloaded
    for fp in dp.glob("*.csv"):
        if fp.stat().st_size < 800:
            continue  # too small to be valid
        try:
            df = pd.read_csv(fp, nrows=2)
            if len(df.columns) >= 4:
                downloaded.add(fp.stem)
        except Exception:
            pass
    return downloaded


# ══════════════════════════════════════════════════════════════
#  BAOSTOCK DOWNLOADER
# ══════════════════════════════════════════════════════════════

def _bs_code(symbol: str) -> str:
    """Map A-share code to baostock exchange.code format."""
    first = symbol[0]
    if first in ('6', '9'):
        return f"sh.{symbol}"
    elif first in ('0', '2', '3'):
        return f"sz.{symbol}"
    elif first in ('4', '8'):
        return f"bj.{symbol}"
    return f"sh.{symbol}"


def download_one_bs(symbol: str, data_dir: str, retries: int = MAX_RETRIES) -> tuple:
    """
    Download one stock via baostock.
    Returns: (symbol, num_rows, status_tag)
      status_tag: "ok_bs" | "skip_empty" | "bs_err:..." | "bs_exc:..."
    """
    target = Path(data_dir) / f"{symbol}.csv"
    fields = "date,open,high,low,close,volume,amount,turn"
    s_date = START_DATE.replace("-", "")
    e_date = END_DATE.replace("-", "")

    for attempt in range(retries):
        try:
            rs = bs.query_history_k_data_plus(
                _bs_code(symbol), fields,
                start_date=s_date, end_date=e_date,
                frequency="d", adjustflag="2",
            )
            if rs.error_code != '0':
                if attempt < retries - 1:
                    time.sleep(1.0 + attempt * 0.5)
                    continue
                return (symbol, 0, f"bs_err:{rs.error_msg[:50]}")

            rows = []
            while rs.next():
                rows.append(rs.get_row_data())

            if len(rows) < MIN_ROWS:
                return (symbol, len(rows), "skip_empty")

            # Parse and validate
            df = pd.DataFrame(rows, columns=fields.split(","))
            for c in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
            df = df[df['volume'].astype(float) > 0]
            df['date'] = pd.to_datetime(df['date'])
            df = df.dropna(subset=['open', 'close', 'volume'])

            if len(df) < MIN_ROWS:
                return (symbol, len(df), "skip_empty")

            # Standardize output columns
            df_out = df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn']].copy()
            df_out = df_out.rename(columns={'turn': 'turnover'})
            df_out.to_csv(target, index=False)
            return (symbol, len(df_out), "ok_bs")

        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                return (symbol, 0, f"bs_exc:{str(e)[:60]}")

    return (symbol, 0, "bs_fail")


# ══════════════════════════════════════════════════════════════
#  AKSHARE DOWNLOADER
# ══════════════════════════════════════════════════════════════

def _ak_code(symbol: str) -> str:
    """Map A-share code to akshare exchange+code format."""
    first = symbol[0]
    if first in ('6', '9'):
        return f"sh{symbol}"
    elif first in ('0', '2', '3'):
        return f"sz{symbol}"
    elif first in ('4', '8'):
        return f"bj{symbol}"
    return f"sh{symbol}"


def download_one_ak(symbol: str, data_dir: str, retries: int = MAX_RETRIES) -> tuple:
    """
    Download one stock via akshare.
    Returns: (symbol, num_rows, status_tag)
    """
    target = Path(data_dir) / f"{symbol}.csv"
    ak_code = _ak_code(symbol)
    s_date = START_DATE.replace("-", "")
    e_date = END_DATE.replace("-", "")

    for attempt in range(retries):
        try:
            import akshare as ak
            os.environ.setdefault('no_proxy', '*')

            df = ak.stock_zh_a_daily(
                symbol=ak_code,
                start_date=s_date,
                end_date=e_date,
                adjust="qfq",
            )

            if df is None or len(df) < MIN_ROWS:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return (symbol, len(df) if df is not None else 0, "skip_empty")

            # Standardize
            col_map = {
                'date': 'date', 'open': 'open', 'high': 'high',
                'low': 'low', 'close': 'close', 'volume': 'volume',
                'amount': 'amount',
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

            needed = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
            available = [c for c in needed if c in df.columns]
            df_out = df[available].copy()

            for c in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                if c in df_out.columns:
                    df_out[c] = pd.to_numeric(df_out[c], errors='coerce')

            df_out['date'] = pd.to_datetime(df_out['date'])
            df_out = df_out.dropna(subset=['open', 'close', 'volume'])

            if len(df_out) < MIN_ROWS:
                # AKShare returns empty DataFrame for non-existent codes
                return (symbol, len(df_out), "skip_empty")

            # Add turnover if available
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
            # Fast-fail on network-level blocks
            if "RemoteDisconnected" in err_str or "ProxyError" in err_str or "ConnectionError" in err_str:
                return (symbol, 0, f"ak_netblock:{err_str}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                return (symbol, 0, f"ak_exc:{err_str}")

    return (symbol, 0, "ak_fail")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def print_progress_table(i: int, n: int, stats: dict, elapsed: float,
                         bs_avail: bool, ak_avail: bool, ak_consec_fail: int):
    """Print a formatted progress report."""
    total_ok = stats['ok_bs'] + stats['ok_ak']
    total_processed = i + 1
    ok_rate = total_ok / total_processed * 100 if total_processed > 0 else 0

    rate = total_processed / elapsed if elapsed > 0 else 0
    eta = (n - total_processed) / rate if rate > 0 else 0

    lines = [
        "",
        "=" * 72,
        f"  PROGRESS REPORT  |  {total_processed}/{n} ({100*total_processed/n:.1f}%)",
        f"  Elapsed: {elapsed/60:.1f} min  |  Rate: {rate:.1f} codes/s  |  ETA: {eta/60:.1f} min",
        "-" * 72,
        f"  {'Source':<12} {'OK':>6} {'Empty':>7} {'Failed':>7} {'Status':<12}",
        f"  {'baostock':<12} {stats['ok_bs']:>6} {stats['empty_bs']:>7} {stats['fail_bs']:>7} {'ON' if bs_avail else 'OFF':<12}",
        f"  {'akshare':<12} {stats['ok_ak']:>6} {stats['empty_ak']:>7} {stats['fail_ak']:>7} "
        f"{'ON' if ak_avail else 'OFF'}{' (consec fail: '+str(ak_consec_fail)+')' if ak_consec_fail > 0 else '':<12}",
        "-" * 72,
        f"  Total OK: {total_ok}  |  Success rate: {ok_rate:.1f}%  |  AK consec fails: {ak_consec_fail}",
        "=" * 72,
        "",
    ]
    log.info("\n".join(lines))


def main():
    log.info("=" * 60)
    log.info("SMART DOWNLOADER - A-share daily data (2020-01-01 ~ today)")
    log.info(f"Data dir:  {DATA_DIR}")
    log.info(f"Log dir:   {LOG_DIR}")
    log.info(f"Start:     {datetime.now().isoformat()}")
    log.info("=" * 60)

    # ── Step 1: Inventory ──────────────────────────────────
    all_codes   = generate_candidate_codes()
    downloaded  = get_downloaded_codes(DATA_DIR)
    remaining   = [c for c in all_codes if c not in downloaded]

    log.info(f"Candidate codes:      {len(all_codes):,}")
    log.info(f"Already downloaded:   {len(downloaded):,}")
    log.info(f"Remaining to process: {len(remaining):,}")
    log.info(f"Estimated real stocks: ~5,300 (most candidates are invalid codes)")

    if not remaining:
        log.info("Nothing to download! All codes already present.")
        return

    # ── Step 2: Source health checks ───────────────────────
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
            symbol="sz000001", start_date="20250102", end_date="20250103", adjust="qfq"
        )
        if test_df is not None and len(test_df) > 0:
            ak_available = True
            log.info("[HEALTH] akshare test OK (sz000001 returned data)")
        else:
            log.warning("[HEALTH] akshare test returned empty data")
    except Exception as e:
        log.warning(f"[HEALTH] akshare unavailable: {e}")

    if not bs_available and not ak_available:
        log.error("FATAL: Both sources unavailable. Exiting.")
        sys.exit(1)

    # ── Step 3: Determine source strategy ──────────────────
    if not ak_available:
        source_mode = "bs_only"
        log.info("MODE: BAOSTOCK-ONLY (akshare unavailable)")
    elif not bs_available:
        source_mode = "ak_only"
        log.info("MODE: AKSHARE-ONLY (baostock unavailable)")
    else:
        source_mode = "alternating"
        log.info(f"MODE: ALTERNATING (switch every {ALTERNATE_EVERY} codes)")
        log.info(f"  baostock interval: {BS_INTERVAL}s | akshare interval: {AK_INTERVAL}s")

    # ── Step 4: Download loop ──────────────────────────────
    stats = defaultdict(int)
    ak_consecutive_fails = 0
    bs_request_count = 0
    start_time = time.time()
    n = len(remaining)
    ak_disabled = not ak_available

    for i, symbol in enumerate(remaining):
        # ── Decide primary source ──
        if source_mode == "bs_only":
            primary = "bs"
        elif source_mode == "ak_only":
            primary = "ak"
        else:
            batch_num = i // ALTERNATE_EVERY
            primary = "bs" if batch_num % 2 == 0 else "ak"

        # If akshare was disabled mid-run due to consecutive failures, force bs
        if ak_disabled and primary == "ak":
            primary = "bs"

        fallback = "ak" if primary == "bs" else "bs"

        # ── Attempt primary ──
        success = False
        is_empty = False

        if primary == "bs" and bs_available:
            sym, rows, status = download_one_bs(symbol, DATA_DIR)
            bs_request_count += 1
            if status == "ok_bs":
                stats['ok_bs'] += 1
                success = True
            elif status == "skip_empty":
                stats['empty_bs'] += 1
                is_empty = True
            else:
                stats['fail_bs'] += 1
        elif primary == "ak" and ak_available and not ak_disabled:
            sym, rows, status = download_one_ak(symbol, DATA_DIR)
            if status == "ok_ak":
                stats['ok_ak'] += 1
                success = True
                ak_consecutive_fails = 0
            elif status == "skip_empty":
                stats['empty_ak'] += 1
                is_empty = True
            elif status.startswith("ak_netblock"):
                stats['fail_ak'] += 1
                ak_consecutive_fails += 1
                # Fast-disable on network block
                if ak_consecutive_fails >= AK_FAIL_THRESHOLD:
                    log.warning(f"AKShare disabled after {ak_consecutive_fails} consecutive failures (network block)")
                    ak_disabled = True
            else:
                stats['fail_ak'] += 1
                ak_consecutive_fails += 1
        else:
            # Primary not available, mark as failed for fallback
            stats[f'fail_{primary}'] += 1

        # ── Fallback if primary failed (and it wasn't just an empty stock) ──
        if not success and not is_empty:
            fallback_available = (fallback == "bs" and bs_available) or \
                                  (fallback == "ak" and ak_available and not ak_disabled)

            if fallback_available:
                if fallback == "bs":
                    sym2, rows2, status2 = download_one_bs(symbol, DATA_DIR)
                    bs_request_count += 1
                    if status2 == "ok_bs":
                        stats['ok_bs'] += 1
                        success = True
                    elif status2 == "skip_empty":
                        stats['empty_bs'] += 1
                        is_empty = True
                    else:
                        stats['fail_bs'] += 1
                else:  # fallback == "ak"
                    sym2, rows2, status2 = download_one_ak(symbol, DATA_DIR)
                    if status2 == "ok_ak":
                        stats['ok_ak'] += 1
                        success = True
                        ak_consecutive_fails = 0
                    elif status2 == "skip_empty":
                        stats['empty_ak'] += 1
                        is_empty = True
                    elif status2.startswith("ak_netblock"):
                        stats['fail_ak'] += 1
                        ak_consecutive_fails += 1
                    else:
                        stats['fail_ak'] += 1
                        ak_consecutive_fails += 1

        # ── Rate-limit delay ──
        if success:
            # Full delay for successful downloads
            if primary == "bs" or (not success and fallback == "bs"):
                delay = BS_INTERVAL + random.uniform(0, 0.3)
            else:
                delay = AK_INTERVAL + random.uniform(0, 0.15)
        elif is_empty:
            # Short delay for empty/invalid codes
            delay = 0.05 + random.uniform(0, 0.05)
        else:
            # Moderate delay for failures (source may be slow)
            delay = 0.3 + random.uniform(0, 0.2)

        time.sleep(delay)

        # Extra rest for akshare batches
        if primary == "ak" and (i + 1) % AK_BATCH_SIZE == 0:
            time.sleep(AK_BATCH_REST)

        # ── Periodic baostock re-login ──
        if bs_request_count > 0 and bs_request_count % BS_RELOGIN_EVERY == 0:
            try:
                bs.logout()
                time.sleep(1)
                lg = bs.login()
                if lg.error_code == '0':
                    log.info(f"[RELOGIN] baostock re-login OK at request #{bs_request_count}")
                else:
                    log.warning(f"[RELOGIN] baostock re-login failed: {lg.error_msg}")
            except Exception as e:
                log.warning(f"[RELOGIN] baostock re-login error: {e}")

        # ── Progress report ──
        if (i + 1) % PROGRESS_EVERY == 0:
            elapsed = time.time() - start_time
            print_progress_table(i, n, stats, elapsed, bs_available, ak_available, ak_consecutive_fails)

        # ── Disable akshare after threshold ──
        if not ak_disabled and ak_consecutive_fails >= AK_FAIL_THRESHOLD:
            log.warning(f"[DISABLE] AKShare disabled after {AK_FAIL_THRESHOLD} consecutive failures")
            ak_disabled = True

    # ── Step 5: Final report ───────────────────────────────
    if bs_available:
        try:
            bs.logout()
        except Exception:
            pass

    elapsed = time.time() - start_time
    final_downloaded = len(get_downloaded_codes(DATA_DIR))
    total_ok = stats['ok_bs'] + stats['ok_ak']
    total_empty = stats.get('empty_bs', 0) + stats.get('empty_ak', 0)
    total_fail = stats.get('fail_bs', 0) + stats.get('fail_ak', 0)

    log.info("")
    log.info("=" * 60)
    log.info("SMART DOWNLOADER - FINAL REPORT")
    log.info(f"Completed at: {datetime.now().isoformat()}")
    log.info(f"Total elapsed: {elapsed/60:.1f} min ({elapsed/3600:.2f} h)")
    log.info(f"Codes processed: {n:,}")
    log.info(f"  baostock OK:    {stats['ok_bs']:,}")
    log.info(f"  akshare OK:     {stats['ok_ak']:,}")
    log.info(f"  Empty (no data):{total_empty:,}")
    log.info(f"  Failed:         {total_fail:,}")
    log.info(f"Files on disk before: {len(downloaded):,}")
    log.info(f"Files on disk after:  {final_downloaded:,}")
    log.info(f"Net new files:        {final_downloaded - len(downloaded):,}")
    log.info(f"Success rate (of real stocks): {total_ok}/{total_ok+total_fail} "
             f"({100*total_ok/(total_ok+total_fail):.1f}%)" if (total_ok+total_fail) > 0 else "")
    log.info(f"Avg time per code: {elapsed/n:.2f}s")
    log.info("=" * 60)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
