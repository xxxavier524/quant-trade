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


def pattern_agent(df: pd.DataFrame) -> StockOpinion:
    """战法序列状态 + GBDT 胜率（与回测共源，见 patterns.py）。

    回测结论（agent_team_backtest.md）：B1 信号日无边际优势，B2 放量确认才有
    （B1→B2 序列 72.4% 胜率）——因此 B2确认=多头、B1候B2=中性等确认。
    """
    from alphapulse.agent_team.patterns import (
        pattern_state_series, pattern_conf_signed, STATE_CN)
    try:
        from alphapulse.ml.pattern_model import predict_ml_score
        ml_last = predict_ml_score(df)
    except Exception:
        ml_last = None

    state = pattern_state_series(df)
    ml_arr = None
    if ml_last is not None:
        ml_arr = np.full(len(df), np.nan)
        ml_arr[-1] = float(ml_last)
    conf_arr, signed_arr = pattern_conf_signed(state, ml_arr)
    conf, signed = float(conf_arr[-1]), float(signed_arr[-1])

    if signed > 0:
        signal = SIGNAL_BULL
    elif signed < 0:
        signal = SIGNAL_BEAR
    else:
        signal = SIGNAL_NEUTRAL
    if signed != 0:
        conf = abs(signed)      # 保证 opinion.signed() 与回测 signed 序列严格一致

    state_cn = STATE_CN[int(state[-1])]
    ev = {"state": state_cn,
          "gbdt": (round(float(ml_last), 3) if ml_last is not None else None)}
    reason = state_cn + (f"·GBDT胜率{ml_last:.2f}" if ml_last is not None else "·无ML模型")
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
