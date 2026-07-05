#!/usr/bin/env python3
"""Backtest 46 case stocks with NEW strategies (v2).
Strategies: B1_B2_B3, BRICK_THREE_TYPES, NEEDLE_WASHOUT, B1_FORMULA (baseline).
Output: exact signal dates, per-type breakdown, JSON + CSV.
"""

import sys, json
from pathlib import Path
from datetime import date
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_backtest import load_stocks
from alphapulse.strategies.b1_b2_b3_strategy import generate_signals as b1b2b3
from alphapulse.strategies.brick_three_types import generate_signals as brick3
from alphapulse.strategies.needle_washout import generate_signals as nw
from alphapulse.strategies.b1_formula_strategy import generate_signals as b1

from alphapulse.config.settings import DATA_DIR
PROJECT_ROOT = Path(__file__).resolve().parent.parent

STRATEGIES = {
    "B1_B2_B3": (b1b2b3, "signal_type"),
    "BRICK_THREE_TYPES": (brick3, "brick_type"),
    "NEEDLE_WASHOUT": (nw, None),
    "B1_FORMULA": (b1, None),
}

TYPE_KEYS = {
    "B1_B2_B3": "signal_type",
    "BRICK_THREE_TYPES": "brick_type",
}


def load_cases():
    cases_path = PROJECT_ROOT / "cases" / "case_stocks.csv"
    df = pd.read_csv(cases_path)
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    return df


def date_str(d):
    """Convert Timestamp or date-like to YYYY-MM-DD string."""
    return str(pd.Timestamp(d).date())


def main():
    print("=" * 75)
    print("  Case Stock Detection v2 — NEW Strategy Suite")
    print("=" * 75)

    # --- Load cases ---
    cases = load_cases()
    case_map = dict(zip(cases["symbol"], cases["name"]))
    print(f"\n[1] Case stocks: {len(cases)}")

    # --- Load data ---
    print(f"[2] Loading data from {DATA_DIR} ...")
    all_stocks = load_stocks(DATA_DIR, min_days=200)
    case_symbols = set(cases["symbol"])
    case_stocks = {s: all_stocks[s] for s in case_symbols if s in all_stocks}
    missing = case_symbols - set(case_stocks.keys())
    print(f"    Available: {len(all_stocks)} stocks total")
    print(f"    Case stocks with data: {len(case_stocks)} / {len(cases)}")
    if missing:
        print(f"    Missing data: {sorted(missing)}")

    if len(case_stocks) == 0:
        print("[ERROR] No case stock data available")
        return

    # --- Run all strategies ---
    print(f"\n[3] Running {len(STRATEGIES)} strategies on {len(case_stocks)} case stocks...")
    print()

    results = {}           # symbol -> {strategy_name: {...}}
    all_detections = {}    # strategy_name -> list of (symbol, ...)

    for sym in sorted(case_stocks.keys()):
        data = case_stocks[sym]
        name = case_map.get(sym, "")
        sym_results = {}

        print(f"=== {sym} ({name}) ===")

        for sname, (sfn, type_col) in STRATEGIES.items():
            try:
                sigs = sfn(data, symbol=sym)
                if sigs.empty or len(sigs) == 0:
                    sym_results[sname] = {
                        "count": 0,
                        "first": None,
                        "last": None,
                        "dates": [],
                        "breakdown": {},
                    }
                    print(f"  {sname}: 0 signals")
                    continue

                # Extract dates (index)
                dates = list(sigs.index)
                dates_sorted = sorted(dates)
                dates_str = [date_str(d) for d in dates_sorted]

                record = {
                    "count": len(dates_sorted),
                    "first": dates_str[0],
                    "last": dates_str[-1],
                    "dates": dates_str,
                    "breakdown": {},
                }

                # Type breakdown if applicable
                if type_col and type_col in sigs.columns:
                    type_counts = sigs[type_col].value_counts().to_dict()
                    record["breakdown"] = {
                        str(k): int(v) for k, v in type_counts.items()
                    }
                    breakdown_parts = ", ".join(
                        f"{k}={v}" for k, v in sorted(record["breakdown"].items())
                    )
                    print(f"  {sname}: {len(dates_sorted)} signals "
                          f"— first={dates_str[0]}, last={dates_str[-1]}")
                    print(f"    {breakdown_parts}")
                else:
                    print(f"  {sname}: {len(dates_sorted)} signals "
                          f"— first={dates_str[0]}, last={dates_str[-1]}")

                sym_results[sname] = record

            except Exception as e:
                print(f"  {sname}: ERROR — {e}")
                sym_results[sname] = {
                    "count": 0,
                    "first": None,
                    "last": None,
                    "dates": [],
                    "breakdown": {},
                    "error": str(e),
                }

        results[sym] = sym_results
        print()

    # --- Summary table ---
    n_cases = len(case_stocks)
    print("=" * 75)
    print("  SUMMARY")
    print("=" * 75)
    print()
    print(f"| {'Strategy':<24s} | {'Hit':>6s} | {'Rate':>8s} |")
    print(f"|{'-'*26}|{'-'*8}|{'-'*10}|")

    strategy_hits = {}
    for sname in STRATEGIES:
        hit_count = sum(
            1 for sym in case_stocks
            if results.get(sym, {}).get(sname, {}).get("count", 0) > 0
        )
        hit_rate = hit_count / n_cases * 100 if n_cases > 0 else 0
        strategy_hits[sname] = (hit_count, hit_rate)
        print(f"| {sname:<24s} | {hit_count:>3d}/{n_cases:<3d} | {hit_rate:>6.1f}% |")

    print()

    # --- Every-case detail table ---
    print(f"{'=' * 75}")
    print(f"  PER-CASE DETAIL")
    print(f"{'=' * 75}")
    print(f"| Symbol   | Name        | {'B1_B2_B3':>9s} | {'BRICK_3':>7s} | {'NEEDLE':>6s} | {'B1_FORMULA':>10s} |")
    print(f"|----------|-------------|-----------|---------|--------|------------|")

    csv_rows = []
    for sym in sorted(case_stocks.keys()):
        name = case_map.get(sym, "")
        bb = results.get(sym, {}).get("B1_B2_B3", {}).get("count", 0)
        br = results.get(sym, {}).get("BRICK_THREE_TYPES", {}).get("count", 0)
        nw_count = results.get(sym, {}).get("NEEDLE_WASHOUT", {}).get("count", 0)
        b1f = results.get(sym, {}).get("B1_FORMULA", {}).get("count", 0)
        print(f"| {sym:<8s} | {str(name)[:11]:<11s} | {bb:>4d}      | {br:>4d}   | {nw_count:>4d}  | {b1f:>5d}       |")

        # Build CSV row
        csv_row = {
            "symbol": sym,
            "name": name,
            "B1_B2_B3_count": bb,
            "B1_B2_B3_first": results.get(sym, {}).get("B1_B2_B3", {}).get("first", ""),
            "B1_B2_B3_last": results.get(sym, {}).get("B1_B2_B3", {}).get("last", ""),
            "B1_B2_B3_dates": ";".join(results.get(sym, {}).get("B1_B2_B3", {}).get("dates", [])),
            "BRICK_THREE_TYPES_count": br,
            "BRICK_THREE_TYPES_first": results.get(sym, {}).get("BRICK_THREE_TYPES", {}).get("first", ""),
            "BRICK_THREE_TYPES_last": results.get(sym, {}).get("BRICK_THREE_TYPES", {}).get("last", ""),
            "NEEDLE_WASHOUT_count": nw_count,
            "NEEDLE_WASHOUT_first": results.get(sym, {}).get("NEEDLE_WASHOUT", {}).get("first", ""),
            "NEEDLE_WASHOUT_last": results.get(sym, {}).get("NEEDLE_WASHOUT", {}).get("last", ""),
            "B1_FORMULA_count": b1f,
            "B1_FORMULA_first": results.get(sym, {}).get("B1_FORMULA", {}).get("first", ""),
            "B1_FORMULA_last": results.get(sym, {}).get("B1_FORMULA", {}).get("last", ""),
        }
        csv_rows.append(csv_row)

    print()

    # --- Save ---
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)

    # JSON
    json_out = {
        "timestamp": date.today().isoformat(),
        "n_cases_input": len(cases),
        "n_cases_with_data": n_cases,
        "missing_data": sorted(list(missing)) if missing else [],
        "strategies": list(STRATEGIES.keys()),
        "summary": {
            sname: {
                "hit": hit_count,
                "total": n_cases,
                "rate": round(rate, 1),
            }
            for sname, (hit_count, rate) in strategy_hits.items()
        },
        "results": {
            sym: {
                sname: {
                    "count": rec["count"],
                    "first": rec["first"],
                    "last": rec["last"],
                    "dates": rec["dates"],
                    "breakdown": rec.get("breakdown", {}),
                }
                for sname, rec in symr.items()
            }
            for sym, symr in results.items()
        },
    }
    json_path = reports_dir / "case_detection_v2.json"
    with open(json_path, "w") as f:
        json.dump(json_out, f, indent=2, default=str, ensure_ascii=False)
    print(f"Saved JSON: {json_path}")

    # CSV
    csv_df = pd.DataFrame(csv_rows)
    csv_path = reports_dir / "case_detection_v2.csv"
    csv_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"Saved CSV:  {csv_path}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
