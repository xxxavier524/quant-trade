#!/usr/bin/env python3
"""BRICK_N_JUMP / BRICK_CONTINUATION 参数探索。

测试放宽参数后是否能触发这两个子类型信号。
在全量4660只中随机抽样500只进行参数网格测试。

参数网格：
- consol_lookback: [3, 5, 8]
- consol_max_amplitude: [10, 15, 20]
- require_consolidation: [True, False] (关闭横盘要求测试N_JUMP)
- pullback_depth_max: [0.08, 0.12, 0.15]

用法:
    cd /Users/qiushixuan/cc/quantan\ trade && source .venv/bin/activate
    python -W ignore -u scripts/grid_search_brick_types.py
"""

import sys
import json
import time
import random
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_backtest import load_stocks
from alphapulse.strategies.brick_three_types import generate_signals

from alphapulse.config.settings import DATA_DIR
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backtest_results"
BEST_PARAMS_FILE = Path(__file__).resolve().parent.parent / "config" / "best_params.json"

random.seed(42)
np.random.seed(42)


def main():
    print("=" * 80)
    print("BRICK_THREE_TYPES 参数探索 -- N_JUMP / CONTINUATION 触发分析")
    print("=" * 80)

    # --- 加载全量数据 ---
    print(f"[INFO] 加载数据: {DATA_DIR}")
    t0 = time.time()
    all_stocks = load_stocks(DATA_DIR, min_days=200)
    print(f"[INFO] 全量加载: {len(all_stocks)} 只股票 (耗时 {time.time()-t0:.1f}s)")

    # 随机抽样500只
    all_keys = list(all_stocks.keys())
    if len(all_keys) > 500:
        sample_keys = random.sample(all_keys, 500)
    else:
        sample_keys = all_keys
    samples = {k: all_stocks[k] for k in sample_keys}
    print(f"[INFO] 抽样: {len(samples)} 只")

    # --- 参数网格 ---
    consol_lookbacks = [3, 5, 8]
    consol_max_amplitudes = [10, 15, 20]
    require_consolidation_opts = [True, False]
    pullback_depth_maxs = [0.08, 0.12, 0.15]

    total = (len(consol_lookbacks) * len(consol_max_amplitudes)
             * len(require_consolidation_opts) * len(pullback_depth_maxs))
    print(f"\n[INFO] 参数组合总数: {total}")
    print(f"  consol_lookback: {consol_lookbacks}")
    print(f"  consol_max_amplitude: {consol_max_amplitudes}")
    print(f"  require_consolidation: {require_consolidation_opts}")
    print(f"  pullback_depth_max: {pullback_depth_maxs}")

    # --- 网格搜索 ---
    results = []
    n_done = 0
    t_start = time.time()

    for lookback in consol_lookbacks:
        for ampl in consol_max_amplitudes:
            for req_consol in require_consolidation_opts:
                for pullback_d in pullback_depth_maxs:
                    n_jump = n_cont = n_brk = 0
                    n_jump_sigs = n_cont_sigs = n_brk_sigs = 0
                    n_bull_bear_missing = 0  # 250日以下无法算黄线
                    n_too_short = 0            # <200日

                    for sym, data in samples.items():
                        if len(data) < 200:
                            n_too_short += 1
                            continue

                        try:
                            sigs = generate_signals(
                                data, symbol=sym,
                                consol_lookback=lookback,
                                consol_max_amplitude=ampl,
                                require_consolidation=req_consol,
                                pullback_depth_max=pullback_d,
                            )
                        except Exception:
                            continue

                        if len(sigs) > 0 and "brick_type" in sigs.columns:
                            bt = sigs["brick_type"]
                            has_jump = bool((bt == "BRICK_N_JUMP").any())
                            has_cont = bool((bt == "BRICK_CONTINUATION").any())
                            has_brk = bool((bt == "BRICK_BREAKOUT").any())
                            if has_jump:
                                n_jump += 1
                                n_jump_sigs += int((bt == "BRICK_N_JUMP").sum())
                            if has_cont:
                                n_cont += 1
                                n_cont_sigs += int((bt == "BRICK_CONTINUATION").sum())
                            if has_brk:
                                n_brk += 1
                                n_brk_sigs += int((bt == "BRICK_BREAKOUT").sum())

                    r = {
                        "consol_lookback": lookback,
                        "consol_max_amplitude": ampl,
                        "require_consolidation": req_consol,
                        "pullback_depth_max": pullback_d,
                        "stocks_with_n_jump": n_jump,
                        "n_jump_total_sigs": n_jump_sigs,
                        "stocks_with_continuation": n_cont,
                        "cont_total_sigs": n_cont_sigs,
                        "stocks_with_breakout": n_brk,
                        "breakout_total_sigs": n_brk_sigs,
                        "n_stocks_tested": len(samples) - n_too_short,
                    }
                    results.append(r)
                    n_done += 1

                    if n_done % 10 == 0:
                        elapsed = time.time() - t_start
                        best_nj = max(r2["stocks_with_n_jump"] for r2 in results)
                        best_nc = max(r2["stocks_with_continuation"] for r2 in results)
                        print(f"  ... {n_done}/{total} ({elapsed:.1f}s) "
                              f"best N_JUMP={best_nj} CONT={best_nc}")

    total_elapsed = time.time() - t_start
    print(f"\n[INFO] 参数探索完成，耗时 {total_elapsed:.1f}s")

    # --- 结果分析 ---
    print("\n" + "=" * 80)
    print("Part 1: N_JUMP 触发分析 (按 require_consolidation 分组)")
    print("=" * 80)

    for req_c in [True, False]:
        group = [r for r in results if r["require_consolidation"] == req_c]
        print(f"\n--- require_consolidation = {req_c} ---")
        hdr = f"{'lb':<5} {'amp':<6} {'pullD':<8} {'N_JUMP':<10} {'CONT':<10} {'BREAK':<10} {'JUMPsigs':<10} {'CONTsigs':<10}"
        print(hdr)
        print("-" * 80)
        for r in sorted(group, key=lambda x: x["stocks_with_n_jump"], reverse=True):
            print(
                f"{r['consol_lookback']:<5} {r['consol_max_amplitude']:<6} "
                f"{r['pullback_depth_max']:<8} "
                f"{r['stocks_with_n_jump']:<10} {r['stocks_with_continuation']:<10} "
                f"{r['stocks_with_breakout']:<10} "
                f"{r['n_jump_total_sigs']:<10} {r['cont_total_sigs']:<10}"
            )

    print("\n" + "=" * 80)
    print("Part 2: CONTINUATION 触发分析 (按 pullback_depth_max 分组)")
    print("=" * 80)

    for pd_max in pullback_depth_maxs:
        group = [r for r in results if r["pullback_depth_max"] == pd_max]
        avg_jump = np.mean([r["stocks_with_n_jump"] for r in group])
        avg_cont = np.mean([r["stocks_with_continuation"] for r in group])
        avg_brk = np.mean([r["stocks_with_breakout"] for r in group])
        max_jump = max(r["stocks_with_n_jump"] for r in group)
        max_cont = max(r["stocks_with_continuation"] for r in group)
        print(f"  pullback_depth_max={pd_max:.2f}: "
              f"N_JUMP avg={avg_jump:.1f} max={max_jump} | "
              f"CONT avg={avg_cont:.1f} max={max_cont} | "
              f"BREAK avg={avg_brk:.1f}")

    # --- 找出最佳触发参数 ---
    print("\n" + "=" * 80)
    print("Part 3: 最佳参数推荐")
    print("=" * 80)

    # N_JUMP best
    best_nj = max(results, key=lambda x: (x["stocks_with_n_jump"], x["n_jump_total_sigs"]))
    print(f"\n  N_JUMP 最佳触发:")
    print(f"    params: lookback={best_nj['consol_lookback']}, "
          f"amp={best_nj['consol_max_amplitude']}, "
          f"req_consol={best_nj['require_consolidation']}, "
          f"pullback_depth_max={best_nj['pullback_depth_max']}")
    print(f"    触发股票数: {best_nj['stocks_with_n_jump']}/{best_nj['n_stocks_tested']}")
    print(f"    信号总数: {best_nj['n_jump_total_sigs']}")

    # CONTINUATION best
    best_cont = max(results, key=lambda x: (x["stocks_with_continuation"], x["cont_total_sigs"]))
    print(f"\n  CONTINUATION 最佳触发:")
    print(f"    params: lookback={best_cont['consol_lookback']}, "
          f"amp={best_cont['consol_max_amplitude']}, "
          f"req_consol={best_cont['require_consolidation']}, "
          f"pullback_depth_max={best_cont['pullback_depth_max']}")
    print(f"    触发股票数: {best_cont['stocks_with_continuation']}/{best_cont['n_stocks_tested']}")
    print(f"    信号总数: {best_cont['cont_total_sigs']}")

    # BREAKOUT best
    best_brk = max(results, key=lambda x: (x["stocks_with_breakout"], x["breakout_total_sigs"]))
    print(f"\n  BREAKOUT 最佳触发:")
    print(f"    params: lookback={best_brk['consol_lookback']}, "
          f"amp={best_brk['consol_max_amplitude']}, "
          f"req_consol={best_brk['require_consolidation']}, "
          f"pullback_depth_max={best_brk['pullback_depth_max']}")
    print(f"    触发股票数: {best_brk['stocks_with_breakout']}/{best_brk['n_stocks_tested']}")
    print(f"    信号总数: {best_brk['breakout_total_sigs']}")

    # 找出同时有 N_JUMP 和 CONTINUATION 触发的 Pareto 最优组合
    print("\n--- Pareto 前沿 (N_JUMP + CONTINUATION 双高) ---")
    pareto = []
    for r in results:
        pareto.append((r, r["stocks_with_n_jump"] + r["stocks_with_continuation"]))
    pareto.sort(key=lambda x: x[1], reverse=True)
    for rank, (r, total_both) in enumerate(pareto[:8], 1):
        print(
            f"  #{rank} lb={r['consol_lookback']} amp={r['consol_max_amplitude']} "
            f"reqC={r['require_consolidation']} pullD={r['pullback_depth_max']} "
            f"=> N_JUMP={r['stocks_with_n_jump']} CONT={r['stocks_with_continuation']} "
            f"BREAK={r['stocks_with_breakout']} (total={total_both})"
        )

    # --- 保存结果 ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "brick_types_param_exploration.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[INFO] 结果已保存: {out_path}")

    # --- 更新 best_params.json ---
    # 使用 N_JUMP 和 CONTINUATION 都能触发的最佳参数
    best_combo = pareto[0][0]

    existing = {}
    if BEST_PARAMS_FILE.exists():
        try:
            with open(BEST_PARAMS_FILE, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    existing["BRICK_THREE_TYPES"] = {
        "consol_lookback": best_combo["consol_lookback"],
        "consol_max_amplitude": best_combo["consol_max_amplitude"],
        "require_consolidation": best_combo["require_consolidation"],
        "pullback_depth_max": best_combo["pullback_depth_max"],
        "stocks_with_n_jump": best_combo["stocks_with_n_jump"],
        "stocks_with_continuation": best_combo["stocks_with_continuation"],
        "stocks_with_breakout": best_combo["stocks_with_breakout"],
        "n_stocks_tested": best_combo["n_stocks_tested"],
    }

    with open(BEST_PARAMS_FILE, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    print(f"[INFO] 最佳参数已更新: {BEST_PARAMS_FILE}")

    print("\n" + "=" * 80)
    print("探索完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
