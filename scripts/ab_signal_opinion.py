#!/usr/bin/env python3
"""AB验证：SignalOpinion 聚合(死区) vs 现行线性 composite 的 Top-N 对比（路线图#8）。

复用 ic_weight_tuning.build_panel（截面 sub_scores+ml_score+fwd5），逐日截面：
- 基线 = 现行 IC 权重线性加权 composite（zscore 加权）Top50 fwd5 胜率/均值
- 对照 = SignalOpinion 聚合（rule 综合分 zscore + ml 概率），死区 ∈ {0,0.25,0.5}
诚实判定：死区聚合是否超越已 IC 调优的线性 composite。

用法：python scripts/ab_signal_opinion.py --sample 800
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR, REPORTS_DIR  # noqa: E402
from alphapulse.ranking.composite import load_weights  # noqa: E402
from alphapulse.ranking.signal_opinion import aggregate, from_rule_ml  # noqa: E402
from ic_weight_tuning import build_panel  # noqa: E402
from replay_screen import load_stock  # noqa: E402


def composite_topn_win(panel, weights, factor_cols, top_n=50):
    """现行线性 composite：逐日截面 zscore 加权 → Top-N fwd5 胜率/均值。"""
    cols = [c for c in factor_cols if weights.get(c, 0) > 0 and c in panel.columns]
    w = np.array([weights[c] for c in cols])
    recs = []
    for d, g in panel.groupby("date"):
        if len(g) < 200:
            continue
        z = (g[cols] - g[cols].mean()) / g[cols].std().replace(0, np.nan)
        s = z.fillna(0.0) @ w
        top = g.loc[s.nlargest(top_n).index]
        recs.append((float((top["fwd5"] > 0).mean()), float(top["fwd5"].mean())))
    r = np.array(recs)
    return (len(r), round(r[:, 0].mean() * 100, 1), round(r[:, 1].mean() * 100, 3))


def opinion_topn_win(panel, weights, factor_cols, dead_zone, top_n=50):
    """SignalOpinion 聚合：rule=加权zscore综合分(截面再zscore作rule_z)，ml=ml_score概率。"""
    cols = [c for c in factor_cols if weights.get(c, 0) > 0
            and c in panel.columns and c != "ml_score"]
    w = np.array([weights[c] for c in cols])
    has_ml = "ml_score" in panel.columns
    recs = []
    for d, g in panel.groupby("date"):
        if len(g) < 200:
            continue
        z = (g[cols] - g[cols].mean()) / g[cols].std().replace(0, np.nan)
        rule_raw = z.fillna(0.0) @ w
        # rule 截面再标准化作为 rule_z（tanh 前的标准分）
        rule_z = ((rule_raw - rule_raw.mean()) / (rule_raw.std() or 1.0)).to_numpy()
        ml = g["ml_score"].to_numpy() if has_ml else [None] * len(g)
        agg = np.array([aggregate(from_rule_ml(rz, mp), dead_zone=dead_zone)
                        for rz, mp in zip(rule_z, ml)])
        s = pd.Series(agg, index=g.index)
        top = g.loc[s.nlargest(top_n).index]
        recs.append((float((top["fwd5"] > 0).mean()), float(top["fwd5"].mean())))
    r = np.array(recs)
    return (len(r), round(r[:, 0].mean() * 100, 1), round(r[:, 1].mean() * 100, 3))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    args = ap.parse_args()

    import random
    weights = dict(load_weights())
    factor_cols = list(weights.keys())
    files = sorted(Path(DATA_DIR).glob("*.csv"))
    random.seed(42)
    files = random.sample(files, min(args.sample, len(files)))
    frames = {}
    for f in files:
        df = load_stock(f, "9999-12-31", min_rows=180)
        if df is not None:
            frames[f.stem] = df
    print(f"样本 {len(frames)} 只")
    panel = build_panel(frames, factor_cols)
    print(f"面板 {len(panel)} 股日 · {panel['date'].nunique()} 交易日")

    base = composite_topn_win(panel, weights, factor_cols)
    rows = [("线性composite(基线)", base)]
    for dz in (0.0, 0.25, 0.5):
        rows.append((f"SignalOpinion 死区{dz}", opinion_topn_win(panel, weights, factor_cols, dz)))

    best = max(rows[1:], key=lambda r: r[1][1])
    d = best[1][1] - base[1]
    verdict = (f"{best[0]} Top50 5日胜率 {best[1][1]}% vs 基线 {base[1]}%（Δ{d:+.1f}）——"
               + ("死区聚合超越线性composite,可选启用" if d > 0.5 else
                  "未超越,现行0-100已近最优(佐证不必重构排序层)"))

    lines = [
        "# SignalOpinion 聚合(死区) vs 线性composite Top50 对比（路线图#8）",
        "",
        f"> 样本 {len(frames)} 只 | 面板 {len(panel)} 股日 · {panel['date'].nunique()} 交易日 | "
        f"Top50 fwd5",
        "",
        f"**结论：{verdict}**",
        "",
        "| 口径 | 交易日 | Top50 5日胜率% | Top50 5日均值% |",
        "|---|---|---|---|",
    ]
    for label, (nd, win, mean) in rows:
        lines.append(f"| {label} | {nd} | {win} | {mean} |")
    lines += ["", "说明：规则子分数+LGBM 已由现行 composite 用 IC 权重线性合成；本对比检验"
              "'置信度加权+死区'是否带来额外增益。负结论=现行排序层已足够,SignalOpinion 作"
              "显式协议保留(便于未来接 LLM/其它源),不替换生产。"]
    out = Path(REPORTS_DIR) / "ab_signal_opinion.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:]))
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
