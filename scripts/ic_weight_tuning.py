#!/usr/bin/env python3
"""因子权重 IC 闭环调优（Phase 3 遗留，composite 种子权重 → 数据驱动）。

协议：
1. 抽样股票全历史 → 每股 compute_sub_score_frame + GBDT批量分 + fwd5
2. 近2年窗口逐日截面 Spearman IC（因子值 vs 未来5日收益）→ mean IC / ICIR
3. 候选权重 w ∝ max(meanIC, 0)（负IC因子清零），归一到现权重总和
4. 验证：逐日截面 zscore 加权合成分 → 每日Top50 的 fwd5 胜率+均值，旧 vs 新
5. 双指标均改善才写入 config/factor_weights.json（旧权重备份 .bak）

用法：python scripts/ic_weight_tuning.py --sample 800 [--apply]
（缺省只报告不落盘；--apply 且通过验证才写入）
"""

import argparse
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
from alphapulse.ranking.composite import load_weights, WEIGHTS_FILE  # noqa: E402
from replay_screen import load_stock  # noqa: E402

WINDOW_DAYS = 500   # 近2年交易日


def _gbdt():
    from alphapulse.ml import pattern_model as pm
    if not pm.MODEL_PATH.exists():
        return None, None
    import joblib
    model = joblib.load(pm.MODEL_PATH)
    feats = json.loads(pm.META_PATH.read_text())["features"]
    return model, feats


def build_panel(frames: dict, factor_cols: list[str]) -> pd.DataFrame:
    """(date, symbol, 各因子, fwd5) 面板，近 WINDOW_DAYS。"""
    from alphapulse.ranking.sub_scores import compute_sub_score_frame
    from alphapulse.ml.pattern_model import feature_frame

    model, feat_cols = _gbdt()
    parts = []
    for i, (sym, df) in enumerate(frames.items()):
        if i % 200 == 0 and i:
            print(f"  面板 {i}/{len(frames)}")
        subs = compute_sub_score_frame(df)
        if subs.empty:
            continue
        close = df["close"].astype(float)
        p = subs.copy()
        if model is not None and "ml_score" in factor_cols:
            try:
                X = (feature_frame(df).reindex(columns=feat_cols, fill_value=0.0)
                     .fillna(0.0))
                p["ml_score"] = model.predict_proba(X)[:, 1]
            except Exception:
                pass
        p["fwd5"] = (close.shift(-5) / close - 1).values
        p["date"] = df["date"].astype(str).values
        p["symbol"] = sym
        parts.append(p.tail(WINDOW_DAYS).dropna(subset=["fwd5"]))
    panel = pd.concat(parts, ignore_index=True)
    return panel[[c for c in ["date", "symbol", "fwd5"] + factor_cols
                  if c in panel.columns]]


def daily_ic(panel: pd.DataFrame, factor_cols: list[str]) -> pd.DataFrame:
    """逐日截面 Spearman IC → 各因子 mean IC / ICIR / 覆盖天数。"""
    ics = {}
    for d, g in panel.groupby("date"):
        if len(g) < 80:
            continue
        r_f = g[factor_cols].rank()
        r_y = g["fwd5"].rank()
        ic_d = r_f.corrwith(r_y)
        ics[d] = ic_d
    icdf = pd.DataFrame(ics).T
    out = pd.DataFrame({
        "mean_ic": icdf.mean(),
        "icir": icdf.mean() / icdf.std().replace(0, np.nan),
        "days": icdf.notna().sum(),
    })
    return out.sort_values("mean_ic", ascending=False)


def composite_eval(panel: pd.DataFrame, weights: dict, factor_cols: list[str],
                   top_n: int = 50) -> dict:
    """截面 zscore 加权合成 → 每日Top-N 的 fwd5 表现。"""
    cols = [c for c in factor_cols if weights.get(c, 0) > 0 and c in panel.columns]
    w = np.array([weights[c] for c in cols])

    def _score(g):
        z = (g[cols] - g[cols].mean()) / g[cols].std().replace(0, np.nan)
        return (z.fillna(0.0) @ w)

    recs = []
    for d, g in panel.groupby("date"):
        if len(g) < 200:
            continue
        s = _score(g)
        top = g.loc[s.nlargest(top_n).index]
        recs.append({"date": d, "win": float((top["fwd5"] > 0).mean()),
                     "mean": float(top["fwd5"].mean())})
    r = pd.DataFrame(recs)
    return {"days": len(r), "win5": round(float(r["win"].mean()), 4),
            "mean5": round(float(r["mean"].mean()), 5)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--apply", action="store_true", help="通过验证后写入权重文件")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    cur = dict(load_weights())
    factor_cols = list(cur.keys())

    files = sorted(Path(args.data_dir).glob("*.csv"))
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

    ic = daily_ic(panel, [c for c in factor_cols if c in panel.columns])
    print("\n=== 因子 IC（fwd5，日截面 Spearman）===")
    print(ic.round(4).to_string())

    total = sum(cur.values())
    pos = ic["mean_ic"].clip(lower=0.0)
    if pos.sum() <= 0:
        print("全部因子 IC≤0，不生成新权重")
        return 1
    new = {k: round(float(pos.get(k, 0.0) / pos.sum() * total), 4) for k in factor_cols}

    old_perf = composite_eval(panel, cur, factor_cols)
    new_perf = composite_eval(panel, new, factor_cols)
    print(f"\n旧权重 Top50: 胜率 {old_perf['win5']*100:.1f}% 均值 {old_perf['mean5']*100:.2f}%"
          f"（{old_perf['days']}日）")
    print(f"新权重 Top50: 胜率 {new_perf['win5']*100:.1f}% 均值 {new_perf['mean5']*100:.2f}%")

    passed = (new_perf["win5"] > old_perf["win5"]
              and new_perf["mean5"] > old_perf["mean5"])
    print("判定:", "✅ 新权重双指标占优" if passed else "❌ 未双改善，保持现权重")
    print("\n新权重候选:", json.dumps(new, ensure_ascii=False))

    if passed and args.apply:
        cfg = json.loads(WEIGHTS_FILE.read_text())
        WEIGHTS_FILE.with_suffix(".json.bak").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2))
        cfg.setdefault("weights", {})["B1_SCORE"] = new
        cfg.setdefault("ic_history", {})[pd.Timestamp.today().strftime("%Y-%m-%d")] = \
            ic["mean_ic"].round(4).to_dict()
        WEIGHTS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        print(f"→ 已写入 {WEIGHTS_FILE}（旧权重备份 .bak）")
    elif passed:
        print("（--apply 未指定，仅报告）")
    print(f"耗时 {(time.monotonic()-t0)/60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    sys.exit(main())
