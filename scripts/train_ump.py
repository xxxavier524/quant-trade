#!/usr/bin/env python3
"""UMP 失败模式裁判 训练+时间外推评估 CLI（路线图 #2）。

协议：
- 交易生成：B1B2B3（stop_pct 读 best_params，与生产口径一致）
- 训练：entry_year ≤ 2024 交易特征 KMeans 聚类 → 标定失败簇（n≥80 且 簇胜率≤25%）
- 评估：entry_year ≥ 2025 时间外推——否决组 vs 保留组胜率/净均值 + 误杀率
- 通过判定：保留组胜率 > 全体 ≥1pp 且 否决组净均值显著为负；否则记录负结果不接入

用法：
    python scripts/train_ump.py --sample 1500
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.ml import pattern_model as pm  # noqa: E402
from alphapulse.strategies import ump_referee as ur  # noqa: E402
from validate_signal import load_universe  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1500)
    ap.add_argument("--train-until", type=int, default=2024)
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    stocks = load_universe(Path(args.data_dir), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")

    # v5（2026-08-02）：标签 = 纯选股口径（B1_B2_B3 信号的机会命中）
    print("构建选股特征集（B1_B2_B3）...")
    df = pm.build_training_set(stocks, strategies=["B1_B2_B3"])
    print(f"  选股信号 {len(df)} 笔，基准命中率 {df['label'].mean()*100:.1f}%")

    tr = df[df["entry_year"] <= args.train_until]
    te = df[df["entry_year"] > args.train_until]
    print(f"  训练 {len(tr)} 笔(≤{args.train_until}) / 外推 {len(te)} 笔(>{args.train_until})")
    if len(tr) < 5000 or len(te) < 1000:
        sys.exit("样本不足，加大 --sample")

    model = ur.fit_ump(tr)
    n_veto_c = len(model.veto_clusters)
    veto_stats = model.cluster_stats[
        model.cluster_stats["cluster"].isin(model.veto_clusters)]
    print(f"\n失败簇 {n_veto_c}/{model.kmeans.n_clusters} 个"
          f"（簇内训练期胜率≤{ur.VETO_WIN_RATE*100:.0f}%）")
    if n_veto_c:
        print(veto_stats.round(4).to_string(index=False))

    result = ur.evaluate_holdout(model, te)
    print(f"\n===== 时间外推评估（>{args.train_until}）=====")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    base_win = float(te["label"].mean())
    kept_win = result["kept"].get("win_rate", 0)
    vet = result["vetoed"]
    passed = (result["veto_share"] > 0.02
              and kept_win - base_win >= 0.01
              and vet.get("n", 0) > 100
              and vet.get("mean_net", 0) < 0)
    print(f"\n基准胜率 {base_win*100:.1f}% → 保留组 {kept_win*100:.1f}% "
          f"(提升 {(kept_win-base_win)*100:+.1f}pp) | "
          f"否决 {result['veto_share']*100:.1f}% | 误杀率 {result['false_kill_rate']}")
    print("判定:", "✅ 有效，落盘接入" if passed else "❌ 提升不足，记录负结果不接入")

    if passed:
        ur.save_ump(model, {"train_until": args.train_until,
                            "holdout": result, "base_win_holdout": round(base_win, 4),
                            "sample": args.sample,
                            "metric": "选股机会命中（5日内收盘≥+5%）"})
        print(f"→ {ur.UMP_PATH}")
    print(f"耗时 {(time.monotonic()-t0)/60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    sys.exit(main())
