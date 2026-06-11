"""ML 形态模型 — GBDT 胜率预测（用户确认路线 2026-06-11）。

训练标签：三大战法状态机的逐笔交易，net_return>0 为正样本（贴近实战）。
特征：入场日的 11 个连续子分数 + 14 个量价工程特征（共 ~25 维，全因果）。
切分：按入场年份时间切分（≤2023 训练 / 2024 验证 / 2025+ 测试），防泄漏。
强化：tracking 库 ml_boost 标记的连涨信号作为加权正样本并入。
输出：models/pattern_gbdt.pkl + 特征重要性 + 分位胜率提升报告；
     predict_ml_score() 供评分体系作为 ml_score 子分数（0-1）。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphapulse.ranking.sub_scores import compute_sub_scores
from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line
from alphapulse.factors.b1_formula import compute_kdj_j, compute_macd_dif

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODEL_DIR / "pattern_gbdt.pkl"
META_PATH = MODEL_DIR / "pattern_gbdt_meta.json"

def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """单股全历史特征帧（一次向量化算完，每行=该日入场可见特征）。

    与逐日切片等价（全部因果算子），快两个数量级——12万笔交易特征
    从~100分钟降到~2分钟。
    """
    from alphapulse.ranking.sub_scores import compute_sub_score_frame

    subs = compute_sub_score_frame(df)
    if subs.empty:
        return pd.DataFrame()

    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)

    white = compute_short_trend(c)
    yellow = compute_bull_bear_line(c)
    j = compute_kdj_j(h, low, c)
    dif = compute_macd_dif(c)

    v_ma5 = v.rolling(5).mean()
    v_ma20 = v.rolling(20).mean()
    c_min120 = c.rolling(120).min()
    c_max120 = c.rolling(120).max()

    eng = pd.DataFrame({
        "ret_5": c / c.shift(5) - 1,
        "ret_10": c / c.shift(10) - 1,
        "ret_20": c / c.shift(20) - 1,
        "ret_60": c / c.shift(60) - 1,
        "vol_ratio_5": v / v_ma5.replace(0, np.nan),
        "vol_ratio_20": v / v_ma20.replace(0, np.nan),
        "vol_trend": v_ma5 / v_ma20.replace(0, np.nan),
        "amp_20": h.rolling(20).max() / low.rolling(20).min().replace(0, np.nan) - 1,
        "dist_white": c / white.replace(0, np.nan) - 1,
        "dist_yellow": c / yellow.replace(0, np.nan) - 1,
        "j_value": j,
        "dif_pct": dif / c.replace(0, np.nan),
        "pos_in_120d": (c - c_min120) / (c_max120 - c_min120).replace(0, np.nan),
        "volatility_20": c.pct_change().rolling(20).std(),
    }, index=df.index)
    return pd.concat([eng, subs], axis=1)


def features_at(df: pd.DataFrame, i: int) -> dict | None:
    """入场日 i 的完整特征（单点查询用；批量请直接用 feature_frame）。"""
    frame = feature_frame(df)
    if frame.empty or i < 120 or i >= len(frame):
        return None
    return frame.iloc[i].to_dict()


def build_training_set(stocks: dict[str, pd.DataFrame],
                       playbooks: list[str] | None = None) -> pd.DataFrame:
    """全部战法交易 → 特征表（每笔交易一行 + label + entry_year + weight）。"""
    from alphapulse.strategies.playbook_engine import PLAYBOOKS
    playbooks = playbooks or list(PLAYBOOKS)
    rows = []
    for sym, df in stocks.items():
        frame = feature_frame(df)  # 每股只算一次
        if frame.empty:
            continue
        dates = df["date"].astype(str).tolist()
        idx_map = {d: i for i, d in enumerate(dates)}
        for pb in playbooks:
            try:
                trades = PLAYBOOKS[pb](df, symbol=sym)
            except Exception:
                continue
            for t in trades:
                i = idx_map.get(t["entry_date"])
                if i is None or i < 120:
                    continue
                rows.append({**frame.iloc[i].to_dict(),
                             "label": int(t["net_return"] > 0),
                             "entry_year": int(t["entry_date"][:4]),
                             "playbook": pb, "symbol": sym,
                             "entry_date": t["entry_date"], "weight": 1.0})
    return pd.DataFrame(rows)


def append_boost_samples(train_df: pd.DataFrame,
                         stocks: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """tracking 库连涨强化样本 → 加权正样本并入。"""
    try:
        import sqlite3
        from alphapulse.tracking.signal_tracker import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        boosted = pd.read_sql(
            "SELECT s.symbol, s.date FROM signals s JOIN ml_boost b ON b.signal_id = s.id", conn)
        conn.close()
    except Exception:
        return train_df
    rows = []
    for _, r in boosted.iterrows():
        df = stocks.get(str(r["symbol"]).zfill(6))
        if df is None:
            continue
        dates = df["date"].astype(str).tolist()
        try:
            i = dates.index(r["date"])
        except ValueError:
            continue
        f = features_at(df, i)
        if f:
            rows.append({**f, "label": 1, "entry_year": int(r["date"][:4]),
                         "playbook": "BOOST", "symbol": r["symbol"],
                         "entry_date": r["date"], "weight": 2.0})
    if rows:
        train_df = pd.concat([train_df, pd.DataFrame(rows)], ignore_index=True)
    return train_df


def train(train_df: pd.DataFrame, train_until: int = 2023,
          valid_year: int = 2024) -> dict:
    """时间切分训练 + 评估 + 落盘。"""
    import joblib
    from lightgbm import LGBMClassifier
    from sklearn.metrics import roc_auc_score

    meta_cols = {"label", "entry_year", "playbook", "symbol", "entry_date", "weight"}
    feat_cols = [c for c in train_df.columns if c not in meta_cols]

    tr = train_df[train_df["entry_year"] <= train_until]
    va = train_df[train_df["entry_year"] == valid_year]
    te = train_df[train_df["entry_year"] > valid_year]

    model = LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=31,
        min_child_samples=100, subsample=0.8, colsample_bytree=0.8,
        reg_lambda=1.0, random_state=42, verbosity=-1)
    model.fit(tr[feat_cols], tr["label"], sample_weight=tr["weight"],
              eval_set=[(va[feat_cols], va["label"])] if len(va) else None)

    report = {"n_train": len(tr), "n_valid": len(va), "n_test": len(te),
              "base_win_rate": round(float(tr["label"].mean()), 4),
              "features": feat_cols}
    for name, part in [("valid", va), ("test", te)]:
        if len(part) < 100:
            continue
        proba = model.predict_proba(part[feat_cols])[:, 1]
        report[f"{name}_auc"] = round(float(roc_auc_score(part["label"], proba)), 4)
        # 分位胜率：模型分Top10%交易 vs 全体
        q = pd.qcut(proba, 10, labels=False, duplicates="drop")
        decile = part.groupby(q)["label"].mean()
        report[f"{name}_top_decile_win"] = round(float(decile.iloc[-1]), 4)
        report[f"{name}_bottom_decile_win"] = round(float(decile.iloc[0]), 4)

    imp = sorted(zip(feat_cols, model.feature_importances_.tolist()),
                 key=lambda x: -x[1])
    report["feature_importance"] = [(k, int(v)) for k, v in imp[:15]]

    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    META_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


_model_cache = None


def predict_ml_score(df: pd.DataFrame) -> float | None:
    """单股最新一日的 ML 胜率分（0-1）。模型缺失返回 None。"""
    global _model_cache
    if not MODEL_PATH.exists():
        return None
    if _model_cache is None:
        import joblib
        _model_cache = (joblib.load(MODEL_PATH),
                        json.loads(META_PATH.read_text())["features"])
    model, feat_cols = _model_cache
    f = features_at(df, len(df) - 1)
    if f is None:
        return None
    x = pd.DataFrame([f])[feat_cols]
    return round(float(model.predict_proba(x)[:, 1][0]), 4)
