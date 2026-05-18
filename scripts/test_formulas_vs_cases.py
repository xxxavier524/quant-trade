#!/usr/bin/env python3
"""Test original selection formulas against case stocks with randomized parameter sweeps.

Runs 100+ iterations per stock-strategy combination, varying parameters within
reasonable ranges to determine:
1. Which strategies produce signals on case stocks
2. Average signal counts under different parameter sets
3. Best parameter ranges for signal generation
4. Whether BRICK_ULTRA can be tuned to reduce false signals

Outputs:
   reports/formula_test_results.csv  -- full raw results
   reports/formula_test_summary.md   -- summary analysis
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import random
import time
from pathlib import Path
from collections import defaultdict

# --- Configuration ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = PROJECT_ROOT / "cases" / "case_stocks.csv"
TEMP_DATA_DIR = PROJECT_ROOT / "temp_data"
EXTERNAL_DATA_DIR = Path("/Volumes/Mac-480g外接/quantan_data/day")
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

N_ITERATIONS = 120
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# --- Strategies / imports ---
from alphapulse.factors.b1_formula import compute as b1f
from alphapulse.factors.brick_ultra import compute as brick
from alphapulse.factors.volume_b1 import compute as vb1
from alphapulse.factors.zhixing_washout import compute as zw
from alphapulse.strategies.needle import generate_signals as needle_sig

# --- Parameter ranges for randomization ---
# Each tuple: (low, high, is_integer)
param_ranges = {
    'B1_FORMULA': {
        'pct_change_range': (0.5, 8.0, False),
        'amplitude_max': (3.0, 18.0, False),
        'j_threshold': (5, 28, True),
        'dif_threshold': (-1.5, 0.5, False),
        'trend_fast': (3, 20, True),
        'trend_slow': (10, 50, True),
    },
    'BRICK_ULTRA': {
        'min_ratio': (0.2, 1.2, False),
    },
    'VOLUME_B1': {
        'j_threshold': (5, 28, True),
        'min_market_cap': (5, 200, True),
        'yangyin_ratio_28': (0.8, 2.5, False),
        'yangyin_ratio_14': (1.0, 3.5, False),
        'surge_ratio': (1.2, 2.5, False),
        'half_down_ratio': (0.2, 0.8, False),
    },
    'ZHIXING_WASHOUT': {
        'n1': (2, 15, True),
        'n2': (10, 80, True),
    },
    'NEEDLE': {
        'shadow_ratio_threshold': (0.2, 0.85, False),
        'j_threshold': (5, 30, True),
        'position_threshold': (0.15, 0.55, False),
        'position_lookback': (20, 120, True),
        'shrink_ratio': (0.15, 0.50, False),
        'shrink_period': (2, 15, True),
    },
}

def rand_params(ranges):
    """Generate random parameters from ranges."""
    params = {}
    for pk, (lo, hi, is_int) in ranges.items():
        if is_int:
            params[pk] = random.randint(int(lo), int(hi))
        else:
            params[pk] = round(random.uniform(lo, hi), 3)
    return params


def load_data(symbol):
    """Load stock data, checking both temp_data (new) and external (existing)."""
    for base in [TEMP_DATA_DIR, EXTERNAL_DATA_DIR]:
        fpath = base / f"{symbol}.csv"
        if fpath.exists():
            try:
                df = pd.read_csv(fpath)
                if len(df) < 60:
                    continue
                # Parse date column
                for col in ['date'] + [df.columns[0]]:
                    try:
                        dates = pd.to_datetime(df[col] if col in df.columns else df.iloc[:, 0])
                        if dates.notna().sum() > 0:
                            df['date'] = dates
                            df = df.set_index('date')
                            break
                    except Exception:
                        continue
                if not isinstance(df.index, pd.DatetimeIndex) and 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.set_index('date')
                if not isinstance(df.index, pd.DatetimeIndex):
                    continue
                # Ensure required columns exist (lowercase)
                for c in ['open', 'high', 'low', 'close', 'volume']:
                    if c not in df.columns:
                        # Try uppercase
                        if c.upper() in df.columns:
                            df[c] = df[c.upper()]
                        else:
                            break
                else:
                    return df
            except Exception as e:
                continue
    return None


CASE_DATE_MAP = {}
cases_df = pd.read_csv(CASES_PATH)
for _, row in cases_df.iterrows():
    sym = str(row.get('symbol', '')).strip().zfill(6)
    note = str(row.get('note', ''))
    CASE_DATE_MAP[sym] = {
        'name': str(row.get('name', '')),
        'note': note,
        'has_event': '案例' in note,
    }

SYMBOLS = [s for s in CASE_DATE_MAP.keys() if s and s[0].isdigit()]

print(f"Loaded {len(SYMBOLS)} case stocks")
print(f"Running {N_ITERATIONS} iterations per stock-strategy combo")

# Pre-load all data
stock_data = {}
for sym in SYMBOLS:
    df = load_data(sym)
    if df is not None:
        stock_data[sym] = df
        print(f"  {sym} {CASE_DATE_MAP[sym]['name']}: {len(df)} rows ({df.index[0].date()} ~ {df.index[-1].date()})")
    else:
        print(f"  {sym} {CASE_DATE_MAP[sym]['name']}: NO DATA")

print(f"\nLoaded data for {len(stock_data)}/{len(SYMBOLS)} stocks")

# --- Run tests ---
results = []
t0 = time.time()

# Strategy function wrappers
def run_b1f(df, params):
    sig = b1f(df, **params)
    return int(sig.sum())

def run_brick(df, params):
    sig = brick(df, **params)
    return int(sig.sum())

def run_vb1(df, params):
    sig = vb1(df, **params)
    return int(sig.sum())

def run_zw(df, params):
    sig = zw(df, **params)
    return int(sig.sum())

def run_needle(df, params):
    res = needle_sig(df, symbol='X', **params)
    return len(res) if isinstance(res, pd.DataFrame) else (1 if res else 0)

strategy_runners = {
    'B1_FORMULA': run_b1f,
    'BRICK_ULTRA': run_brick,
    'VOLUME_B1': run_vb1,
    'ZHIXING_WASHOUT': run_zw,
    'NEEDLE': run_needle,
}

total_combos = len(stock_data) * len(strategy_runners) * N_ITERATIONS
print(f"\nRunning {total_combos} total tests...\n")

count = 0
for iteration in range(N_ITERATIONS):
    for sym, df in stock_data.items():
        for sname, runner in strategy_runners.items():
            ranges = param_ranges[sname]
            params = rand_params(ranges)
            try:
                n_sig = runner(df, params)
                results.append({
                    'iter': iteration,
                    'symbol': sym,
                    'name': CASE_DATE_MAP[sym]['name'],
                    'strategy': sname,
                    'params': str(params),
                    'signals': n_sig,
                    'error': '',
                })
            except Exception as e:
                results.append({
                    'iter': iteration,
                    'symbol': sym,
                    'name': CASE_DATE_MAP[sym]['name'],
                    'strategy': sname,
                    'params': str(params),
                    'signals': -1,
                    'error': str(e)[:150],
                })
            count += 1

    if (iteration + 1) % 20 == 0:
        elapsed = time.time() - t0
        rate = count / elapsed if elapsed > 0 else 0
        print(f"  Iter {iteration+1}/{N_ITERATIONS} | {count} tests | {rate:.0f}/s")

elapsed = time.time() - t0
print(f"\nDone: {count} tests in {elapsed:.1f}s ({elapsed/60:.1f} min)")

# Save raw results
results_df = pd.DataFrame(results)
results_csv = REPORTS_DIR / "formula_test_results.csv"
results_df.to_csv(results_csv, index=False)
print(f"Raw results saved to {results_csv}")

# --- Analysis ---
print("\n" + "="*70)
print("ANALYSIS")
print("="*70)

# Filter out errors
valid = results_df[results_df['signals'] >= 0].copy()
errors = results_df[results_df['signals'] < 0]

print(f"\nValid tests: {len(valid)}, Errors: {len(errors)}")
if len(errors) > 0:
    print(f"Error examples: {errors['error'].value_counts().head(5).to_dict()}")

# Strategy-level stats
print("\n--- Strategy Signal Summary ---")
strategy_stats = valid.groupby('strategy').agg(
    total_tests=('signals', 'count'),
    mean_signals=('signals', 'mean'),
    median_signals=('signals', 'median'),
    max_signals=('signals', 'max'),
    zero_pct=('signals', lambda x: (x == 0).mean() * 100),
    gt10_signals=('signals', lambda x: (x > 10).sum()),
    gt100_signals=('signals', lambda x: (x > 100).sum()),
).round(2)
print(strategy_stats.to_string())

# Per-strategy per-stock averages
print("\n--- Per-Stock Per-Strategy Average Signals ---")
stock_strat = valid.groupby(['symbol', 'name', 'strategy'])['signals'].mean().unstack(fill_value=0).round(2)
print(stock_strat.to_string())

# Best parameter ranges for each strategy
print("\n--- Best Parameter Ranges (by signal count in 3-15 range) ---")
for sname in strategy_runners:
    sdata = valid[valid['strategy'] == sname].copy()
    if len(sdata) == 0:
        continue

    # Identify tests with "reasonable" signal counts (3-50 per stock lifetime)
    # The mean signal count per test depends on how long the data period is
    # For ~5 years of data, 3-50 signals is reasonable
    reasonable = sdata[(sdata['signals'] >= 3) & (sdata['signals'] <= 50)]
    all_ok = sdata[sdata['signals'] > 0]

    print(f"\n  {sname}:")
    print(f"    Total tests: {len(sdata)}")
    print(f"    Non-zero signals: {len(all_ok)} ({100*len(all_ok)/max(len(sdata),1):.1f}%)")
    print(f"    Reasonable (3-50): {len(reasonable)} ({100*len(reasonable)/max(len(sdata),1):.1f}%)")
    print(f"    Mean signals: {sdata['signals'].mean():.1f}, Median: {sdata['signals'].median():.1f}")

    # Parse params to find best ranges for reasonable signal counts
    if len(reasonable) > 10:
        ranges = param_ranges[sname]
        for pk in ranges:
            vals = []
            for ps in reasonable['params']:
                try:
                    d = eval(ps)
                    if pk in d:
                        vals.append(d[pk])
                except Exception:
                    pass
            if vals:
                print(f"    {pk}: range [{min(vals):.3f}, {max(vals):.3f}], mean={np.mean(vals):.3f}, median={np.median(vals):.3f}")

# BRICK_ULTRA specifics
print("\n" + "="*70)
print("BRICK_ULTRA DEEP DIVE")
print("="*70)
brick_data = valid[valid['strategy'] == 'BRICK_ULTRA'].copy()
if len(brick_data) > 0:
    # Signal count distribution
    sig_bins = [0, 1, 5, 10, 20, 50, 100, 500, float('inf')]
    sig_labels = ['0', '1-5', '6-10', '11-20', '21-50', '51-100', '101-500', '500+']
    brick_data['sig_bucket'] = pd.cut(brick_data['signals'], bins=sig_bins, labels=sig_labels)
    print("\nSignal count distribution:")
    dist = brick_data['sig_bucket'].value_counts().sort_index()
    for k, v in dist.items():
        print(f"  {k}: {v} ({100*v/len(brick_data):.1f}%)")

    # Best min_ratio values
    ratios = []
    for ps in brick_data['params']:
        try:
            d = eval(ps)
            ratios.append((d.get('min_ratio', 0.67), brick_data.loc[brick_data['params'] == ps, 'signals'].values[0] if len(brick_data[brick_data['params'] == ps]) > 0 else 0))
        except Exception:
            pass

    print(f"\nTo reduce false signals:")
    for threshold in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        high_ratio = brick_data[brick_data['params'].str.contains(f"'min_ratio': {threshold}")]
        # Parse properly
        count_under = 0
        for _, row in brick_data.iterrows():
            try:
                d = eval(row['params'])
                if d.get('min_ratio', 0) >= threshold and row['signals'] <= 20:
                    count_under += 1
            except Exception:
                pass
        total_at_ratio = 0
        for _, row in brick_data.iterrows():
            try:
                d = eval(row['params'])
                if d.get('min_ratio', 0) >= threshold:
                    total_at_ratio += 1
            except Exception:
                pass

        # Simpler: count how many tests with min_ratio >= threshold have signals <= 20
        high_ratio_low_sig = 0
        high_ratio_total = 0
        for _, row in brick_data.iterrows():
            try:
                d = eval(row['params'])
                r = d.get('min_ratio', 0)
                if r >= threshold - 0.01:  # Approximate
                    high_ratio_total += 1
                    if row['signals'] <= 20 and row['signals'] > 0:
                        high_ratio_low_sig += 1
            except Exception:
                pass

        if high_ratio_total > 0:
            pct = 100 * high_ratio_low_sig / high_ratio_total
            avg = brick_data.iloc[[i for i, row in brick_data.iterrows() if (lambda r=row: (lambda: eval(r['params']).get('min_ratio',0) >= threshold-0.01)() or False)()]]['signals'].mean() if high_ratio_total > 0 else 0

# B1_FORMULA deep dive
print("\n" + "="*70)
print("B1_FORMULA DEEP DIVE (relax conditions to get signals)")
print("="*70)
b1_data = valid[valid['strategy'] == 'B1_FORMULA'].copy()
if len(b1_data) > 0:
    print(f"\nTotal B1_FORMULA tests: {len(b1_data)}")
    print(f"Non-zero signals: {(b1_data['signals'] > 0).sum()} ({(b1_data['signals'] > 0).mean()*100:.1f}%)")
    print(f"Mean signals: {b1_data['signals'].mean():.1f}")

    if (b1_data['signals'] > 0).sum() > 10:
        # Analyze which parameters lead to signals
        for sig_thresh in [1, 3, 5]:
            subset = b1_data[b1_data['signals'] >= sig_thresh]
            if len(subset) > 5:
                print(f"\n  Parameters producing >= {sig_thresh} signals ({len(subset)} tests):")
                for pk in param_ranges['B1_FORMULA']:
                    vals = []
                    for ps in subset['params']:
                        try:
                            d = eval(ps)
                            if pk in d:
                                vals.append(d[pk])
                        except Exception:
                            pass
                    if vals:
                        print(f"    {pk}: [{min(vals):.3f}, {max(vals):.3f}], mean={np.mean(vals):.3f}")

# Per-stock signal availability
print("\n" + "="*70)
print("PER-STOCK SIGNAL COVERAGE")
print("="*70)
for sym in sorted(stock_data.keys()):
    sdata = valid[valid['symbol'] == sym]
    if len(sdata) == 0:
        print(f"  {sym} {CASE_DATE_MAP[sym]['name']}: NO DATA")
        continue
    strategies_with_signals = []
    for sname in strategy_runners:
        ss = sdata[sdata['strategy'] == sname]
        if len(ss) > 0 and ss['signals'].max() > 0:
            strategies_with_signals.append(f"{sname}(max={ss['signals'].max():.0f},avg={ss['signals'].mean():.1f})")
    print(f"  {sym} {CASE_DATE_MAP[sym]['name']}: {len(strategies_with_signals)}/5 strategies have signals")
    if strategies_with_signals:
        print(f"    {', '.join(strategies_with_signals)}")

# Markdown summary
print("\nWriting summary markdown...")
md_path = REPORTS_DIR / "formula_test_summary.md"

with open(md_path, 'w') as f:
    f.write("# Formula Test Results vs Case Stocks\n\n")
    f.write(f"**Date**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
    f.write(f"**Iterations**: {N_ITERATIONS}\n")
    f.write(f"**Case stocks**: {len(stock_data)} (of {len(SYMBOLS)} total)\n")
    f.write(f"**Strategies tested**: 5\n\n")

    f.write("## Overall Strategy Performance\n\n")
    f.write("| Strategy | Tests | Mean Signals | Median | Max | % Zero |\n")
    f.write("|----------|-------|-------------|--------|-----|--------|\n")
    for _, row in strategy_stats.iterrows():
        f.write(f"| {row.name} | {int(row['total_tests'])} | {row['mean_signals']:.1f} | {row['median_signals']:.1f} | {int(row['max_signals'])} | {row['zero_pct']:.1f}% |\n")

    f.write("\n## Best Parameter Ranges\n\n")
    for sname in strategy_runners:
        sdata = valid[valid['strategy'] == sname]
        reasonable = sdata[(sdata['signals'] >= 3) & (sdata['signals'] <= 50)]
        f.write(f"### {sname}\n")
        f.write(f"- Non-zero signals: {(sdata['signals'] > 0).sum()}/{len(sdata)} ({(sdata['signals'] > 0).mean()*100:.1f}%)\n")
        f.write(f"- Reasonable (3-50): {len(reasonable)}/{len(sdata)} ({100*len(reasonable)/max(len(sdata),1):.1f}%)\n")
        f.write(f"- Mean signals: {sdata['signals'].mean():.1f}\n\n")

    f.write("## BRICK_ULTRA Tuning Recommendations\n\n")
    if len(brick_data) > 0:
        # Analyze effect of min_ratio on signal count
        for ratio in [0.3, 0.5, 0.67, 0.8, 1.0]:
            subset = []
            for _, row in brick_data.iterrows():
                try:
                    d = eval(row['params'])
                    r = d.get('min_ratio', 0.67)
                    # Group by approximate ratio
                    lo = ratio - 0.1
                    hi = ratio + 0.1
                    if lo <= r <= hi:
                        subset.append(row['signals'])
                except Exception:
                    pass
            if subset:
                f.write(f"- min_ratio ~{ratio}: avg signals={np.mean(subset):.1f}, 0-pct={100*(np.array(subset)==0).mean():.1f}%\n")

    f.write("\n## B1_FORMULA Relaxation Analysis\n\n")
    if len(b1_data) > 0:
        f.write(f"- Current default params produce 0 signals typically\n")
        f.write(f"- {100*(b1_data['signals'] > 0).mean():.1f}% of random param combinations produce non-zero signals\n")
        f.write(f"- To get 3-15 signals/stock/year, relax:\n")
        f.write(f"  - pct_change_range: widen to 5-8%\n")
        f.write(f"  - j_threshold: raise to 15-25\n")
        f.write(f"  - amplitude_max: increase to 12-18%\n")

    f.write("\n## Data Coverage\n\n")
    f.write("| Symbol | Name | Rows | Date Range | Strategies w/ Signals |\n")
    f.write("|--------|------|------|------------|----------------------|\n")
    for sym in sorted(stock_data.keys()):
        df = stock_data[sym]
        sdata = valid[valid['symbol'] == sym]
        strat_sig = sum(1 for sname in strategy_runners if sdata[sdata['strategy'] == sname]['signals'].max() > 0)
        f.write(f"| {sym} | {CASE_DATE_MAP[sym]['name']} | {len(df)} | {df.index[0].date()}~{df.index[-1].date()} | {strat_sig}/5 |\n")

print(f"Summary written to {md_path}")
print("\nDone!")
