"""UMP 失败模式裁判（源：abu UMP 思想，路线图 #2）。

防守型 ML：对历史交易特征做 KMeans 聚类，找出"高密度失败簇"
（簇内胜率显著低于基准），新信号若落入失败簇 → 否决，并指认该簇的
历史统计（n笔/胜率/均亏）作为可解释依据。与 GBDT 胜率模型互补：
GBDT 给连续分，UMP 给带案例指认的硬否决。

训练/评估协议（时间外推，防泄漏）：
- 训练：entry_year ≤ train_until 的交易特征（新止损口径 stop_pct 生成）
- 失败簇判定：簇 n ≥ min_cluster_n 且 簇胜率 ≤ veto_win_rate
- 评估：entry_year > train_until 的交易——被否决组 vs 保留组胜率/净均值，
  误杀率 = 被否决交易中实际盈利的比例
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "ml"
UMP_PATH = MODEL_DIR / "ump_referee.joblib"
UMP_META = MODEL_DIR / "ump_referee_meta.json"

N_CLUSTERS = 40
MIN_CLUSTER_N = 80
VETO_WIN_RATE = 0.25       # 簇胜率≤25% 判失败簇（全体基准约42%）


@dataclass
class UmpModel:
    scaler: object
    kmeans: object
    feat_cols: list[str]
    cluster_stats: pd.DataFrame          # cluster/n/win_rate/mean_net
    veto_clusters: list[int] = field(default_factory=list)


def fit_ump(train_df: pd.DataFrame,
            n_clusters: int = N_CLUSTERS,
            min_cluster_n: int = MIN_CLUSTER_N,
            veto_win_rate: float = VETO_WIN_RATE) -> UmpModel:
    """在训练期交易特征上聚类并标定失败簇。train_df 需含 label + 特征列。"""
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    meta_cols = {"label", "entry_year", "playbook", "symbol", "entry_date",
                 "weight", "net_return"}
    feat_cols = [c for c in train_df.columns if c not in meta_cols]
    X = train_df[feat_cols].fillna(0.0).replace([np.inf, -np.inf], 0.0).values

    scaler = StandardScaler().fit(X)
    km = KMeans(n_clusters=n_clusters, n_init=4, random_state=42)
    labels = km.fit_predict(scaler.transform(X))

    g = train_df.assign(cluster=labels).groupby("cluster")
    stats = pd.DataFrame({
        "n": g.size(),
        "win_rate": g["label"].mean(),
        "mean_net": g["net_return"].mean() if "net_return" in train_df else np.nan,
    }).reset_index()
    veto = stats[(stats["n"] >= min_cluster_n)
                 & (stats["win_rate"] <= veto_win_rate)]["cluster"].tolist()
    return UmpModel(scaler, km, feat_cols, stats, veto)


def ump_predict(model: UmpModel, features: pd.DataFrame) -> pd.DataFrame:
    """特征帧 → (cluster, veto, 簇统计)。features 缺列补0（与GBDT口径一致）。"""
    X = (features.reindex(columns=model.feat_cols, fill_value=0.0)
         .fillna(0.0).replace([np.inf, -np.inf], 0.0).values)
    cl = model.kmeans.predict(model.scaler.transform(X))
    stats = model.cluster_stats.set_index("cluster")
    out = pd.DataFrame({"cluster": cl})
    out["veto"] = out["cluster"].isin(model.veto_clusters)
    out["cluster_n"] = out["cluster"].map(stats["n"])
    out["cluster_win_rate"] = out["cluster"].map(stats["win_rate"]).round(4)
    out["cluster_mean_net"] = out["cluster"].map(stats["mean_net"]).round(4)
    return out


def evaluate_holdout(model: UmpModel, test_df: pd.DataFrame) -> dict:
    """时间外推评估：否决组应显著差于保留组；统计误杀率。"""
    pred = ump_predict(model, test_df)
    lab = test_df["label"].values
    net = test_df["net_return"].values if "net_return" in test_df else None
    v = pred["veto"].values

    def _grp(mask):
        if mask.sum() == 0:
            return {"n": 0}
        d = {"n": int(mask.sum()), "win_rate": round(float(lab[mask].mean()), 4)}
        if net is not None:
            d["mean_net"] = round(float(np.nanmean(net[mask])), 4)
        return d

    kept, vetoed = _grp(~v), _grp(v)
    return {"kept": kept, "vetoed": vetoed,
            "veto_share": round(float(v.mean()), 4),
            "false_kill_rate": (round(float(lab[v].mean()), 4) if v.sum() else None),
            "uplift_win_rate": (round(kept.get("win_rate", 0)
                                      - float(lab.mean()), 4) if len(lab) else None)}


def save_ump(model: UmpModel, extra_meta: dict | None = None) -> None:
    import joblib
    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump({"scaler": model.scaler, "kmeans": model.kmeans,
                 "feat_cols": model.feat_cols,
                 "cluster_stats": model.cluster_stats,
                 "veto_clusters": model.veto_clusters}, UMP_PATH)
    veto_stats = model.cluster_stats[
        model.cluster_stats["cluster"].isin(model.veto_clusters)].round(4)
    meta = {"n_clusters": int(model.kmeans.n_clusters),
            "veto_clusters": model.veto_clusters,
            "veto_cluster_stats": veto_stats.to_dict("records"),
            **(extra_meta or {})}
    UMP_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str))


def load_ump() -> UmpModel | None:
    if not UMP_PATH.exists():
        return None
    import joblib
    d = joblib.load(UMP_PATH)
    return UmpModel(d["scaler"], d["kmeans"], d["feat_cols"],
                    d["cluster_stats"], d["veto_clusters"])


def ump_check(df: pd.DataFrame) -> dict | None:
    """单股最新bar的 UMP 裁决（GUI/agent用）。模型缺失返回 None。"""
    model = load_ump()
    if model is None:
        return None
    from alphapulse.ml.pattern_model import feature_frame
    frame = feature_frame(df)
    if frame.empty:
        return None
    r = ump_predict(model, frame.iloc[[-1]]).iloc[0]
    return {"veto": bool(r["veto"]), "cluster": int(r["cluster"]),
            "cluster_n": int(r["cluster_n"]),
            "cluster_win_rate": float(r["cluster_win_rate"]),
            "cluster_mean_net": float(r["cluster_mean_net"])}
