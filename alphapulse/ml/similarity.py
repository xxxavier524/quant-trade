"""形态相似度搜索 — 找"长得最像案例股信号前走势"的股票（用户确认路线）。

模板：黄金案例股（tests/golden/located_signal_days.csv）各自首个信号日
     前 60 个交易日的收盘走势，z 归一化。
匹配：候选股最近 60 日窗口同样 z 归一化后与全部模板做皮尔逊相关
     （矩阵乘法一次算完），输出每只股票的最佳匹配案例与相似分。

直觉对应用户"只做图形完美的标的"的肉眼经验。
"""

import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCATED_CSV = PROJECT_ROOT / "tests" / "golden" / "located_signal_days.csv"

WINDOW = 60


def _znorm(arr: np.ndarray) -> np.ndarray:
    """按行 z 归一化（每个窗口减均值除标准差）。"""
    mean = arr.mean(axis=1, keepdims=True)
    std = arr.std(axis=1, keepdims=True)
    std[std == 0] = 1.0
    return (arr - mean) / std


def build_templates(stock_frames: dict[str, pd.DataFrame],
                    located_csv: Path = LOCATED_CSV) -> tuple[np.ndarray, list[str]]:
    """案例信号日前60日走势 → 模板矩阵 (n_templates, WINDOW)。

    Returns:
        (templates, labels)；labels 形如 "605318法狮龙@2026-01-05"
    """
    if not located_csv.exists():
        return np.empty((0, WINDOW)), []
    located = pd.read_csv(located_csv, dtype={"symbol": str})
    rows, labels = [], []
    for _, r in located.iterrows():
        days = str(r.get("signal_days", ""))
        if "(" not in days:
            continue
        first_day = days.split("(")[0].strip()
        sym = r["symbol"].zfill(6)
        df = stock_frames.get(sym)
        if df is None:
            continue
        dates = df["date"].astype(str).tolist()
        try:
            i = dates.index(first_day)
        except ValueError:
            continue
        if i < WINDOW:
            continue
        win = df["close"].astype(float).iloc[i - WINDOW + 1: i + 1].values
        if len(win) == WINDOW and np.isfinite(win).all():
            rows.append(win)
            labels.append(f"{sym}{r.get('name', '')}@{first_day}")
    if not rows:
        return np.empty((0, WINDOW)), []
    return _znorm(np.array(rows)), labels


def find_similar(stock_frames: dict[str, pd.DataFrame],
                 templates: np.ndarray, labels: list[str],
                 top_n: int = 30) -> pd.DataFrame:
    """全市场最近60日窗口 vs 模板库相关性匹配。

    Returns:
        DataFrame[symbol, similarity, best_case] 按相似分降序
    """
    if templates.size == 0:
        return pd.DataFrame()
    syms, wins = [], []
    for sym, df in stock_frames.items():
        c = df["close"].astype(float).tail(WINDOW).values
        if len(c) == WINDOW and np.isfinite(c).all():
            syms.append(sym)
            wins.append(c)
    if not wins:
        return pd.DataFrame()
    cand = _znorm(np.array(wins))                       # (n_stocks, W)
    corr = cand @ templates.T / WINDOW                   # 皮尔逊相关矩阵
    best_idx = corr.argmax(axis=1)
    best_val = corr.max(axis=1)
    out = pd.DataFrame({
        "symbol": syms,
        "similarity": np.round(best_val, 4),
        "best_case": [labels[i] for i in best_idx],
        "mean_top3": np.round(np.sort(corr, axis=1)[:, -3:].mean(axis=1), 4),
    })
    return out.sort_values("similarity", ascending=False).head(top_n).reset_index(drop=True)


def similar_to_symbol(target: str, stock_frames: dict[str, pd.DataFrame],
                      top_n: int = 20) -> pd.DataFrame:
    """以任意一只股票当前形态为模板找相似股（'看着像XX启动前'）。"""
    df = stock_frames.get(target)
    if df is None or len(df) < WINDOW:
        return pd.DataFrame()
    tmpl = _znorm(df["close"].astype(float).tail(WINDOW).values.reshape(1, -1))
    out = find_similar({k: v for k, v in stock_frames.items() if k != target},
                       tmpl, [target], top_n)
    return out.drop(columns=["mean_top3"], errors="ignore")
