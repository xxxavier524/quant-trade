"""综合评分 — 子分数加权汇总 + 全市场排序（Phase 2 核心管线）。

流程：
1. build_factor_frame: 每只股票 → 一行子分数 + 严格信号徽章（B1/量能B1/知行超短）
2. load_weights: config/factor_weights.json 的 B1_SCORE 权重（用户可改）
3. rank_all: 调用 stock_ranker.rank_stocks 做 winsorize→zscore→加权→0-100
"""

import json
from pathlib import Path

import pandas as pd

from alphapulse.factors import b1_formula, volume_b1, zhixing_trend
from alphapulse.strategies import needle
from alphapulse.ranking.stock_ranker import rank_stocks
from alphapulse.ranking.sub_scores import compute_sub_scores

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WEIGHTS_FILE = PROJECT_ROOT / "config" / "factor_weights.json"

# 种子权重（Phase 3 信号验证产出 IC 后由 FactorWeighter 自动调优）
DEFAULT_WEIGHTS = {
    "j_low": 0.18,
    "trend_gap": 0.16,
    "vol_shrink": 0.13,
    "yangyin": 0.12,
    "surge": 0.10,
    "dif": 0.08,
    "ql_pos": 0.08,
    "pct_calm": 0.05,
    "amplitude": 0.04,
    "bowl": 0.04,            # 掉进碗里（增强）
    "washout_recover": 0.02,  # 单针回收（增强）
    "ml_score": 0.15,        # GBDT形态胜率分（模型缺失时该列不存在，自动忽略）
    "ma_bull": 0.05,         # 日线均线多头排列
    "weekly_cross": 0.08,    # 周线M5上穿M14（B1加强，用户需求）
}


def load_weights(strategy: str = "B1_SCORE") -> dict[str, float]:
    """读取权重；缺失时写入种子权重并返回。"""
    try:
        cfg = json.loads(WEIGHTS_FILE.read_text())
    except Exception:
        cfg = {"weights": {}, "ic_history": {}}
    weights = cfg.get("weights", {}).get(strategy)
    if not weights:
        cfg.setdefault("weights", {})[strategy] = DEFAULT_WEIGHTS
        WEIGHTS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        return dict(DEFAULT_WEIGHTS)
    return weights


def build_stock_row(symbol: str, name: str, data: pd.DataFrame) -> dict | None:
    """单只股票：子分数 + 严格信号徽章 + 快照字段。"""
    subs = compute_sub_scores(data)
    if not subs:
        return None
    row = {"symbol": symbol, "name": name, **subs}
    # ML形态胜率分（模型存在时）
    try:
        from alphapulse.ml.pattern_model import predict_ml_score
        ml = predict_ml_score(data)
        if ml is not None:
            row["ml_score"] = ml
    except Exception:
        pass
    # 严格信号徽章（原始通达信公式，全条件AND）
    try:
        row["sig_b1"] = bool(b1_formula.compute(data).iloc[-1])
        row["sig_volume_b1"] = bool(volume_b1.compute(data).iloc[-1])
        row["sig_zhixing"] = bool(zhixing_trend.compute_ultra(data).iloc[-1])
        row["sig_needle"] = bool(needle.compute(data).iloc[-1])
    except Exception:
        row["sig_b1"] = row["sig_volume_b1"] = row["sig_zhixing"] = False
        row["sig_needle"] = False
    # 战法序列状态（回测证明 B2确认 才是优势所在，B1候B2=等确认——直接展示给用户）
    try:
        from alphapulse.agent_team.patterns import pattern_state_series, STATE_CN
        row["pattern_state"] = STATE_CN[int(pattern_state_series(data)[-1])]
    except Exception:
        row["pattern_state"] = ""
    row["close"] = round(float(data["close"].iloc[-1]), 2)
    prev = float(data["close"].iloc[-2]) if len(data) > 1 else None
    row["pct_change"] = round((row["close"] / prev - 1) * 100, 2) if prev else 0.0
    # 股价相对黄线（知行多空线）位置——硬过滤依据（用户需求：选股必须价在黄线上）
    try:
        yellow = zhixing_trend.compute_bull_bear_line(data["close"]).iloc[-1]
        row["yellow_line"] = round(float(yellow), 2) if pd.notna(yellow) else None
        row["above_yellow"] = bool(row["close"] > yellow) if pd.notna(yellow) else False
    except Exception:
        row["yellow_line"], row["above_yellow"] = None, False
    if "market_cap" in data.columns:
        mv = data["market_cap"].iloc[-1]
        row["float_mv_yi"] = round(float(mv) / 1e8, 1) if pd.notna(mv) else None
    return row


def rank_all(factor_df: pd.DataFrame, top_n: int = 50,
             macro_level: str = "震荡",
             sector_map: dict | None = None,
             require_above_yellow: bool = True,
             weights: dict | None = None) -> pd.DataFrame:
    """全市场加权排序，输出 Top N 并附子分数明细与徽章。

    Args:
        require_above_yellow: 硬过滤，只保留股价站上黄线（知行多空线）的票（用户铁律）
        weights: 覆盖权重；None 则读 config（GUI 交互调参时传入）
    """
    if weights is None:
        weights = load_weights()
    # 硬过滤：股价必须在黄线之上（多头趋势中的回调买点，不抄底破位股）
    if require_above_yellow and "above_yellow" in factor_df.columns:
        factor_df = factor_df[factor_df["above_yellow"]].reset_index(drop=True)
    if factor_df.empty:
        return pd.DataFrame()
    ranked = rank_stocks(
        factor_df, weights,
        sector_strength_map=sector_map,
        macro_level=macro_level,
        top_pct=1.0,
    )
    if ranked.empty:
        return ranked
    # 严格信号股加显式加成：满足原始公式的排前（评分同档时优先）
    # 排除 ranked 已有的列，避免 merge 产生 _x/_y 冲突
    detail_cols = [c for c in factor_df.columns
                   if c not in ranked.columns and c != "symbol"]
    merged = ranked.merge(factor_df[["symbol"] + detail_cols], on="symbol", how="left")
    badge_cols = [c for c in ["sig_b1", "sig_volume_b1", "sig_zhixing", "sig_needle"]
                  if c in merged.columns]
    merged["strict_signal"] = merged[badge_cols].any(axis=1)
    merged = merged.sort_values(["strict_signal", "score"],
                                ascending=[False, False]).reset_index(drop=True)
    merged["rank"] = range(1, len(merged) + 1)
    return merged.head(top_n)
