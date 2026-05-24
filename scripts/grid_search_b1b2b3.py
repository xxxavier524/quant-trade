#!/usr/bin/env python3
"""B1_B2_B3 参数网格搜索 -- 案例股命中率优化。

对45只案例股做参数网格搜索，找到命中率>80%且信号数合理的参数组合。

搜索参数：
- j_threshold: [13, 18, 23, 28] (KDJ J值阈值)
- pct_change_range: [3.0, 5.0, 7.0] (涨幅范围)
- vol_mult_b2: [1.5, 2.0, 3.0] (B2放量倍数)
- confidence权重组合: 无过滤 / 仅高置信度

评分: score = hit_rate * 0.6 + min(signals_per_stock, 5) * 0.4

用法:
    cd /Users/qiushixuan/cc/quantan\ trade && source .venv/bin/activate
    python -W ignore -u scripts/grid_search_b1b2b3.py
"""

import sys
import csv
import json
import time
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_backtest import load_stocks
from alphapulse.strategies.b1_b2_b3_strategy import generate_signals

# 案例股列表（来自 cases/case_stocks.csv）
CASE_FILE = Path(__file__).resolve().parent.parent / "cases" / "case_stocks.csv"
# 数据目录
DATA_DIR = "/Volumes/Mac-480g外接/quantan_data/day"
# 输出文件
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backtest_results"
BEST_PARAMS_FILE = Path(__file__).resolve().parent.parent / "config" / "best_params.json"


def load_case_stocks(path: Path) -> list[str]:
    """加载案例股代码列表。"""
    symbols = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row.get("symbol", "").strip()
            if sym:
                symbols.append(sym)
    return symbols


def run_single_combo(
    stocks: dict[str, pd.DataFrame],
    symbol_list: list[str],
    j_threshold: float,
    pct_change_range: float,
    vol_mult_b2: float,
    min_conf_b1: float,
    min_conf_b2: float,
    min_conf_b3: float,
) -> dict:
    """运行单一参数组合，统计命中率和信号数。

    Returns:
        dict: hit_rate, total_signals, signals_per_stock, score, detail
    """
    hit_count = 0
    total_signals = 0
    signal_counts = {}  # symbol -> count

    params = {
        "j_threshold": j_threshold,
        "pct_change_range": pct_change_range,
        "vol_mult_b2": vol_mult_b2,
        "min_conf_b1": min_conf_b1,
        "min_conf_b2": min_conf_b2,
        "min_conf_b3": min_conf_b3,
    }

    for sym in symbol_list:
        if sym not in stocks:
            continue
        data = stocks[sym]
        try:
            sigs = generate_signals(data, symbol=sym, **params)
            cnt = len(sigs)
            signal_counts[sym] = cnt
            total_signals += cnt
            if cnt > 0:
                hit_count += 1
        except Exception as e:
            signal_counts[sym] = 0

    n_stocks = len(symbol_list)
    hit_rate = hit_count / n_stocks if n_stocks > 0 else 0
    signals_per_stock = total_signals / n_stocks if n_stocks > 0 else 0

    # 评分: hit_rate * 0.6 + min(signals_per_stock, 5) * 0.4
    score = hit_rate * 0.6 + min(signals_per_stock, 5) * 0.4

    return {
        "params": params,
        "hit_count": hit_count,
        "total_signals": total_signals,
        "hit_rate": round(hit_rate, 4),
        "signals_per_stock": round(signals_per_stock, 2),
        "score": round(score, 4),
    }


def main():
    print("=" * 70)
    print("B1_B2_B3 参数网格搜索")
    print("=" * 70)

    # 加载案例股
    if not CASE_FILE.exists():
        print(f"[ERROR] 案例股文件不存在: {CASE_FILE}")
        return

    symbol_list = load_case_stocks(CASE_FILE)
    print(f"[INFO] 案例股: {len(symbol_list)} 只")
    print(f"[INFO] 代码: {symbol_list[:5]}... ({len(symbol_list)} total)")

    # 加载数据
    print(f"[INFO] 加载数据: {DATA_DIR}")
    t0 = time.time()
    stocks = load_stocks(DATA_DIR, symbols=symbol_list, min_days=200)
    print(f"[INFO] 加载了 {len(stocks)}/{len(symbol_list)} 只案例股 (耗时 {time.time()-t0:.1f}s)")

    missing = set(symbol_list) - set(stocks.keys())
    if missing:
        print(f"[WARN] 缺少数据的股票 ({len(missing)}): {sorted(missing)}")

    # 有效案例股
    valid_symbols = [s for s in symbol_list if s in stocks]
    print(f"[INFO] 有效案例股: {len(valid_symbols)} 只")

    # --- 参数网格 ---
    j_thresholds = [13, 18, 23, 28]
    pct_change_ranges = [3.0, 5.0, 7.0]
    vol_mult_b2s = [1.5, 2.0, 3.0]

    # Confidence weight 组合 (min_conf_b1, min_conf_b2, min_conf_b3)
    # - (0,0,0): 无过滤，所有信号都算
    # - (0.7,0,0): 仅高置信度B1 (>=0.8, 即排除仅有b1_formula=0.6的)
    # - (0.7,0.7,0): B1和B2都仅要高置信度
    conf_combos = [
        (0.0, 0.0, 0.0, "no_filter"),
        (0.7, 0.0, 0.0, "b1_high_only"),
        (0.0, 0.8, 0.0, "b2_high_only"),
    ]

    total_combos = (
        len(j_thresholds)
        * len(pct_change_ranges)
        * len(vol_mult_b2s)
        * len(conf_combos)
    )
    print(f"\n[INFO] 参数组合总数: {total_combos}")
    print(f"  j_threshold: {j_thresholds}")
    print(f"  pct_change_range: {pct_change_ranges}")
    print(f"  vol_mult_b2: {vol_mult_b2s}")
    print(f"  confidence combos: {[c[3] for c in conf_combos]}")

    # --- 网格搜索 ---
    results = []
    n_done = 0
    t_start = time.time()

    for j_thr in j_thresholds:
        for pct in pct_change_ranges:
            for vol_m in vol_mult_b2s:
                for conf_b1, conf_b2, conf_b3, conf_label in conf_combos:
                    r = run_single_combo(
                        stocks, valid_symbols,
                        j_threshold=j_thr,
                        pct_change_range=pct,
                        vol_mult_b2=vol_m,
                        min_conf_b1=conf_b1,
                        min_conf_b2=conf_b2,
                        min_conf_b3=conf_b3,
                    )
                    r["conf_label"] = conf_label
                    results.append(r)
                    n_done += 1

                    if n_done % 20 == 0:
                        elapsed = time.time() - t_start
                        print(f"  ... {n_done}/{total_combos} ({elapsed:.1f}s) "
                              f"| best score={max(r2['score'] for r2 in results):.4f}")

    total_elapsed = time.time() - t_start
    print(f"\n[INFO] 网格搜索完成，耗时 {total_elapsed:.1f}s")

    # --- 排序并输出Top5 ---
    results.sort(key=lambda x: x["score"], reverse=True)

    print("\n" + "=" * 70)
    print("Top 10 参数组合")
    print("=" * 70)
    header = (
        f"{'Rank':<5} {'Score':<8} {'HitRate':<9} {'#Signals':<9} "
        f"{'J_thr':<7} {'Pct%':<6} {'VolB2':<7} {'Conf':<15}"
    )
    print(header)
    print("-" * 70)

    for rank, r in enumerate(results[:10], 1):
        p = r["params"]
        conf_label = r.get("conf_label", "?")
        print(
            f"{rank:<5} {r['score']:<8.4f} {r['hit_rate']:<9.4f} "
            f"{r['total_signals']:<9} "
            f"{p['j_threshold']:<7} {p['pct_change_range']:<6} "
            f"{p['vol_mult_b2']:<7} {conf_label:<15}"
        )

    # --- 筛选命中率>80%的组合 ---
    high_hit = [r for r in results if r["hit_rate"] >= 0.80]
    print(f"\n[INFO] 命中率 >= 80% 的参数组合数: {len(high_hit)}")
    if high_hit:
        high_hit.sort(key=lambda x: x["score"], reverse=True)
        print("\n--- 命中率 >= 80% 的 Top 5 ---")
        for rank, r in enumerate(high_hit[:5], 1):
            p = r["params"]
            print(
                f"  #{rank} score={r['score']:.4f} hit={r['hit_rate']:.2%} "
                f"sigs={r['total_signals']} "
                f"j={p['j_threshold']} pct={p['pct_change_range']} "
                f"vol={p['vol_mult_b2']} conf={r.get('conf_label','?')}"
            )

    # --- 保存到 JSON ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "grid_search_b1b2b3.json"
    serializable = []
    for r in results:
        sr = {k: v for k, v in r.items()}
        sr["params"] = {k: v for k, v in sr["params"].items()}
        serializable.append(sr)

    with open(out_path, "w") as f:
        json.dump(serializable, f, indent=2)
    print(f"\n[INFO] 结果已保存: {out_path}")

    # --- 更新 best_params.json ---
    best = results[0]
    best_p = best["params"]
    best_params = {
        "B1_B2_B3": {
            "j_threshold": best_p["j_threshold"],
            "pct_change_range": best_p["pct_change_range"],
            "vol_mult_b2": best_p["vol_mult_b2"],
            "min_conf_b1": best_p["min_conf_b1"],
            "min_conf_b2": best_p["min_conf_b2"],
            "min_conf_b3": best_p["min_conf_b3"],
            "conf_label": best.get("conf_label", "?"),
            "score": best["score"],
            "hit_rate": best["hit_rate"],
            "total_signals": best["total_signals"],
        }
    }

    # 读取或创建 best_params.json (merge mode)
    existing = {}
    if BEST_PARAMS_FILE.exists():
        try:
            with open(BEST_PARAMS_FILE, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    existing.update(best_params)

    with open(BEST_PARAMS_FILE, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    print(f"[INFO] 最佳参数已更新: {BEST_PARAMS_FILE}")

    # --- 总结 ---
    print("\n" + "=" * 70)
    print("搜索总结")
    print("=" * 70)
    print(f"  参数组合总数: {total_combos}")
    print(f"  命中率>=80%的组合: {len(high_hit)}/{total_combos}")
    print(f"  最佳评分: {results[0]['score']:.4f}")
    print(f"  平均命中率: {sum(r['hit_rate'] for r in results)/len(results):.2%}")
    print(f"  平均信号数/股: {sum(r['signals_per_stock'] for r in results)/len(results):.2f}")


if __name__ == "__main__":
    main()
