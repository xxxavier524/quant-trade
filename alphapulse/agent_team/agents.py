"""agent team 四个信息角色（纯函数，复用现有确定性模块）。

- data_agent：数据健康守门
- factor_agent：11 子分数加权 + 严格信号徽章（B1/量能B1/知行超短/单针下三十）
- pattern_agent：当前战法态（近端 B1/量能B1/单针信号）+ GBDT 胜率
- sector_agent：板块相对强弱 + 概念热度 + 大盘档位

聚合角色见 portfolio.py。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphapulse.agent_team.contract import (
    StockOpinion, SIGNAL_BULL, SIGNAL_BEAR, SIGNAL_NEUTRAL)

_OHLCV = ["open", "high", "low", "close", "volume"]


def data_agent(df: pd.DataFrame | None) -> StockOpinion:
    """数据健康守门：行数≥120 且近 60 日 OHLCV 无缺损 → 健康。"""
    n = 0 if df is None else len(df)
    healthy = (
        df is not None and n >= 120
        and all(c in df.columns for c in _OHLCV)
        and not df[_OHLCV].tail(60).isna().any().any()
    )
    if healthy:
        return StockOpinion("data", SIGNAL_NEUTRAL, 100.0, {"rows": n}, f"数据充足({n}行)")
    return StockOpinion("data", SIGNAL_BEAR, 0.0, {"rows": n}, f"数据不足/缺损({n}行)")


def factor_agent(df: pd.DataFrame) -> StockOpinion:
    """11 子分数加权(复用 composite 权重) + 严格信号徽章。"""
    from alphapulse.ranking.sub_scores import compute_sub_scores
    from alphapulse.ranking.composite import load_weights
    from alphapulse.factors import b1_formula, volume_b1, zhixing_trend
    from alphapulse.strategies import needle

    subs = compute_sub_scores(df)
    if not subs:
        return StockOpinion("factor", SIGNAL_NEUTRAL, 0.0, {}, "子分数不可用(历史不足)")

    w = load_weights()
    num = sum(w[k] * subs[k] for k in w if k in subs)
    den = sum(w[k] for k in w if k in subs) or 1.0
    conf = round(100.0 * num / den, 1)

    sigs: list[str] = []
    try:
        if bool(b1_formula.compute(df).iloc[-1]):
            sigs.append("B1")
        if bool(volume_b1.compute(df).iloc[-1]):
            sigs.append("量能B1")
        if bool(zhixing_trend.compute_ultra(df).iloc[-1]):
            sigs.append("知行超短")
        if bool(needle.compute(df).iloc[-1]):
            sigs.append("单针下三十")
    except Exception:
        pass

    if sigs:
        conf = max(conf, 60.0)          # 触发原始公式 → 至少中高置信
        signal = SIGNAL_BULL
    elif conf >= 55.0:
        signal = SIGNAL_BULL
    elif conf < 35.0:
        signal = SIGNAL_BEAR
    else:
        signal = SIGNAL_NEUTRAL

    top = sorted(subs.items(), key=lambda kv: -kv[1])[:3]
    ev = {"factor_score": conf, "strict_signals": sigs, "sub_top": dict(top)}
    reason = (f"因子分{conf:.0f}"
              + (f"·严格信号[{'+'.join(sigs)}]" if sigs else "")
              + "·强项:" + "/".join(k for k, _ in top))
    return StockOpinion("factor", signal, conf, ev, reason)


def pattern_agent(df: pd.DataFrame, b2_wait: int = 5, recent: int = 6) -> StockOpinion:
    """当前战法态 + GBDT 胜率。

    近端 B1/量能B1 买点 → B1买点(新)/B1候B2；近端单针 → 单针探底；
    置信度用 GBDT predict_ml_score（缺模型时按战法态定性）。
    """
    from alphapulse.factors import b1_formula, volume_b1
    from alphapulse.strategies import needle
    try:
        from alphapulse.ml.pattern_model import predict_ml_score
        ml = predict_ml_score(df)
    except Exception:
        ml = None

    try:
        b1 = b1_formula.compute(df).fillna(False)
    except Exception:
        b1 = pd.Series(False, index=df.index)
    try:
        vb1 = volume_b1.compute(df).fillna(False)
    except Exception:
        vb1 = pd.Series(False, index=df.index)
    try:
        nd = needle.compute(df).fillna(False)
    except Exception:
        nd = pd.Series(False, index=df.index)

    buy_idx = np.flatnonzero((b1 | vb1).values)
    last_buy = (len(df) - 1 - int(buy_idx[-1])) if len(buy_idx) else None
    needle_recent = bool(nd.tail(recent).any())

    if last_buy is not None and last_buy <= 1:
        state = "B1买点(新)"
    elif last_buy is not None and last_buy <= b2_wait:
        state = "B1候B2"
    elif needle_recent:
        state = "单针探底"
    else:
        state = "无明确战法态"
    bullish_state = state != "无明确战法态"

    if ml is not None:
        conf = round(float(ml) * 100.0, 1)
    else:
        conf = 60.0 if bullish_state else 40.0

    if bullish_state and conf >= 50.0:
        signal = SIGNAL_BULL
    elif (not bullish_state) and ml is not None and ml < 0.35:
        signal = SIGNAL_BEAR
    else:
        signal = SIGNAL_NEUTRAL

    ev = {"state": state, "bars_since_buy": last_buy,
          "gbdt": (round(float(ml), 3) if ml is not None else None)}
    reason = state + (f"·GBDT胜率{ml:.2f}" if ml is not None else "·无ML模型")
    return StockOpinion("pattern", signal, conf, ev, reason)


def sector_agent(symbol: str, ctx) -> StockOpinion:
    """板块相对强弱 + 概念热度 + 大盘档位。"""
    sector = ctx.sector_map.get(symbol, "")
    sscore = ctx.sector_scores.get(sector)
    concepts = ctx.concept_map.get(symbol, "")
    macro = ctx.macro_level
    macro_bear = "空" in str(macro)

    base = sscore if sscore is not None else ctx.macro_score
    conf = round(float(base), 1)

    if sscore is not None and sscore >= 60.0 and not macro_bear:
        signal = SIGNAL_BULL
    elif sscore is not None and sscore < 35.0:
        signal = SIGNAL_BEAR
    elif macro_bear:
        signal = SIGNAL_BEAR
    else:
        signal = SIGNAL_NEUTRAL

    ev = {"sector": sector, "sector_score": sscore,
          "concepts": concepts, "macro_level": macro}
    reason = (f"板块[{sector or '—'}]"
              + (f"{sscore:.0f}分" if sscore is not None else "无评分")
              + f"·大盘{macro}"
              + (f"·概念:{concepts}" if concepts else ""))
    return StockOpinion("sector", signal, conf, ev, reason)
