#!/usr/bin/env python3
"""Case stock detection with EXACT dates — which strategy, when, how many times.
Output: console table + reports/case_detection_dates.json + .csv
"""

import sys, json
from pathlib import Path
from datetime import date
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_backtest import load_stocks
from alphapulse.strategies.b1_formula_strategy import generate_signals as b1
from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick
from alphapulse.strategies.needle_enhanced import generate_signals as needle
from alphapulse.strategies.b1_enhanced import generate_signals as b1_enh

from alphapulse.config.settings import DATA_DIR
PROJECT_ROOT = Path(__file__).resolve().parent.parent

STRATEGIES = {
    "B1_FORMULA": b1,
    "BRICK_ULTRA": brick,
    "NEEDLE_ENHANCED": needle,
    "B1_ENHANCED": b1_enh,
}

def main():
    print("=" * 80)
    print("  Case Stock Detection — Exact Signal Dates")
    print("=" * 80)

    cases = pd.read_csv(PROJECT_ROOT / "cases" / "case_stocks.csv")
    cases["symbol"] = cases["symbol"].astype(str).str.zfill(6)

    stocks = load_stocks(DATA_DIR, min_days=200)
    case_stocks = {s: stocks[s] for s in cases["symbol"] if s in stocks}
    missing = set(cases["symbol"]) - set(case_stocks.keys())

    print(f"\nCase stocks with data: {len(case_stocks)}")
    if missing:
        print(f"Missing: {sorted(missing)}")

    # Collect all signal dates
    all_results = {}  # symbol -> {strategy: [date_list]}

    for sym, data in sorted(case_stocks.items()):
        sym_results = {}
        for sname, sfn in STRATEGIES.items():
            try:
                sigs = sfn(data, symbol=sym)
                dates = list(sigs[sigs["signal"] == 1].index) if "signal" in sigs.columns else list(sigs.index)
                dates_str = sorted(set(str(d)[:10] for d in dates))
                sym_results[sname] = dates_str
            except Exception as e:
                sym_results[sname] = []
        all_results[sym] = sym_results

    # --- Per-case detail ---
    print(f"\n{'=' * 80}")
    print(f"  PER-CASE SIGNAL DATES")
    print(f"{'=' * 80}\n")

    date_records = []

    for sym in sorted(all_results.keys()):
        name = cases[cases["symbol"] == sym]["note"].values[0]
        name_str = str(name) if not (isinstance(name, float) and pd.isna(name)) else ""
        print(f"── {sym} {name_str} ──")

        total_signals = 0
        record = {"symbol": sym, "name": name_str}

        for sname in STRATEGIES:
            dates = all_results[sym][sname]
            n = len(dates)
            total_signals += n
            record[f"{sname}_count"] = n
            record[f"{sname}_first"] = dates[0] if dates else ""
            record[f"{sname}_last"] = dates[-1] if dates else ""
            record[f"{sname}_dates"] = ",".join(dates)

            if n > 0:
                # Show date ranges
                if n <= 10:
                    date_list = ", ".join(dates)
                else:
                    date_list = f"{dates[0]}, {dates[1]}, ..., {dates[-2]}, {dates[-1]} ({n} total)"
                print(f"  {sname:20s}: {n:3d} signals — {date_list}")
            else:
                print(f"  {sname:20s}: 0 signals")

        record["total_signals"] = total_signals
        date_records.append(record)
        print()

    # --- Summary table ---
    print(f"{'=' * 80}")
    print(f"  SUMMARY: Detection Coverage")
    print(f"{'=' * 80}")
    print(f"| Symbol | Name | B1 | Brick | Needle | B1_Enh | Total |")
    print(f"|--------|------|-----|-------|--------|--------|-------|")

    for sym in sorted(all_results.keys()):
        name = cases[cases["symbol"] == sym]["note"].values[0]
        name_str = str(name)[:10] if not (isinstance(name, float) and pd.isna(name)) else ""
        b1_n = len(all_results[sym]["B1_FORMULA"])
        br_n = len(all_results[sym]["BRICK_ULTRA"])
        nd_n = len(all_results[sym]["NEEDLE_ENHANCED"])
        be_n = len(all_results[sym]["B1_ENHANCED"])
        total = b1_n + br_n + nd_n + be_n
        print(f"| {sym} | {name_str:10s} | {b1_n:3d} | {br_n:3d} | {nd_n:3d} | {be_n:3d} | {total:3d} |")

    # --- Save results ---
    df = pd.DataFrame(date_records)
    csv_path = PROJECT_ROOT / "reports" / "case_detection_dates.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8")

    json_path = PROJECT_ROOT / "reports" / "case_detection_dates.json"
    with open(json_path, "w") as f:
        json.dump({
            "timestamp": date.today().isoformat(),
            "n_cases": len(case_stocks),
            "records": date_records,
        }, f, indent=2, default=str, ensure_ascii=False)

    print(f"\nSaved: {csv_path}")
    print(f"Saved: {json_path}")


if __name__ == "__main__":
    main()
