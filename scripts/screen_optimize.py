#!/usr/bin/env python3
"""纯选股参数优化（v5 walk-forward，2026-08-02）。

目标函数 = 选股成功率（与 screen_bt 同口径：H 日内任一收盘 ≥ +P% 的机会命中），
稳健分 = 0.5×验证窗中位成功率 + 0.5×最差窗成功率（惩罚方差，不选单窗冠军）。
第一性原理约束：**只有稳健成功率显著跑赢同窗基线（随机选一只）才允许写入
best_params.json**——选股的价值必须体现在超额命中率上。

用法：
    python scripts/screen_optimize.py --strategy B1_B2_B3 --sample 800
    python scripts/screen_optimize.py --strategy NEEDLE_WASHOUT --force-write
"""

import argparse
import itertools
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.screening.evaluator import (  # noqa: E402
    evaluate_strategy, signal_dates_of, DEFAULT_HORIZON, DEFAULT_SUCCESS_PCT,
)
from alphapulse.screening.strategies import run_strategy, SCREENING_STRATEGIES  # noqa: E402
from scripts.walk_forward import make_windows, chain_selection  # noqa: E402

BEST_PARAMS_FILE = PROJECT_ROOT / "config" / "best_params.json"
MIN_SIGNALS_PER_WINDOW = 8
MIN_VALID_WINDOWS = 5

# 各策略可优化参数网格（保守邻域，覆盖在任参数）
GRIDS: dict[str, dict[str, list]] = {
    "B1_B2_B3": {
        "j_threshold": [13, 18, 23],
        "pct_change_range": [3.0, 5.0, 7.0],
        "vol_mult_b2": [1.5, 2.0, 3.0],
        "min_conf_b1": [0.0, 0.7],
    },
    "BRICK_THREE_TYPES": {
        "vol_mult_n_jump": [1.3, 1.5, 2.0],
        "vol_mult_breakout": [1.2, 1.3, 1.5],
        "consol_lookback": [3, 5],
        "consol_max_amplitude": [10, 15],
    },
    "NEEDLE_WASHOUT": {
        "j_threshold": [13, 20, 25],
        "shadow_mult": [2.0, 3.0, 4.0],
        "volume_shrink_ratio": [0.7, 0.85, 1.0],
        "fib_min": [0.1, 0.2, 0.3],
    },
    "B1_FORMULA": {
        "j_threshold": [8, 13, 18],
        "dif_threshold": [-0.3, -0.1, 0.0],
        "pct_change_range": [2.0, 3.0, 5.0],
    },
    "ZHIXING_ULTRA": {
        "med_long_min": [55.0, 65.0, 75.0],
        "brick_min_ratio": [0.5, 0.6667, 0.8],
        "dif_min": [0.0, 0.1],
    },
    "VOLUME_B1": {
        "yangyin_ratio_28": [1.4, 1.65, 2.0],
        "yangyin_ratio_14": [1.8, 2.25, 2.7],
        "surge_ratio": [1.5, 1.85, 2.2],
    },
}


def load_sample(sample_n: int, data_dir: str | Path, min_days: int = 300,
                seed: int = 42) -> dict[str, pd.DataFrame]:
    files = sorted(Path(data_dir).glob("*.csv"))
    random.seed(seed)
    picked = random.sample(files, min(sample_n, len(files)))
    stocks = {}
    for f in picked:
        try:
            df = pd.read_csv(f, dtype={"date": str})
            if len(df) >= min_days:
                stocks[f.stem] = df
        except Exception:
            continue
    return stocks


def eval_combo_on_windows(strategy: str, params: dict, stocks: dict,
                          closes_map: dict, windows: list[dict],
                          horizon: int, success_pct: float) -> list[dict | None]:
    """一组参数在每个验证窗的样本外成功率（+ 该窗基线）。"""
    # 全历史信号只算一次，按窗过滤日期
    all_dates: dict[str, list[str]] = {}
    for sym, df in stocks.items():
        try:
            frame = run_strategy(strategy, df, **params)
            dates = signal_dates_of(frame, df)
            if dates:
                all_dates[sym] = dates
        except Exception:
            continue
    per_window = []
    for w in windows:
        win_by_symbol = {sym: [d for d in dates
                               if w["valid_start"] <= d <= w["valid_end"]]
                         for sym, dates in all_dates.items()}
        r = evaluate_strategy(win_by_symbol, closes_map, horizon, success_pct)
        n = r.get("n", 0)
        if n < MIN_SIGNALS_PER_WINDOW or r.get("success_rate") is None:
            per_window.append(None)
        else:
            per_window.append({
                "n": n,
                "success_rate": r["success_rate"],
                "base_rate": r.get("base_rate"),
                "lift_pp": r.get("lift_pp"),
            })
    return per_window


def robust_score(per_window: list[dict | None]) -> dict | None:
    rates = [w["success_rate"] for w in per_window if w]
    bases = [w["base_rate"] for w in per_window if w and w.get("base_rate") is not None]
    if len(rates) < MIN_VALID_WINDOWS:
        return None
    return {
        "valid_windows": len(rates),
        "median": float(np.median(rates)),
        "worst": float(np.min(rates)),
        "best": float(np.max(rates)),
        "robust": 0.5 * float(np.median(rates)) + 0.5 * float(np.min(rates)),
        "base_median": float(np.median(bases)) if bases else None,
        "lift_pp": (0.5 * float(np.median(rates)) + 0.5 * float(np.min(rates))
                    - (np.median(bases) if bases else 0.0)),
        "total_signals": int(sum(w["n"] for w in per_window if w)),
    }


def should_write(new: dict, incumbent_score: float, min_improve: float,
                 min_lift: float) -> tuple[bool, str]:
    # 基线门槛优先于一切：无论有无在任参数，跑不赢随机就不写
    # （2026-08-02 修复：旧逻辑"无在任参数直接写"会绕过 min_lift——
    # 新策略 ZHIXING_ULTRA 超额 +1.75pp 曾被误写入）
    if new.get("lift_pp") is None or new["lift_pp"] < min_lift:
        return False, (f"超额命中不足（{new.get('lift_pp')}pp < {min_lift}pp）——"
                       f"选股未跑赢随机基线，不写参")
    if incumbent_score == float("-inf"):
        return True, "无在任参数"
    if new["robust"] < incumbent_score + min_improve:
        return False, f"未超在任 {incumbent_score:.4f} + 噪声容忍 {min_improve:.4f}"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, choices=list(GRIDS))
    ap.add_argument("--sample", type=int, default=600)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    ap.add_argument("--success-pct", type=float, default=DEFAULT_SUCCESS_PCT)
    ap.add_argument("--min-improve", type=float, default=1.0,
                    help="覆盖在任参数所需最小 robust 提升（pp）")
    ap.add_argument("--min-lift", type=float, default=3.0,
                    help="相对基线的最小超额命中（pp），不满足不写参")
    ap.add_argument("--force-write", action="store_true",
                    help="无视稳健/超额门槛强制写入")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if args.force_write:
        args.min_improve = float("-inf")
        args.min_lift = float("-inf")

    stocks = load_sample(args.sample, args.data_dir)
    closes_map = {s: d.set_index("date")["close"].astype(float)
                  for s, d in stocks.items()}
    windows = make_windows()
    keys = list(GRIDS[args.strategy])
    combos = [dict(zip(keys, vals))
              for vals in itertools.product(*GRIDS[args.strategy].values())]
    print(f"[WF] {args.strategy}: {len(combos)} 组参数 × {len(windows)} 验证窗 "
          f"（口径: {args.horizon}日内收盘≥+{args.success_pct:.0f}% 机会命中）", flush=True)

    combo_windows: dict[str, list] = {}
    combo_meta: dict[str, dict] = {}
    t0 = time.time()
    for ci, params in enumerate(combos, 1):
        key = json.dumps(params, sort_keys=True)
        per_window = eval_combo_on_windows(
            args.strategy, params, stocks, closes_map, windows,
            args.horizon, args.success_pct)
        combo_windows[key] = per_window
        combo_meta[key] = {"params": params, "robust": robust_score(per_window)}
        if ci % 5 == 0 or ci == len(combos):
            print(f"  ... {ci}/{len(combos)}（{time.time()-t0:.0f}s）", flush=True)

    ranked = sorted((m for m in combo_meta.values() if m["robust"]),
                    key=lambda m: m["robust"]["robust"], reverse=True)
    if not ranked:
        print("[WF] 无参数组合满足有效窗数要求", file=sys.stderr)
        return 1

    chain = chain_selection(combo_windows, windows)

    md = [f"# 纯选股成功率优化 — {args.strategy}",
          f"\n样本 {len(stocks)} 只 | {len(combos)} 组参数 × {len(windows)} 窗"
          f" | 口径: 信号后{args.horizon}日内收盘≥+{args.success_pct:.0f}%（机会命中）",
          f" | 稳健分 = 0.5×中位窗 + 0.5×最差窗；基线 = 同窗全体股票命中率\n",
          "## Top 10（按稳健分）\n",
          "| # | 稳健% | 中位% | 最差% | 基线中位% | 超额pp | 有效窗 | 总信号 | 参数 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for i, m in enumerate(ranked[:10], 1):
        r = m["robust"]
        base = f"{r['base_median']:.1f}" if r.get("base_median") is not None else "—"
        lift = f"{r['lift_pp']:+.1f}" if r.get("lift_pp") is not None else "—"
        md.append(f"| {i} | {r['robust']:.1f} | {r['median']:.1f} | {r['worst']:.1f} | "
                  f"{base} | {lift} | {r['valid_windows']} | {r['total_signals']} "
                  f"| `{json.dumps(m['params'], ensure_ascii=False)}` |")
    md += ["\n## 链式流程回测（每窗只用之前窗口信息选参）\n",
           "| 验证窗 | 样本外成功率% | 信号数 | 当时选中参数 |", "|---|---|---|---|"]
    for c in chain:
        # chain_selection 的 oos 来自 evaluate_strategy（已是百分数），不要再乘 100
        oos = f"{c['oos']:.1f}" if c["oos"] is not None else "—"
        md.append(f"| {c['window']} | {oos} | {c['n']} | `{c['chosen'] or '—'}` |")
    out_md = PROJECT_ROOT / "reports" / f"screen_optimize_{args.strategy}.md"
    out_md.parent.mkdir(exist_ok=True)
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"[WF] 报告 → {out_md}", flush=True)

    best = ranked[0]
    existing = {}
    if BEST_PARAMS_FILE.exists():
        try:
            existing = json.loads(BEST_PARAMS_FILE.read_text())
        except Exception:
            existing = {}
    old = existing.get(args.strategy)
    incumbent = float((old or {}).get("_source", {}).get("robust_score", float("-inf")))
    ok, reason = should_write(best["robust"], incumbent, args.min_improve, args.min_lift)
    if not ok:
        print(f"[WF] 未写入 best_params：{reason}（--force-write 可强制）", flush=True)
        return 0

    entry = dict(best["params"])
    entry["_source"] = {
        "method": "screen_walk_forward",
        "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "metric": f"{args.horizon}日内收盘≥+{args.success_pct:.0f}%机会命中",
        "robust_score": round(best["robust"]["robust"], 4),
        "oos_median": round(best["robust"]["median"], 4),
        "oos_worst": round(best["robust"]["worst"], 4),
        "base_median": (round(best["robust"]["base_median"], 4)
                        if best["robust"].get("base_median") is not None else None),
        "lift_pp": round(best["robust"]["lift_pp"], 4),
        "windows": best["robust"]["valid_windows"],
    }
    if old and "_source" not in old:
        entry["_provenance_prev"] = old
    existing[args.strategy] = entry
    BEST_PARAMS_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"[WF] best_params 已更新: {json.dumps(best['params'], ensure_ascii=False)} "
          f"robust={best['robust']['robust']:.2f}% 超额={best['robust']['lift_pp']:+.2f}pp",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
