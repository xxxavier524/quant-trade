#!/usr/bin/env python3
"""B1_B2_B3 参数网格搜索 -- 案例股命中率优化 (v2 细化评分)。

对45只案例股做参数网格搜索，找到命中率>80%且信号数合理的参数组合。

搜索参数：
- j_threshold: [13, 18, 23, 28] (KDJ J值阈值)
- pct_change_range: [3.0, 5.0, 7.0] (涨幅范围)
- vol_mult_b2: [1.5, 2.0, 3.0] (B2放量倍数)
- confidence权重组合: 无过滤 / 仅高置信度

综合评分（v2 多维）:
  score = hit_rate * 0.35
        + min(b2b3_ratio, 0.6) / 0.6 * 0.25   (B2+B3确认率)
        + (1 - min(sigs_per_stock_per_year / 10, 0.9)) * 0.25  (信号密度反比)
        + stability * 0.15                      (信号分布稳定性)

用法:
    cd /Users/qiushixuan/cc/quantan\ trade && source .venv/bin/activate
    python -W ignore -u scripts/grid_search_b1b2b3.py
"""

import sys
import csv
import json
import time
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_backtest import load_stocks
from alphapulse.strategies.b1_b2_b3_strategy import generate_signals

CASE_FILE = Path(__file__).resolve().parent.parent / "cases" / "case_stocks.csv"
from alphapulse.config.settings import DATA_DIR
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backtest_results"
BEST_PARAMS_FILE = Path(__file__).resolve().parent.parent / "config" / "best_params.json"


def load_case_stocks(path: Path) -> list[str]:
    symbols = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("symbol", "").strip():
                symbols.append(row["symbol"].strip())
    return symbols


def run_single_combo(
    stocks: dict,
    symbol_list: list[str],
    j_threshold: float,
    pct_change_range: float,
    vol_mult_b2: float,
    min_conf_b1: float,
    min_conf_b2: float,
    min_conf_b3: float,
) -> dict:
    """运行单一参数组合，统计 B1/B2/B3 各类信号数。

    Returns:
        dict with: hit_rate, total_signals, b1_cnt, b2_cnt, b3_cnt,
                   signals_per_stock_per_year, b2b3_ratio, score, per_stock_detail
    """
    hit_count = 0
    b1_cnt = b2_cnt = b3_cnt = 0
    per_stock_signals = {}
    total_data_days = 0  # sum of data length across all stocks (for per-year normalization)

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
            per_stock_signals[sym] = cnt
            total_data_days += len(data)
            if cnt > 0:
                hit_count += 1
                # 按 signal_type 分别计数
                if "signal_type" in sigs.columns:
                    st = sigs["signal_type"]
                    b1_cnt += int((st == "B1").sum())
                    b2_cnt += int((st == "B2").sum())
                    b3_cnt += int((st == "B3").sum())
                else:
                    b1_cnt += cnt
        except Exception:
            per_stock_signals[sym] = 0

    n_stocks = len(symbol_list)
    total_signals = b1_cnt + b2_cnt + b3_cnt
    hit_rate = hit_count / n_stocks if n_stocks > 0 else 0

    # 平均每只股票每年信号数 (用年均交易日252天归一化)
    avg_data_years = total_data_days / n_stocks / 252 if n_stocks > 0 else 1
    signals_per_stock_per_year = (total_signals / n_stocks / avg_data_years) if n_stocks > 0 and avg_data_years > 0 else 0

    # B2+B3 占比
    b2b3_ratio = (b2_cnt + b3_cnt) / total_signals if total_signals > 0 else 0

    # 信号分布稳定性 (CV of per-stock signal counts, lower=more stable)
    if total_signals > 0:
        counts_arr = np.array(list(per_stock_signals.values()))
        mean_c = counts_arr.mean()
        std_c = counts_arr.std()
        cv = std_c / mean_c if mean_c > 0 else 2.0
        stability = max(0.0, 1.0 - cv)  # cv=0 → stability=1, cv=1 → stability=0
    else:
        stability = 0.0

    # === 综合评分 v2 ===
    # (a) 命中率贡献: hit_rate * 0.35
    score_a = hit_rate * 0.35

    # (b) B2+B3确认率贡献: min(b2b3_ratio, 0.6) / 0.6 * 0.25
    score_b = min(b2b3_ratio, 0.6) / 0.6 * 0.25

    # (c) 信号密度贡献: 越少越好 (目标每年1-5个信号; >10则严重惩罚)
    #     (1 - min(signals_per_stock_per_year/10, 0.9)) * 0.25
    score_c = (1.0 - min(signals_per_stock_per_year / 10.0, 0.9)) * 0.25

    # (d) 稳定性贡献
    score_d = stability * 0.15

    score = score_a + score_b + score_c + score_d

    return {
        "params": params,
        "hit_count": hit_count,
        "hit_rate": round(hit_rate, 4),
        "total_signals": total_signals,
        "b1_cnt": b1_cnt,
        "b2_cnt": b2_cnt,
        "b3_cnt": b3_cnt,
        "b2b3_ratio": round(b2b3_ratio, 4),
        "signals_per_stock_year": round(signals_per_stock_per_year, 2),
        "stability": round(stability, 3),
        "score": round(score, 4),
        "score_breakdown": {
            "hit": round(score_a, 4),
            "b2b3": round(score_b, 4),
            "density": round(score_c, 4),
            "stability": round(score_d, 4),
        },
    }


def main():
    print("=" * 80)
    print("B1_B2_B3 参数网格搜索 (v2: B1/B2/B3 多维评分)")
    print("=" * 80)

    if not CASE_FILE.exists():
        print(f"[ERROR] 案例股文件不存在: {CASE_FILE}")
        return

    symbol_list = load_case_stocks(CASE_FILE)
    print(f"[INFO] 案例股: {len(symbol_list)} 只")
    print(f"  代码: {symbol_list[:5]}...")

    print(f"[INFO] 加载数据: {DATA_DIR}")
    t0 = time.time()
    stocks = load_stocks(DATA_DIR, symbols=symbol_list, min_days=200)
    print(f"[INFO] 加载了 {len(stocks)}/{len(symbol_list)} 只 (耗时 {time.time()-t0:.1f}s)")

    valid_symbols = [s for s in symbol_list if s in stocks]
    if len(valid_symbols) < len(symbol_list):
        missing = set(symbol_list) - set(stocks.keys())
        print(f"[WARN] 缺少数据: {sorted(missing)}")
    print(f"[INFO] 有效案例股: {len(valid_symbols)} 只")

    # --- 参数网格 ---
    j_thresholds = [13, 18, 23, 28]
    pct_change_ranges = [3.0, 5.0, 7.0]
    vol_mult_b2s = [1.5, 2.0, 3.0]

    conf_combos = [
        (0.0, 0.0, 0.0, "no_filter"),
        (0.7, 0.0, 0.0, "b1_high_only"),
        (0.0, 0.8, 0.0, "b2_high_only"),
    ]

    total_combos = len(j_thresholds) * len(pct_change_ranges) * len(vol_mult_b2s) * len(conf_combos)
    print(f"\n[INFO] 参数组合总数: {total_combos}")
    print(f"  j_threshold: {j_thresholds}")
    print(f"  pct_change_range: {pct_change_ranges}")
    print(f"  vol_mult_b2: {vol_mult_b2s}")
    print(f"  conf_combos: {[c[3] for c in conf_combos]}")

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

                    if n_done % 30 == 0:
                        elapsed = time.time() - t_start
                        best_so_far = max(r2["score"] for r2 in results)
                        print(f"  ... {n_done}/{total_combos} ({elapsed:.1f}s) best_score={best_so_far:.4f}")

    total_elapsed = time.time() - t_start
    print(f"\n[INFO] 网格搜索完成，耗时 {total_elapsed:.1f}s")

    # --- 排序 ---
    results.sort(key=lambda x: x["score"], reverse=True)

    # --- 输出: 全面展示 ---
    print("\n" + "=" * 80)
    print("Top 15 参数组合 (综合评分)")
    print("=" * 80)
    hdr = (
        f"{'Rk':<4} {'Score':<8} {'Hit%':<7} {'TotSig':<7} "
        f"{'B1':<6} {'B2':<6} {'B3':<5} {'B2B3%':<8} "
        f"{'S/Yr':<6} {'Stab':<6} {'J':<5} {'Pct%':<5} {'VolB2':<6} {'Conf':<15}"
    )
    print(hdr)
    print("-" * 80)

    for rank, r in enumerate(results[:15], 1):
        p = r["params"]
        bd = r["score_breakdown"]
        print(
            f"{rank:<4} {r['score']:<8.4f} {r['hit_rate']:<7.2%} {r['total_signals']:<7} "
            f"{r['b1_cnt']:<6} {r['b2_cnt']:<6} {r['b3_cnt']:<5} {r['b2b3_ratio']:<8.2%} "
            f"{r['signals_per_stock_year']:<6.1f} {r['stability']:<6.3f} "
            f"{p['j_threshold']:<5} {p['pct_change_range']:<5} {p['vol_mult_b2']:<6} "
            f"{r.get('conf_label','?'):<15}"
        )

    # --- 按 j_threshold 分组统计 ---
    print("\n" + "=" * 80)
    print("按 j_threshold 分组汇总")
    print("=" * 80)
    for jv in j_thresholds:
        group = [r for r in results if r["params"]["j_threshold"] == jv]
        avg_hit = np.mean([r["hit_rate"] for r in group])
        avg_sig = np.mean([r["total_signals"] for r in group])
        avg_b2b3 = np.mean([r["b2b3_ratio"] for r in group])
        avg_spy = np.mean([r["signals_per_stock_year"] for r in group])
        avg_score = np.mean([r["score"] for r in group])
        print(f"  j={jv}: avg_hit={avg_hit:.1%} avg_sigs={avg_sig:.0f} "
              f"avg_b2b3={avg_b2b3:.1%} avg_sigs/yr={avg_spy:.1f} avg_score={avg_score:.4f}")

    # --- 筛选命中率>80%且信号密度合理的组合 ---
    qualified = [r for r in results if r["hit_rate"] >= 0.80 and r["signals_per_stock_year"] <= 20]
    qualified.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n[INFO] 命中率>=80% 且 信号密度<=20/yr: {len(qualified)}/{total_combos}")
    if qualified:
        print("\n--- 合格组合 Top 8 ---")
        for rank, r in enumerate(qualified[:8], 1):
            p = r["params"]
            print(
                f"  #{rank} score={r['score']:.4f} hit={r['hit_rate']:.1%} "
                f"B1={r['b1_cnt']} B2={r['b2_cnt']} B3={r['b3_cnt']} "
                f"B2B3%={r['b2b3_ratio']:.1%} sigs/yr={r['signals_per_stock_year']:.1f} "
                f"j={p['j_threshold']} pct={p['pct_change_range']} vol={p['vol_mult_b2']} "
                f"conf={r.get('conf_label','?')}"
            )

    # --- 保存到 JSON ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "grid_search_b1b2b3.json"
    serializable = []
    for r in results:
        sr = {
            "params": {k: v for k, v in r["params"].items()},
            "hit_rate": r["hit_rate"],
            "total_signals": r["total_signals"],
            "b1_cnt": r["b1_cnt"],
            "b2_cnt": r["b2_cnt"],
            "b3_cnt": r["b3_cnt"],
            "b2b3_ratio": r["b2b3_ratio"],
            "signals_per_stock_year": r["signals_per_stock_year"],
            "stability": r["stability"],
            "score": r["score"],
            "score_breakdown": r["score_breakdown"],
            "conf_label": r.get("conf_label", "?"),
        }
        serializable.append(sr)

    with open(out_path, "w") as f:
        json.dump(serializable, f, indent=2)
    print(f"\n[INFO] 结果已保存: {out_path}")

    # --- 更新 best_params.json ---
    # 取合格组合中评分最高的 (如果合格组合为空则取全局最高)
    best_overall = results[0]
    best_qualified = qualified[0] if qualified else best_overall

    bp = best_qualified["params"]
    best_params = {
        "B1_B2_B3": {
            "j_threshold": bp["j_threshold"],
            "pct_change_range": bp["pct_change_range"],
            "vol_mult_b2": bp["vol_mult_b2"],
            "min_conf_b1": bp["min_conf_b1"],
            "min_conf_b2": bp["min_conf_b2"],
            "min_conf_b3": bp["min_conf_b3"],
            "conf_label": best_qualified.get("conf_label", "?"),
            "hit_rate": best_qualified["hit_rate"],
            "b2b3_ratio": best_qualified["b2b3_ratio"],
            "total_signals": best_qualified["total_signals"],
            "signals_per_stock_year": best_qualified["signals_per_stock_year"],
            "score": best_qualified["score"],
        }
    }

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
    print("\n" + "=" * 80)
    print("搜索总结")
    print("=" * 80)
    print(f"  参数组合总数: {total_combos}")
    print(f"  命中率>=80%: {sum(1 for r in results if r['hit_rate']>=0.80)}/{total_combos}")
    print(f"  合格(>=80%且<=20/yr): {len(qualified)}/{total_combos}")
    print(f"  全局最佳评分: {results[0]['score']:.4f}")
    print(f"  合格最佳评分: {qualified[0]['score']:.4f}" if qualified else "  合格: 无")
    print(f"  Best params -> config/best_params.json")


if __name__ == "__main__":
    main()
