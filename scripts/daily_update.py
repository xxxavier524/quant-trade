#!/usr/bin/env python3
"""Daily incremental data update — appends only new trading days to existing CSVs.

Runs fast (~2 min for 5000 stocks) by fetching only last 5 trading days from baostock.
New stocks (no CSV yet) get full download.
"""

import sys, time, os
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import baostock as bs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = os.environ.get("ALPHAPULSE_DATA_DIR", "/Volumes/Mac-480g外接/quantan_data/day")

def fmt_date(dt):
    return dt.strftime("%Y-%m-%d")

def main():
    data_path = Path(DATA_DIR)
    data_path.mkdir(parents=True, exist_ok=True)

    bs.login()
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Daily update start. Data dir: {DATA_DIR}")

    existing = sorted(data_path.glob("*.csv"))
    # Generate all A-share codes
    codes = []
    for prefix in ("000", "001", "002", "003", "004"):
        for i in range(1, 1000):
            codes.append(f"{prefix}{i:03d}")
    for prefix in ("300", "301"):
        for i in range(1, 1000):
            codes.append(f"{prefix}{i:03d}")
    for prefix in ("600", "601", "603", "605"):
        for i in range(1, 1000):
            codes.append(f"{prefix}{i:03d}")
    for i in range(1, 1000):
        codes.append(f"688{i:03d}")
    for i in range(1, 1000):
        codes.append(f"920{i:03d}")

    existing_syms = {f.stem for f in existing}
    all_syms = set(codes)
    to_update = list(existing_syms)  # Update existing stocks
    new_stocks = list(all_syms - existing_syms)[:100]  # Download up to 100 new per day

    updated = 0
    new_added = 0
    skipped = 0

    # ── Update existing stocks: fetch last 5 trading days ──
    fetch_start = fmt_date(datetime.now() - timedelta(days=10))

    for i, sym in enumerate(to_update):
        code = f"sh.{sym}" if sym.startswith(('6','9')) else f"sz.{sym}"
        try:
            rs = bs.query_history_k_data_plus(
                code, 'date,open,high,low,close,volume,amount,turn',
                start_date=fetch_start, end_date=fmt_date(datetime.now()),
                frequency='d', adjustflag='2')
            new_rows = []
            while (rs.error_code == '0') & rs.next():
                row = rs.get_row_data()
                if row[0] and row[0] != '':
                    new_rows.append(row)

            if not new_rows:
                skipped += 1
                continue

            fpath = data_path / f"{sym}.csv"
            existing_df = pd.read_csv(fpath)
            new_df = pd.DataFrame(new_rows,
                columns=['date','open','high','low','close','volume','amount','turn'])
            new_df.columns = ['date','open','high','low','close','volume','amount','turnover']
            new_df['amount'] = pd.to_numeric(new_df['amount'], errors='coerce')
            new_df['turnover'] = pd.to_numeric(new_df['turnover'], errors='coerce')

            combined = pd.concat([existing_df, new_df]).drop_duplicates(subset=['date']).sort_values('date')
            combined.to_csv(fpath, index=False)
            updated += 1
        except Exception:
            skipped += 1

        if updated % 500 == 0 and updated > 0:
            print(f"  Existing updated: {updated}/{len(to_update)}...")
        time.sleep(0.15)

    # ── Download new stocks (full history) ──
    for i, sym in enumerate(new_stocks):
        code = f"sh.{sym}" if sym.startswith(('6','9')) else f"sz.{sym}"
        try:
            rs = bs.query_history_k_data_plus(
                code, 'date,open,high,low,close,volume,amount,turn',
                start_date='2020-01-01', end_date=fmt_date(datetime.now()),
                frequency='d', adjustflag='2')
            rows = []
            while (rs.error_code == '0') & rs.next():
                row = rs.get_row_data()
                if row[0] and row[0] != '':
                    rows.append(row)
            if len(rows) >= 60:
                df = pd.DataFrame(rows,
                    columns=['date','open','high','low','close','volume','amount','turn'])
                df.columns = ['date','open','high','low','close','volume','amount','turnover']
                df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
                df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce')
                df.to_csv(data_path / f"{sym}.csv", index=False)
                new_added += 1
        except Exception:
            pass
        if new_added % 20 == 0 and new_added > 0:
            print(f"  New stocks: {new_added}...")
        time.sleep(0.3)

    bs.logout()

    print(f"\n[{datetime.now():%Y-%m-%d %H:%M}] Daily update complete.")
    print(f"  Updated: {updated} existing")
    print(f"  New:     {new_added} new stocks")
    print(f"  Skipped: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
