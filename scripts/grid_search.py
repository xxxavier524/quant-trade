"""参数网格搜索 — 基于 signal_validator 的稳健性优先扫描。

对注册因子的参数空间做笛卡尔积扫描，每组参数跑信号胜率验证，输出：
- 参数面结果表（CSV，可热力图渲染）
- 邻域稳健性分析：最优参数的相邻组合均值（防止只取 argmax 过拟合）

用法：
    python scripts/grid_search.py --factor B1_FORMULA \\
        --grid '{"j_threshold": [8,10,13,15,18], "pct_change_range": [2,3,4]}' \\
        --sample 800 --window 5
"""

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.backtest.signal_validator import validate_signal  # noqa: E402
from validate_signal import load_universe  # noqa: E402

RESULTS_DIR = PROJECT_ROOT / "backtest_results"


def neighborhood_stability(df: pd.DataFrame, grid: dict, metric: str) -> pd.DataFrame:
    """每个参数组合的邻域均值：与任一参数相邻一档的组合的 metric 平均。

    稳健最优 = 自身高且邻域均值也高（参数面平滑处）。
    """
    keys = list(grid.keys())
    index_of = {k: {v: i for i, v in enumerate(grid[k])} for k in keys}

    def neighbors(row):
        vals = []
        for _, other in df.iterrows():
            dist = 0
            for k in keys:
                di = abs(index_of[k][row[k]] - index_of[k][other[k]])
                dist += di
            if dist == 1:  # 恰好相邻一档
                vals.append(other[metric])
        return sum(vals) / len(vals) if vals else float("nan")

    df = df.copy()
    df["neighborhood_" + metric] = df.apply(neighbors, axis=1)
    # 稳健分 = 0.5*自身 + 0.5*邻域
    df["robust_score"] = 0.5 * df[metric] + 0.5 * df["neighborhood_" + metric]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", required=True)
    ap.add_argument("--grid", required=True, help='JSON: {"param": [v1,v2,...], ...}')
    ap.add_argument("--window", type=int, default=5, help="评估用前向窗口（日）")
    ap.add_argument("--metric", default="mean_net", choices=["win_rate", "win_rate_net", "mean", "mean_net"])
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="9999-12-31")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    grid = json.loads(args.grid)
    combos = [dict(zip(grid.keys(), vals)) for vals in itertools.product(*grid.values())]
    print(f"参数组合: {len(combos)} 组 × universe {args.sample}")

    stocks = load_universe(Path(args.data_dir), args.sample, args.end)
    print(f"universe 加载完成: {len(stocks)} 只")

    rows = []
    t0 = time.monotonic()
    for i, params in enumerate(combos):
        r = validate_signal(args.factor, stocks, params,
                            forward_days=[args.window], start=args.start, end=args.end)
        w = r.get("windows", {}).get(args.window, {})
        rows.append({**params, "n_signals": r.get("n_signals", 0), **w})
        print(f"  [{i+1}/{len(combos)}] {params} → n={r.get('n_signals',0)} "
              f"{args.metric}={w.get(args.metric, float('nan'))}")
    print(f"扫描耗时 {(time.monotonic()-t0)/60:.1f} 分钟")

    df = pd.DataFrame(rows)
    df = df[df["n_signals"] >= 100]  # 样本过少的组合无统计意义
    if df.empty:
        sys.exit("所有组合样本不足，请放宽参数范围")

    df = neighborhood_stability(df, grid, args.metric)
    df = df.sort_values("robust_score", ascending=False).reset_index(drop=True)

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"grid_{args.factor}_{args.window}d.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"\n===== 稳健最优（自身+邻域各50%权重）Top 5 =====")
    cols = list(grid.keys()) + ["n_signals", args.metric, f"neighborhood_{args.metric}", "robust_score"]
    print(df[cols].head(5).to_string(index=False))
    print(f"\n结果已存 {out}")


if __name__ == "__main__":
    main()
