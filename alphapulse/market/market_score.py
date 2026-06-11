"""大盘诊断 v2 — 量能 + N型结构 + 知行BS点 三维评分（Phase 2b）。

用户需求（docs/trading_system.md §6）：
- 量能：成交量 vs MA20/MA60 放缩量状态（30分）
- 知行BS点：白线/黄线金叉死叉、收盘站上/跌破（40分）
- N型结构：指数级N型上涨形态（30分）

输出：综合分 0-100 + 档位 + 仓位建议。
数据：data/index/*.csv（真实指数，fetch_index_data.py 维护）。
"""

from pathlib import Path

import numpy as np
import pandas as pd

from alphapulse.factors.zhixing_trend import (
    compute_short_trend,
    compute_bull_bear_line,
    compute_macd_dif,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_DIR = PROJECT_ROOT / "data" / "index"

MAIN_INDEXES = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}


def load_index(code: str, end_date: str = "9999-12-31") -> pd.DataFrame:
    p = INDEX_DIR / f"{code}.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    return df[df["date"] <= end_date].reset_index(drop=True)


def volume_score(df: pd.DataFrame) -> tuple[float, str]:
    """量能 0-30：放量上涨最优，放量下跌最差。"""
    if len(df) < 60:
        return 15.0, "数据不足"
    vol = df["volume"].astype(float)
    close = df["close"].astype(float)
    ma20 = vol.rolling(20).mean().iloc[-1]
    ma60 = vol.rolling(60).mean().iloc[-1]
    v = vol.iloc[-1]
    up_day = close.iloc[-1] >= close.iloc[-2]

    ratio20 = v / ma20 if ma20 else 1.0
    if ratio20 >= 1.2:
        state = "放量"
        score = 25.0 if up_day else 6.0   # 放量涨=进攻，放量跌=出货
    elif ratio20 <= 0.7:
        state = "缩量"
        score = 12.0 if up_day else 16.0  # 缩量跌=惜售，缩量涨=量价背离略弱
    else:
        state = "平量"
        score = 18.0 if up_day else 12.0
    if v > ma60 and up_day:
        score = min(30.0, score + 5.0)    # 趋势级放量加成
    return round(score, 1), state


def zhixing_bs_score(df: pd.DataFrame) -> tuple[float, str]:
    """知行BS 0-40：白线vs黄线 + 收盘位置 + 近期金叉/死叉事件。"""
    if len(df) < 120:
        return 20.0, "数据不足"
    close = df["close"].astype(float)
    white = compute_short_trend(close)
    yellow = compute_bull_bear_line(close)
    dif = compute_macd_dif(close)

    score = 0.0
    notes = []
    # 白线在黄线上（趋势多头）：15分
    if white.iloc[-1] > yellow.iloc[-1]:
        score += 15
        notes.append("白>黄")
    # 收盘站上黄线：10分
    if close.iloc[-1] > yellow.iloc[-1]:
        score += 10
        notes.append("站上黄线")
    # 近5日白线金叉黄线（B点）：+10；死叉（S点）：-10
    cross_up = (white.shift(1) <= yellow.shift(1)) & (white > yellow)
    cross_dn = (white.shift(1) >= yellow.shift(1)) & (white < yellow)
    if cross_up.tail(5).any():
        score += 10
        notes.append("近5日金叉(B)")
    elif cross_dn.tail(5).any():
        score -= 10
        notes.append("近5日死叉(S)")
    # MACD DIF>0：5分
    if dif.iloc[-1] > 0:
        score += 5
        notes.append("DIF>0")
    return round(max(0.0, min(40.0, score)), 1), "+".join(notes) or "空头排列"


def n_struct_score(df: pd.DataFrame) -> tuple[float, str]:
    """N型结构 0-30：复用 N_STRUCT 因子识别指数级 N 型上涨。"""
    if len(df) < 60:
        return 15.0, "数据不足"
    try:
        from alphapulse.factors import n_struct
        sig = n_struct.compute(df)
        recent = sig.tail(10)
        if bool(recent.any()):
            return 25.0, "近10日N型确认"
        # 无N型：看60日趋势方向给基础分
        close = df["close"].astype(float)
        trend = close.iloc[-1] / close.iloc[-60] - 1
        if trend > 0.05:
            return 18.0, "上升趋势无N型"
        if trend < -0.05:
            return 6.0, "下降趋势"
        return 12.0, "横盘"
    except Exception:
        return 15.0, "计算失败"


_POSITION_ADVICE = [
    (80, "多头", "可重仓（70-90%），回踩白线加仓"),
    (60, "震荡偏多", "标准仓位（50-70%），严选强势板块"),
    (40, "震荡", "半仓以内（30-50%），快进快出"),
    (20, "震荡偏空", "轻仓（10-30%），只做最强信号"),
    (0, "空头", "空仓观望（≤10%），等待大盘B点"),
]


def compute_market_score(end_date: str = "9999-12-31") -> dict:
    """三大指数综合大盘诊断。

    Returns:
        dict: score/level/advice/detail（每指数三维分项）
    """
    per_index = {}
    scores = []
    for code, name in MAIN_INDEXES.items():
        df = load_index(code, end_date)
        if df.empty or len(df) < 60:
            continue
        v_s, v_note = volume_score(df)
        z_s, z_note = zhixing_bs_score(df)
        n_s, n_note = n_struct_score(df)
        total = v_s + z_s + n_s
        # 上证权重加倍（主导情绪）
        weight = 2.0 if code == "sh000001" else 1.0
        scores.append((total, weight))
        per_index[name] = {
            "total": round(total, 1),
            "volume": {"score": v_s, "note": v_note},
            "zhixing_bs": {"score": z_s, "note": z_note},
            "n_struct": {"score": n_s, "note": n_note},
        }
    if not scores:
        return {"score": 50.0, "level": "震荡", "advice": "指数数据缺失", "detail": {}}

    score = sum(s * w for s, w in scores) / sum(w for _, w in scores)
    for th, level, advice in _POSITION_ADVICE:
        if score >= th:
            return {"score": round(score, 1), "level": level,
                    "advice": advice, "detail": per_index}
    return {"score": round(score, 1), "level": "空头",
            "advice": _POSITION_ADVICE[-1][2], "detail": per_index}
