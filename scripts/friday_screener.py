#!/usr/bin/env python3
"""Friday stock screener — run all strategies on most recent data."""
import sys, json
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_backtest import load_stocks
from alphapulse.strategies.b1_formula_strategy import generate_signals as b1
from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick
from alphapulse.strategies.needle_enhanced import generate_signals as needle
from alphapulse.strategies.b1_enhanced import generate_signals as b1_enh
from alphapulse.strategies.b1_b2_b3_strategy import generate_signals as b1b2b3
from alphapulse.strategies.brick_three_types import generate_signals as brick_three
from alphapulse.strategies.needle_washout import generate_signals as needle_washout_sig
from alphapulse.utils.filters import (
    filter_universe, filter_signal, get_st_stocks, get_delisted_stocks,
    is_at_limit_up,
)

from alphapulse.config.settings import DATA_DIR
TARGET_DATE = "2026-05-22"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

STRATS = {
    "B1_FORMULA": b1,
    "BRICK_ULTRA": brick,
    "NEEDLE_ENHANCED": needle,
    "B1_ENHANCED": b1_enh,
    "B1_B2_B3": b1b2b3,
    "BRICK_THREE_TYPES": brick_three,
    "NEEDLE_WASHOUT": needle_washout_sig,
}

def main():
    print("=" * 70)
    print(f"  AlphaPulse-A 周五选股 ({TARGET_DATE})")
    print("=" * 70)

    print("\n[1] Loading stocks...")
    stocks = load_stocks(DATA_DIR, min_days=200)
    print(f"    Total: {len(stocks)} stocks")

    # Filter to stocks with recent data (Thu 5/21 or Fri 5/22)
    recent_stocks = {}
    for sym, df in stocks.items():
        latest = str(df.index[-1])[:10]
        if latest >= "2026-05-19":
            recent_stocks[sym] = df

    print(f"    With data >= 5/19: {len(recent_stocks)} stocks")

    # ── Pre-filters ──
    print("\n[2] Applying filters...")
    st_set = get_st_stocks()
    dl_set = get_delisted_stocks()

    # Hard filters: ST, delisted, limit-up (cannot trade)
    filtered_stocks = {}
    filter_stats = {"st": 0, "delisted": 0, "limit_up": 0, "ok": 0}
    for sym, data in recent_stocks.items():
        if sym in st_set:
            filter_stats["st"] += 1
            continue
        if sym in dl_set:
            filter_stats["delisted"] += 1
            continue
        if is_at_limit_up(data, sym):
            filter_stats["limit_up"] += 1
            continue
        filtered_stocks[sym] = data
        filter_stats["ok"] += 1

    print(f"    ST excluded: {filter_stats['st']}")
    print(f"    Delisted excluded: {filter_stats['delisted']}")
    print(f"    Limit-up excluded: {filter_stats['limit_up']}")
    print(f"    Passed filter: {filter_stats['ok']} stocks")

    print("\n[3] Running strategies...")
    all_picks = {}

    for sname, sfn in STRATS.items():
        picks = []
        for sym, data in sorted(filtered_stocks.items()):
            try:
                sigs = sfn(data, symbol=sym)
                if "signal" in sigs.columns:
                    buy_sigs = sigs[sigs["signal"] == 1]
                else:
                    buy_sigs = sigs
                if len(buy_sigs) > 0:
                    sig_dates = sorted(str(d)[:10] for d in buy_sigs.index)
                    latest_sig = sig_dates[-1]
                    n_sigs = len(sig_dates)
                    # Extract signal types (B1/B2/B3 or brick types)
                    sig_types = []
                    if "signal_type" in buy_sigs.columns:
                        sig_types = sorted(set(
                            str(t) for t in buy_sigs["signal_type"].dropna().unique()
                        ))
                    elif "brick_type" in buy_sigs.columns:
                        sig_types = sorted(set(
                            str(t) for t in buy_sigs["brick_type"].dropna().unique()
                        ))
                    picks.append((sym, latest_sig, n_sigs, sig_types))
            except Exception:
                pass
        picks.sort(key=lambda x: x[1], reverse=True)
        all_picks[sname] = picks
        print(f"    {sname}: {len(picks)} stocks with signals")

    # --- Friday signals specifically ---
    print(f"\n{'=' * 70}")
    print(f"  FRIDAY (5/21-5/22) SIGNALS")
    print(f"{'=' * 70}")

    for sname, picks in all_picks.items():
        recent = [(s, d, n, st) for s, d, n, st in picks if d >= "2026-05-21"]
        print(f"\n--- {sname}: {len(recent)} stocks ---")
        if recent:
            for sym, d, n, st in recent[:25]:
                st_str = f" types={','.join(st)}" if st else ""
                print(f"  {sym}  last={d}  total_signals={n}{st_str}")

    # --- Consensus ---
    print(f"\n{'=' * 70}")
    print(f"  CONSENSUS (2+ strategies, latest signal Thu-Fri)")
    print(f"{'=' * 70}")

    consensus = {}
    for sname, picks in all_picks.items():
        for sym, sig_date, n, sig_types in picks:
            if sig_date >= "2026-05-21":
                if sym not in consensus:
                    consensus[sym] = {"date": sig_date, "strats": [], "total": 0}
                consensus[sym]["strats"].append(sname)
                consensus[sym]["total"] += n

    multi = [(s, v) for s, v in consensus.items() if len(v["strats"]) >= 2]
    multi.sort(key=lambda x: -x[1]["total"])

    if multi:
        for sym, v in multi:
            print(f"  {sym}: {', '.join(v['strats'])} (last={v['date']}, total={v['total']})")
    else:
        print("  No consensus picks this week.")

    # --- Save ---
    out = {
        "target_date": TARGET_DATE,
        "n_stocks_screened": len(filtered_stocks),
        "n_before_filter": len(recent_stocks),
        "filter_stats": filter_stats,
        "strategies": {
            s: [{"symbol": x[0], "last_signal": x[1], "total_signals": x[2],
                 "signal_types": x[3]} for x in picks]
            for s, picks in all_picks.items()
        },
        "consensus": [{"symbol": s, "strategies": v["strats"], "last_signal": v["date"]}
                       for s, v in multi],
    }

    json_path = PROJECT_ROOT / "reports" / f"friday_screen_{TARGET_DATE}.json"
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nSaved: {json_path}")

    # --- Summary CSV ---
    rows = []
    for sname, picks in all_picks.items():
        for sym, d, n, st in picks:
            if d >= "2026-05-21":
                rows.append({
                    "strategy": sname, "symbol": sym,
                    "last_signal": d, "total_signals": n,
                    "signal_type": ",".join(st) if st else "",
                })
    if rows:
        csv_path = PROJECT_ROOT / "reports" / f"friday_picks_{TARGET_DATE}.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        print(f"Saved: {csv_path}")


if __name__ == "__main__":
    main()
