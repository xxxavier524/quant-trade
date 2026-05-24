#!/usr/bin/env python3
"""周五选股 (轻量版) — 只跑4个核心策略，快速出结果。"""
import sys, json
sys.path.insert(0, "")
from pathlib import Path
from scripts.run_backtest import load_stocks
from alphapulse.strategies.b1_b2_b3_strategy import generate_signals as b1b2b3
from alphapulse.strategies.brick_three_types import generate_signals as brick3
from alphapulse.strategies.needle_washout import generate_signals as nw
from alphapulse.strategies.b1_formula_strategy import generate_signals as b1
from alphapulse.utils.filters import get_st_stocks, get_delisted_stocks, is_at_limit_up

TARGET = "2026-05-22"
DATA_DIR = "/Volumes/Mac-480g外接/quantan_data/day"
PROJECT_ROOT = Path(".")

STRATS = {"B1_FORMULA": b1, "B1_B2_B3": b1b2b3, "BRICK_3": brick3, "NEEDLE_WASHOUT": nw}

def main():
    print(f"Fri screen {TARGET}")
    stocks = load_stocks(DATA_DIR, min_days=200)
    st_set = get_st_stocks(); dl_set = get_delisted_stocks()
    clean = {}
    for s,d in stocks.items():
        if s in st_set or s in dl_set or is_at_limit_up(d,s): continue
        if str(d.index[-1])[:10] >= "2026-05-19": clean[s] = d
    print(f"Clean: {len(clean)}")

    all_picks = {}
    for sname, fn in STRATS.items():
        picks = []
        for i, (sym, data) in enumerate(sorted(clean.items())):
            try:
                sigs = fn(data, symbol=sym)
                buy = sigs[sigs["signal"]==1] if "signal" in sigs.columns else sigs
                if len(buy) > 0:
                    dates = sorted(str(d)[:10] for d in buy.index)
                    sig_types = []
                    if "signal_type" in buy.columns: sig_types = list(buy["signal_type"].dropna().unique())
                    picks.append({"symbol":sym,"last":dates[-1],"n":len(dates),"types":sig_types})
            except: pass
        picks.sort(key=lambda x: x["last"], reverse=True)
        recent = [p for p in picks if p["last"] >= "2026-05-21"]
        print(f"{sname}: {len(picks)} total, {len(recent)} Thu-Fri")
        all_picks[sname] = picks

    # Consensus
    cons = {}
    for sname, picks in all_picks.items():
        for p in picks:
            if p["last"] >= "2026-05-21":
                cons.setdefault(p["symbol"],[]).append(sname)
    multi = {s:strats for s,strats in cons.items() if len(strats)>=2}
    print(f"\nConsensus (2+): {len(multi)} stocks")
    for sym, strats in sorted(multi.items(), key=lambda x:-len(x[1]))[:20]:
        print(f"  {sym}: {','.join(strats)}")

    # Save
    out = {"date":TARGET,"clean":len(clean),"strategies":all_picks,"consensus":list(multi.keys())}
    json_path = PROJECT_ROOT / "reports" / f"friday_screen_{TARGET}.json"
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2, default=str, ensure_ascii=False)

if __name__ == "__main__":
    main()
