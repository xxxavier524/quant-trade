#!/usr/bin/env python3
"""Alpha158 入 LGBM 的 AUC 前后对比（路线图#3 进阶验收）。

问题：把 Alpha158 因子加入现有 GBDT 胜率模型的特征集，OOS AUC 是否提升？

协议（沿用 ab_test_rps / ic_weight_tuning 惯例——只报告，不覆盖生产模型）：
1. pattern_model.build_training_set 生成战法逐笔交易 + 27基线特征 + label（口径同生产）
2. 每股 compute_alpha158 一次，按 (symbol, entry_date) 对齐挂到每笔交易行
3. 同切分(≤2023训/2024验/2025+测)、同超参，训两个 LGBM：
   A=基线27特征  B=基线+158  （另出 C=仅Alpha158 作参照）
4. 对比 valid/test 的 AUC + Top10%分位胜率 → reports/alpha158_lgbm_ab.md
   生产模型 models/pattern_gbdt.pkl 不动。

用法：python scripts/alpha158_lgbm_ab.py --sample 1200
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR, REPORTS_DIR  # noqa: E402
from alphapulse.ml import pattern_model as pm  # noqa: E402
from alphapulse.factors.alpha158 import ALPHA158, compute_alpha158  # noqa: E402
from validate_signal import load_universe  # noqa: E402

META_COLS = {"label", "entry_year", "playbook", "symbol", "entry_date",
             "weight", "net_return"}


def attach_alpha158(train_df: pd.DataFrame, stocks: dict) -> pd.DataFrame:
    """按 (symbol, entry_date) 把 Alpha158 因子挂到每笔交易行。

    每股 compute_alpha158 一次，date→行 映射后 reindex 到该股交易的入场日。
    """
    a158_cols = list(ALPHA158)
    blocks = []
    for i, (sym, g) in enumerate(train_df.groupby("symbol", sort=False)):
        if i % 200 == 0 and i:
            print(f"  Alpha158 对齐 {i} 只 ...")
        df = stocks.get(sym)
        if df is None:
            blocks.append(pd.DataFrame(np.nan, index=g.index, columns=a158_cols))
            continue
        frame = compute_alpha158(df)
        frame.index = df["date"].astype(str).values          # 以日期为索引
        picked = frame.reindex(g["entry_date"].values)        # 对齐到入场日
        picked.index = g.index                                # 回到 train_df 行索引
        blocks.append(picked[a158_cols].astype(np.float32))
    a158 = pd.concat(blocks).reindex(train_df.index)
    return pd.concat([train_df, a158], axis=1)


def train_variant(train_df: pd.DataFrame, feat_cols: list[str],
                  train_until: int = 2023, valid_year: int = 2024) -> dict:
    """单一特征集训练+评估（不落盘）。同 pattern_model.train 的切分与超参。"""
    from lightgbm import LGBMClassifier
    from sklearn.metrics import roc_auc_score

    tr = train_df[train_df["entry_year"] <= train_until]
    va = train_df[train_df["entry_year"] == valid_year]
    te = train_df[train_df["entry_year"] > valid_year]

    model = LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=31,
        min_child_samples=100, subsample=0.8, colsample_bytree=0.8,
        reg_lambda=1.0, random_state=42, verbosity=-1)
    model.fit(tr[feat_cols], tr["label"], sample_weight=tr["weight"],
              eval_set=[(va[feat_cols], va["label"])] if len(va) else None)

    out = {"n_feat": len(feat_cols)}
    for name, part in [("valid", va), ("test", te)]:
        if len(part) < 100:
            continue
        proba = model.predict_proba(part[feat_cols])[:, 1]
        out[f"{name}_auc"] = round(float(roc_auc_score(part["label"], proba)), 4)
        q = pd.qcut(proba, 10, labels=False, duplicates="drop")
        decile = part.groupby(q)["label"].mean()
        out[f"{name}_top_decile_win"] = round(float(decile.iloc[-1]), 4)
        out[f"{name}_bottom_decile_win"] = round(float(decile.iloc[0]), 4)
    imp = sorted(zip(feat_cols, model.feature_importances_.tolist()),
                 key=lambda x: -x[1])
    out["top_features"] = [(k, int(v)) for k, v in imp[:15]]
    return out


def write_report(base_cols, a158_cols, res, meta, out_md):
    def row(label, r):
        return (f"| {label} | {r['n_feat']} | {r.get('valid_auc','-')} | "
                f"{r.get('test_auc','-')} | {r.get('test_top_decile_win','-')} | "
                f"{r.get('test_bottom_decile_win','-')} |")

    d_test = res["B"].get("test_auc", 0) - res["A"].get("test_auc", 0)
    d_valid = res["B"].get("valid_auc", 0) - res["A"].get("valid_auc", 0)
    dwin = (res["B"].get("test_top_decile_win", 0)
            - res["A"].get("test_top_decile_win", 0))
    # 采纳门槛沿用 ic_weight_tuning："双指标(valid+test AUC)均改善"才算稳健提升，
    # 否则单集提升多为市场风格/噪声，不足以支撑合入生产特征。
    both_up = d_valid > 0 and d_test > 0
    verdict = ("Alpha158 稳健提升（valid+test 双升）" if both_up and min(d_valid, d_test) >= 0.003 else
               "Alpha158 双升但幅度小" if both_up else
               "Alpha158 非稳健：valid/test 方向不一致，差异在噪声范围，暂不合入生产")
    c_vs_a = res["C"].get("test_auc", 0) - res["A"].get("test_auc", 0)

    lines = [
        "# Alpha158 入 LGBM AUC 前后对比（路线图#3 进阶验收）",
        "",
        f"> 生成: {meta['date']} | universe {meta['n_stocks']} 只 | "
        f"交易样本 {meta['n_trades']} 笔（训{meta['n_train']}/验{meta['n_valid']}/测{meta['n_test']}）| "
        f"基准胜率 {meta['base_win']} | 切分 ≤2023训/2024验/2025+测",
        "",
        f"**结论：{verdict}**",
        "",
        f"- 基线+158 vs 基线：valid AUC Δ{d_valid:+.4f}、test AUC Δ{d_test:+.4f}、"
        f"test Top10%胜率 Δ{dwin:+.4f}",
        f"- 仅Alpha158 vs 基线（无手工特征）：test AUC Δ{c_vs_a:+.4f} "
        f"→ 通用因子库{'基本复现' if abs(c_vs_a) < 0.01 else ('超过' if c_vs_a > 0 else '低于')}手工27特征的信号量",
        "",
        "| 特征集 | 维度 | valid AUC | test AUC | test Top10%胜率 | test Bot10%胜率 |",
        "|---|---|---|---|---|---|",
        row("A 基线(生产27特征)", res["A"]),
        row("B 基线+Alpha158", res["B"]),
        row("C 仅Alpha158", res["C"]),
        "",
        "说明：AUC>0.5 即有区分度；生产模型 test_auc≈0.55。Top10%胜率=模型分最高10%"
        "交易的实际胜率，相对基准胜率的提升是实战收益来源。生产模型 models/pattern_gbdt.pkl "
        "本脚本不改动；若 B 稳定占优，下一步用 pattern_model.feature_frame 合入 Alpha158 子集重训。",
        "",
        "## B（基线+Alpha158）Top15 特征重要性",
        "",
        "| 特征 | 重要性 |",
        "|---|---|",
    ]
    for k, v in res["B"]["top_features"]:
        tag = " *(A158)*" if k in a158_cols else ""
        lines.append(f"| {k}{tag} | {v} |")
    lines += ["", "## C（仅Alpha158）Top15 特征重要性", "",
              "| 特征 | 重要性 |", "|---|---|"]
    for k, v in res["C"]["top_features"]:
        lines.append(f"| {k} | {v} |")
    out_md.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1200)
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    stocks = load_universe(Path(args.data_dir), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")

    pb_kwargs = {}
    try:
        bp = json.loads((PROJECT_ROOT / "config" / "best_params.json").read_text())
        sp = bp.get("PLAYBOOK_B1B2B3", {}).get("stop_pct")
        if sp:
            pb_kwargs["B1B2B3"] = {"stop_pct": sp}
            print(f"B1B2B3 标签口径 stop_pct={sp}（best_params）")
    except Exception:
        pass

    print("构建训练集（战法交易特征化）...")
    train_df = pm.build_training_set(stocks, playbook_kwargs=pb_kwargs)
    train_df = pm.append_boost_samples(train_df, stocks)
    print(f"  交易样本 {len(train_df)} 笔")
    if len(train_df) < 1000:
        sys.exit("样本不足1000，加大 --sample")

    print("挂接 Alpha158 因子 ...")
    train_df = attach_alpha158(train_df, stocks)

    base_cols = [c for c in train_df.columns
                 if c not in META_COLS and c not in ALPHA158]
    a158_cols = list(ALPHA158)
    print(f"基线特征 {len(base_cols)} 维 · Alpha158 {len(a158_cols)} 维")

    res = {}
    for tag, cols in [("A", base_cols), ("B", base_cols + a158_cols),
                      ("C", a158_cols)]:
        print(f"训练变体 {tag}（{len(cols)}维）...")
        res[tag] = train_variant(train_df, cols)
        print(f"  {tag}: {json.dumps({k:v for k,v in res[tag].items() if k!='top_features'}, ensure_ascii=False)}")

    tr = train_df[train_df["entry_year"] <= 2023]
    va = train_df[train_df["entry_year"] == 2024]
    te = train_df[train_df["entry_year"] > 2024]
    meta = {"date": pd.Timestamp.today().strftime("%Y-%m-%d"),
            "n_stocks": len(stocks), "n_trades": len(train_df),
            "n_train": len(tr), "n_valid": len(va), "n_test": len(te),
            "base_win": round(float(tr["label"].mean()), 4)}

    out_md = Path(REPORTS_DIR) / "alpha158_lgbm_ab.md"
    write_report(base_cols, a158_cols, res, meta, out_md)
    print(f"\n→ {out_md}")
    print(f"耗时 {(time.monotonic()-t0)/60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    sys.exit(main())
