#!/usr/bin/env python3
"""并行下载子进程 — 读取代码列表文件，逐只下载。"""
import sys, time, pandas as pd, baostock as bs
from pathlib import Path

code_file = sys.argv[1]
out_dir = sys.argv[2]

codes = [l.strip() for l in Path(code_file).read_text().strip().split('\n') if l.strip()]
total = len(codes)
ok = skip = empty = err = 0
t0 = time.time()

bs.login()
print(f'[{Path(code_file).stem}] START {total} codes')

for i, sym in enumerate(codes):
    target = Path(out_dir) / f'{sym}.csv'
    if target.exists() and target.stat().st_size > 1000:
        skip += 1
        continue

    bs_code = f'sh.{sym}' if sym[0] in '69' else f'sz.{sym}'
    try:
        rs = bs.query_history_k_data_plus(
            bs_code, 'date,open,high,low,close,volume,amount,turn',
            start_date='2020-01-01', end_date='2026-05-18',
            frequency='d', adjustflag='2')
        if rs.error_code != '0':
            err += 1; continue
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if len(rows) < 60:
            empty += 1; continue
        df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount','turn'])
        df = df[df['volume'].astype(float) > 0]
        for c in ['open','high','low','close','volume','amount']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df['date'] = pd.to_datetime(df['date'])
        df = df.dropna(subset=['open','close','volume'])
        if len(df) < 60:
            empty += 1; continue
        df.to_csv(target, index=False)
        ok += 1
    except Exception:
        err += 1

    time.sleep(0.1)

    if (i + 1) % 200 == 0:
        elapsed = time.time() - t0
        print(f'[{Path(code_file).stem}] {i+1}/{total} ok={ok} skip={skip} empty={empty} err={err}')

bs.logout()
elapsed = time.time() - t0
print(f'[{Path(code_file).stem}] DONE {elapsed:.0f}s ok={ok} skip={skip} empty={empty} err={err}')
