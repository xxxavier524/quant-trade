#!/usr/bin/env python3
"""Thursday (2026-05-21) stock screener with hard filters."""
import sys, json
sys.path.insert(0, '.')
from scripts.run_backtest import load_stocks
from alphapulse.strategies.b1_formula_strategy import generate_signals as b1
from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick
from alphapulse.strategies.b1_enhanced import generate_signals as b1_enh
from alphapulse.utils.filters import get_st_stocks, get_delisted_stocks, is_at_limit_up

TARGET = "2026-05-21"

print("Loading data...")
from alphapulse.config.settings import DATA_DIR
stocks = load_stocks(DATA_DIR, min_days=200)
print(f"Loaded {len(stocks)} stocks")

thu = {s: d for s, d in stocks.items() if str(d.index[-1])[:10] >= TARGET}
print(f"With Thu data: {len(thu)}")

st_set = get_st_stocks()
dl_set = get_delisted_stocks()
clean = {}
st_n = dl_n = lu_n = 0
for sym, data in thu.items():
    if sym in st_set: st_n += 1; continue
    if sym in dl_set: dl_n += 1; continue
    if is_at_limit_up(data, sym): lu_n += 1; continue
    clean[sym] = data
print(f"ST:{st_n} DL:{dl_n} LimitUp:{lu_n} -> Clean:{len(clean)}")

all_picks = {}
for sname, sfn in [("B1_FORMULA", b1), ("BRICK_ULTRA", brick), ("B1_ENHANCED", b1_enh)]:
    picks = []
    for sym, data in clean.items():
        try:
            sigs = sfn(data, symbol=sym)
            buy = sigs[sigs["signal"] == 1] if "signal" in sigs.columns else sigs
            thu_dates = [d for d in buy.index if str(d)[:10] == TARGET]
            if thu_dates:
                picks.append((sym, len(buy)))
        except: pass
    picks.sort(key=lambda x: -x[1])
    all_picks[sname] = picks
    print(f"{sname}: {len(picks)} on {TARGET}")

# Consensus
print(f"\n=== CONSENSUS (2+ strategies, {TARGET}) ===")
consensus = {}
for sname, picks in all_picks.items():
    for sym, n in picks:
        consensus.setdefault(sym, []).append(sname)

ranked = sorted(consensus.items(), key=lambda x: -len(x[1]))
for sym, strats in ranked:
    n = len(strats)
    if n >= 2:
        print(f"  {'⭐'*n} {sym}: {', '.join(strats)}")

# B1-only
b1_syms = set(s for s, _ in all_picks["B1_FORMULA"])
cons_syms = set(s for s, v in consensus.items() if len(v) >= 2)
b1_only = b1_syms - cons_syms
if b1_only:
    print(f"\n--- B1 only ({len(b1_only)}) ---")
    for sym in sorted(b1_only)[:20]:
        print(f"  {sym}")

n_cons = sum(1 for _, v in consensus.items() if len(v) >= 2)
print(f"\n=== Summary ===")
print(f"Thu {TARGET}: {len(thu)} initial -> {len(clean)} filtered -> {len(all_picks['B1_FORMULA'])} B1 -> {n_cons} consensus")
