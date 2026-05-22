#!/usr/bin/env python3
"""Backtest case stocks: run all strategies against 46 case stocks.
Report which cases detected, when, and by which strategy.
"""

import sys, json
from pathlib import Path
from datetime import date
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_backtest import load_stocks, BacktestEngine
from alphapulse.strategies.b1_formula_strategy import generate_signals as b1_sig
from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick_sig
from alphapulse.strategies.needle_enhanced import generate_signals as needle_sig
from alphapulse.strategies.two_stage_selection import generate_signals as two_stage_sig
from alphapulse.strategies.b1_enhanced import generate_signals as b1_enhanced_sig
from alphapulse.strategies.b1_super import generate_signals as b1_super_sig

DATA_DIR = "/Volumes/Mac-480g外接/quantan_data/day"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

STRATEGIES = {
    "B1_FORMULA": b1_sig,
    "BRICK_ULTRA": brick_sig,
    "NEEDLE_ENHANCED": needle_sig,
    "B1_ENHANCED": b1_enhanced_sig,
    "B1_SUPER": b1_super_sig,
}

def load_cases():
    cases_path = PROJECT_ROOT / "cases" / "case_stocks.csv"
    df = pd.read_csv(cases_path)
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    return df

def main():
    print("=" * 70)
    print("Case Stock Detection Backtest")
    print("=" * 70)

    # Load case list
    cases = load_cases()
    case_symbols = set(cases["symbol"].tolist())
    print(f"\n[1] Case stocks: {len(case_symbols)}")

    # Load all data
    print(f"[2] Loading data...")
    all_stocks = load_stocks(DATA_DIR, min_days=200)
    print(f"    Available: {len(all_stocks)} stocks")

    # Filter to case stocks
    case_stocks = {s: all_stocks[s] for s in case_symbols if s in all_stocks}
    missing = case_symbols - set(case_stocks.keys())
    print(f"    Case stocks with data: {len(case_stocks)}")
    if missing:
        print(f"    Missing: {sorted(missing)}")

    if len(case_stocks) == 0:
        print("[ERROR] No case stock data available")
        return

    # Run each strategy
    print(f"\n[3] Running {len(STRATEGIES)} strategies on {len(case_stocks)} case stocks...")

    all_detections = {}  # strategy -> list of (symbol, date_range, signal_count)

    for strat_name, strat_fn in STRATEGIES.items():
        print(f"\n  --- {strat_name} ---")
        detections = []
        for sym, data in sorted(case_stocks.items()):
            try:
                sigs = strat_fn(data, symbol=sym)
                n_sigs = len(sigs[sigs["signal"] == 1]) if "signal" in sigs.columns else len(sigs)
                if n_sigs > 0:
                    if "date" in sigs.columns:
                        sig_dates = sigs[sigs["signal"] == 1]["date"].tolist() if "signal" in sigs.columns else sigs.index.tolist()
                        first_date = str(sig_dates[0])[:10]
                        last_date = str(sig_dates[-1])[:10]
                    else:
                        first_date = str(sigs.index[0])[:10]
                        last_date = str(sigs.index[-1])[:10]
                    detections.append({
                        "symbol": sym,
                        "name": cases[cases["symbol"] == sym]["note"].values[0] if sym in cases["symbol"].values else "",
                        "signals": n_sigs,
                        "first": first_date,
                        "last": last_date,
                    })
                    print(f"    {sym}: {n_sigs} signals ({first_date} -> {last_date})")
            except Exception as e:
                pass

        all_detections[strat_name] = detections
        detected_syms = set(d["symbol"] for d in detections)
        print(f"    Detected: {len(detected_syms)}/{len(case_stocks)} cases")

    # --- Summary ---
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: Case Stock Detection Rates")
    print(f"{'=' * 70}")

    # Per-strategy summary
    print(f"\n| Strategy | Detected | Total | Rate | Avg Signals |")
    print(f"|----------|----------|-------|------|-------------|")
    for sname, dets in all_detections.items():
        detected = len(set(d["symbol"] for d in dets))
        rate = detected / len(case_stocks) * 100
        avg_sig = np.mean([d["signals"] for d in dets]) if dets else 0
        print(f"| {sname} | {detected} | {len(case_stocks)} | {rate:.1f}% | {avg_sig:.1f} |")

    # All strategies combined detection
    all_detected = set()
    for dets in all_detections.values():
        all_detected.update(d["symbol"] for d in dets)
    print(f"\n**Combined (any strategy)**: {len(all_detected)}/{len(case_stocks)} ({len(all_detected)/len(case_stocks)*100:.1f}%)")

    # Per-case detail table
    print(f"\n{'=' * 70}")
    print(f"PER-CASE DETAIL")
    print(f"{'=' * 70}")
    print(f"| Symbol | Name | B1_FORMULA | BRICK | NEEDLE | B1_ENH | B1_SUPER | Total |")
    print(f"|--------|------|------------|-------|--------|--------|---------|-------|")

    case_scores = []
    for sym in sorted(case_stocks.keys()):
        name_val = cases[cases["symbol"] == sym]["note"].values[0] if sym in cases["symbol"].values else ""
        name_str = str(name_val) if not isinstance(name_val, float) or not np.isnan(name_val) else ""
        counts = {}
        for sname, dets in all_detections.items():
            d = [x for x in dets if x["symbol"] == sym]
            counts[sname] = d[0]["signals"] if d else 0
        total = sum(counts.values())
        case_scores.append({"symbol": sym, "name": name_str, "total": total, **counts})
        b1 = "✓" if counts["B1_FORMULA"] > 0 else "-"
        br = "✓" if counts["BRICK_ULTRA"] > 0 else "-"
        nd = "✓" if counts["NEEDLE_ENHANCED"] > 0 else "-"
        be = "✓" if counts["B1_ENHANCED"] > 0 else "-"
        bs = "✓" if counts["B1_SUPER"] > 0 else "-"
        print(f"| {sym} | {name_str[:12]} | {b1} | {br} | {nd} | {be} | {bs} | {total} |")

    # Top detected cases
    case_scores.sort(key=lambda x: -x["total"])
    print(f"\n**Top detected cases:**")
    for c in case_scores[:10]:
        print(f"  {c['symbol']} ({c['name'][:10]}): {c['total']} total signals across strategies")

    # Undetected cases
    undetected = [c for c in case_scores if c["total"] == 0]
    if undetected:
        print(f"\n**Undetected cases ({len(undetected)}):**")
        for c in undetected:
            print(f"  {c['symbol']} ({c['name'][:15]})")
    else:
        print(f"\n**All cases detected by at least one strategy!**")

    # Save results
    out = {
        "timestamp": date.today().isoformat(),
        "n_cases": len(case_stocks),
        "missing_data": sorted(missing) if missing else [],
        "combined_detection_rate": round(len(all_detected) / len(case_stocks) * 100, 1),
        "per_strategy": {
            s: {
                "detected": len(set(d["symbol"] for d in dets)),
                "rate": round(len(set(d["symbol"] for d in dets)) / len(case_stocks) * 100, 1),
            }
            for s, dets in all_detections.items()
        },
        "per_case": case_scores,
        "undetected": [c["symbol"] for c in case_scores if c["total"] == 0],
    }

    out_path = PROJECT_ROOT / "reports" / "case_detection_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nResults saved: {out_path}")


if __name__ == "__main__":
    main()
