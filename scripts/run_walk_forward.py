#!/usr/bin/env python3
"""Walk-forward 网格重跑（B1_B2_B3 / BRICK_THREE_TYPES）。

用法：
    python scripts/run_walk_forward.py --strategy B1_B2_B3 --sample 800
    python scripts/run_walk_forward.py --strategy BRICK_THREE_TYPES --sample 800

输出：
- reports/walk_forward_<策略>.md（每组参数8窗样本外成功率 + 链式流程回测）
- config/best_params.json 更新为稳健参数（带 walk_forward 来源标注，旧参数存 _provenance）
"""

import argparse
import itertools
import json
import random
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from scripts.walk_forward import (  # noqa: E402
    make_windows, evaluate_combo_on_windows, robust_score, chain_selection,
    HORIZON, SUCCESS_PCT)

BEST_PARAMS_FILE = PROJECT_ROOT / "config" / "best_params.json"
REPORTS_DIR = PROJECT_ROOT / "reports"


def should_replace(new_score: float, incumbent: float, min_improve: float) -> bool:
    """新参数是否值得覆盖在任参数。

    要求 new > incumbent + min_improve（噪声容忍带）。没有在任记录（-inf）时直接写入。
    min_improve=-inf 表示强制覆盖。
    """
    if min_improve == float("-inf"):
        return True
    if incumbent == float("-inf"):
        return True
    return new_score > incumbent + min_improve

GRIDS = {
    "B1_B2_B3": {
        "module": ("alphapulse.strategies.b1_b2_b3_strategy", "generate_signals"),
        "grid": {
            "j_threshold": [13, 18, 23],
            "pct_change_range": [3.0, 5.0, 7.0],
            "vol_mult_b2": [1.5, 2.0, 3.0],
            "min_conf_b1": [0.0, 0.7],
        },
    },
    "BRICK_THREE_TYPES": {
        "module": ("alphapulse.strategies.brick_three_types", "generate_signals"),
        "grid": {
            "vol_mult_n_jump": [1.3, 1.5, 2.0],
            "vol_mult_breakout": [1.2, 1.3, 1.5],
            "consol_lookback": [3, 5],
            "consol_max_amplitude": [10, 15],
        },
    },
}


def load_sample(sample_n: int, seed: int = 42) -> dict[str, pd.DataFrame]:
    files = sorted(Path(DATA_DIR).glob("*.csv"))
    random.seed(seed)
    picked = random.sample(files, min(sample_n, len(files)))
    stocks = {}
    for f in picked:
        try:
            df = pd.read_csv(f, dtype={"date": str})
            if len(df) >= 300:
                stocks[f.stem] = df
        except Exception:
            continue
    return stocks


def signal_dates_of(sig_frame: pd.DataFrame, src: pd.DataFrame) -> list[str]:
    """信号帧 → 买入信号日列表。

    信号帧的索引=输入帧的行标签（对 RangeIndex 输入是行号），必须经源帧
    date 列映射回日期，不能直接把索引当日期。
    """
    if sig_frame is None or sig_frame.empty:
        return []
    if "signal" in sig_frame.columns:
        sig_frame = sig_frame[sig_frame["signal"] == 1]
    if sig_frame.empty:
        return []
    return [str(d)[:10] for d in src["date"].reindex(sig_frame.index).dropna()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, choices=list(GRIDS))
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--min-improve", type=float, default=0.02,
                    help="覆盖在任参数所需的最小 robust 提升（噪声容忍，默认0.02）")
    ap.add_argument("--force-write", action="store_true",
                    help="无视提升门槛强制写入 best_params.json")
    args = ap.parse_args()
    if args.force_write:
        args.min_improve = float("-inf")   # 强制覆盖

    spec = GRIDS[args.strategy]
    mod = __import__(spec["module"][0], fromlist=[spec["module"][1]])
    gen = getattr(mod, spec["module"][1])

    print(f"[WF] 加载样本 {args.sample} 只 ...", flush=True)
    t0 = time.time()
    stocks = load_sample(args.sample)
    closes_map = {s: d.set_index("date")["close"].astype(float)
                  for s, d in stocks.items()}
    print(f"[WF] 有效 {len(stocks)} 只（{time.time()-t0:.0f}s）", flush=True)

    windows = make_windows()
    keys = list(spec["grid"])
    combos = [dict(zip(keys, vals))
              for vals in itertools.product(*spec["grid"].values())]
    print(f"[WF] {args.strategy}: {len(combos)} 组参数 × {len(windows)} 个验证窗 "
          f"(口径: {HORIZON}日内+{SUCCESS_PCT:.0f}%)", flush=True)

    combo_windows: dict[str, list] = {}
    combo_meta: dict[str, dict] = {}
    for ci, params in enumerate(combos, 1):
        key = json.dumps(params, sort_keys=True)
        all_signals = {}
        for sym, df in stocks.items():
            try:
                dates = signal_dates_of(gen(df, symbol=sym, **params), df)
                if dates:
                    all_signals[sym] = dates
            except Exception:
                continue
        per_window = evaluate_combo_on_windows(all_signals, closes_map, windows)
        combo_windows[key] = per_window
        combo_meta[key] = {"params": params, "robust": robust_score(per_window)}
        if ci % 6 == 0 or ci == len(combos):
            done_scores = [m["robust"]["robust"] for m in combo_meta.values() if m["robust"]]
            best = max(done_scores) if done_scores else float("nan")
            print(f"  ... {ci}/{len(combos)} ({time.time()-t0:.0f}s) "
                  f"best_robust={best:.3f}", flush=True)

    ranked = sorted((m for m in combo_meta.values() if m["robust"]),
                    key=lambda m: m["robust"]["robust"], reverse=True)
    if not ranked:
        print("[WF] 无参数组合满足有效窗口数要求，放弃更新 best_params")
        return 1

    chain = chain_selection(combo_windows, windows)

    # ---- Markdown 报告 ----
    md = [f"# Walk-Forward 报告 — {args.strategy}",
          f"\n样本 {len(stocks)} 只（seed=42）| {len(combos)} 组参数 × {len(windows)} 验证窗"
          f" | 口径: 信号后{HORIZON}个交易日内最高收盘 ≥ +{SUCCESS_PCT:.0f}%\n",
          "## 稳健参数 Top 10（0.5×中位窗 + 0.5×最差窗）\n",
          "| # | robust | 中位 | 最差 | 最好 | 有效窗 | 总信号 | 参数 |",
          "|---|---|---|---|---|---|---|---|"]
    for i, m in enumerate(ranked[:10], 1):
        r = m["robust"]
        md.append(f"| {i} | {r['robust']:.3f} | {r['median']:.3f} | {r['worst']:.3f} "
                  f"| {r['best']:.3f} | {r['valid_windows']} | {r['total_signals']} "
                  f"| `{json.dumps(m['params'], ensure_ascii=False)}` |")
    md += ["\n## 链式流程回测（每窗只用之前窗口的信息选参 → 该窗样本外成功率）\n",
           "| 验证窗 | 样本外成功率 | 信号数 | 当时选中参数 |", "|---|---|---|---|"]
    for c in chain:
        oos = f"{c['oos']:.1%}" if c["oos"] is not None else "—"
        md.append(f"| {c['window']} | {oos} | {c['n']} | `{c['chosen'] or '—'}` |")
    oos_vals = [c["oos"] for c in chain if c["oos"] is not None]
    if oos_vals:
        md.append(f"\n**流程期望**: 链式样本外成功率 中位 {pd.Series(oos_vals).median():.1%} / "
                  f"最差 {min(oos_vals):.1%}（这是该选参流程实盘可期待的无偏估计）")
    out_md = REPORTS_DIR / f"walk_forward_{args.strategy}.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"[WF] 报告 → {out_md}", flush=True)

    # ---- 更新 best_params.json（保留旧参数为 provenance）----
    best = ranked[0]
    existing = {}
    if BEST_PARAMS_FILE.exists():
        try:
            existing = json.loads(BEST_PARAMS_FILE.read_text())
        except Exception:
            existing = {}
    old = existing.get(args.strategy)
    entry = dict(best["params"])
    entry["_source"] = {
        "method": "walk_forward",
        "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "robust_score": round(best["robust"]["robust"], 4),
        "oos_median": round(best["robust"]["median"], 4),
        "oos_worst": round(best["robust"]["worst"], 4),
        "windows": best["robust"]["valid_windows"],
        "metric": f"{HORIZON}日内+{SUCCESS_PCT:.0f}%成功率",
    }
    if old and "_source" not in old:
        entry["_provenance_prev"] = old

    # ---- 胜过在任参数才覆盖（2026-07-28 修正）----
    # 此前无条件写入本轮网格第一名：样本是固定随机抽样、目标是噪声较大的命中率，
    # 不同市况下重跑很容易用一组"这轮碰巧最高"的参数替换掉更稳健的在任参数。
    new_score = float(best["robust"]["robust"])
    incumbent = float((old or {}).get("_source", {}).get("robust_score", float("-inf")))
    if not should_replace(new_score, incumbent, args.min_improve):
        print(f"[WF] 未覆盖 best_params：新 robust={new_score:.4f} 未超过在任 "
              f"{incumbent:.4f} + 噪声容忍 {args.min_improve:.4f}（报告已生成，"
              f"如确需覆盖用 --force-write）", flush=True)
        return 0

    existing[args.strategy] = entry
    BEST_PARAMS_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"[WF] best_params 已更新: {json.dumps(best['params'], ensure_ascii=False)} "
          f"robust={new_score:.4f}（在任 {incumbent:.4f}）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
