"""板块评分 v2 — 量能 + 板块性质 + 指数位置形态（Phase 2b）。

板块指数不依赖外部API：用 data/meta/sector_members.json（新浪成员表，每周刷新）
+ 本地日线CSV 等权聚合出板块指数（收益累积）与板块成交额，再套用与大盘/个股
一致的知行线框架评分。

输出每板块：综合分 + 分项明细 + 性质标签 + 成员个股映射（供选股联动）。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MEMBERS_FILE = PROJECT_ROOT / "data" / "meta" / "sector_members.json"
TAGS_FILE = PROJECT_ROOT / "config" / "sector_tags.json"

TAG_NAMES = {"cyclical": "顺周期", "tech": "科技", "consumer": "消费",
             "defensive": "防御", "medical": "医药", "dividend": "红利"}


def load_members() -> dict[str, list[str]]:
    """板块名 -> 成员代码列表。"""
    try:
        data = json.loads(MEMBERS_FILE.read_text())
        return {k: v["symbols"] for k, v in data["sectors"].items()}
    except Exception:
        return {}


def load_tags() -> dict[str, list[str]]:
    try:
        tags = json.loads(TAGS_FILE.read_text())
        return {k: v for k, v in tags.items() if not k.startswith("_")}
    except Exception:
        return {}


def symbol_sector_map() -> dict[str, str]:
    """个股 -> 板块名（选股联动用）。"""
    out = {}
    for sector, syms in load_members().items():
        for s in syms:
            out[s] = sector
    return out


CONCEPT_FILE = PROJECT_ROOT / "data" / "meta" / "concept_members.json"


def symbol_concept_map(max_concepts: int = 3) -> dict[str, str]:
    """个股 -> 概念标签串（最多 max_concepts 个，/分隔）。"""
    try:
        data = json.loads(CONCEPT_FILE.read_text())
    except Exception:
        return {}
    acc: dict[str, list[str]] = {}
    for concept, v in data["sectors"].items():
        for s in v["symbols"]:
            acc.setdefault(s, [])
            if len(acc[s]) < max_concepts:
                acc[s].append(concept)
    return {s: "/".join(c) for s, c in acc.items()}


def build_sector_index(symbols: list[str], stock_frames: dict[str, pd.DataFrame],
                       lookback: int = 250) -> pd.DataFrame | None:
    """等权聚合板块指数：日均收益累积为净值 + 成交额合计。

    Args:
        symbols: 板块成员
        stock_frames: {symbol: 日线df}（由调用方一次性加载共享，避免重复IO）
    """
    rets, amts = [], []
    for sym in symbols:
        df = stock_frames.get(sym)
        if df is None or len(df) < 60:
            continue
        tail = df.tail(lookback)
        r = tail.set_index("date")["close"].astype(float).pct_change()
        rets.append(r)
        if "amount" in tail.columns:
            amts.append(tail.set_index("date")["amount"].astype(float))
    if len(rets) < 5:
        return None
    ret_df = pd.concat(rets, axis=1)
    mean_ret = ret_df.mean(axis=1, skipna=True)
    nav = (1 + mean_ret.fillna(0)).cumprod()
    amount = pd.concat(amts, axis=1).sum(axis=1, skipna=True) if amts else pd.Series(dtype=float)
    out = pd.DataFrame({"close": nav, "amount": amount}).dropna(subset=["close"])
    return out.reset_index().rename(columns={"index": "date"})


def _score_sector(idx: pd.DataFrame, n_members: int) -> dict:
    """单板块评分：量能25 + 短期动量25 + 知行位置形态50。"""
    close = idx["close"].astype(float)
    score = 0.0
    notes = []

    # 量能（成交额 vs MA20）
    if "amount" in idx.columns and idx["amount"].notna().sum() > 25:
        amt = idx["amount"].astype(float)
        ratio = amt.iloc[-1] / amt.rolling(20).mean().iloc[-1]
        up = close.iloc[-1] >= close.iloc[-2]
        if ratio >= 1.2 and up:
            score += 22; notes.append("放量上攻")
        elif ratio >= 1.2:
            score += 6; notes.append("放量下跌")
        elif ratio <= 0.7:
            score += 12; notes.append("缩量")
        else:
            score += 14; notes.append("平量")
    else:
        score += 12

    # 动量（5日/20日收益）
    if len(close) > 21:
        r5 = close.iloc[-1] / close.iloc[-6] - 1
        r20 = close.iloc[-1] / close.iloc[-21] - 1
        score += float(np.clip(12.5 + r5 * 250, 0, 12.5))
        score += float(np.clip(12.5 + r20 * 125, 0, 12.5))
        if r5 > 0.02:
            notes.append(f"5日+{r5*100:.1f}%")

    # 知行位置与形态（白/黄线框架，与个股一致）
    if len(close) >= 120:
        white = compute_short_trend(close)
        yellow = compute_bull_bear_line(close)
        if white.iloc[-1] > yellow.iloc[-1]:
            score += 20; notes.append("白>黄")
        if close.iloc[-1] > yellow.iloc[-1]:
            score += 15
        cross_up = (white.shift(1) <= yellow.shift(1)) & (white > yellow)
        if cross_up.tail(5).any():
            score += 15; notes.append("近5日板块B点")
    else:
        score += 25

    return {"score": round(min(100.0, score), 1), "note": "+".join(notes), "members": n_members}


def rank_sectors(stock_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """全部板块评分排名。

    Args:
        stock_frames: {symbol: 日线df}，与 daily_screener 共享加载结果

    Returns:
        DataFrame[sector, score, tags, note, members] 按分降序
    """
    members = load_members()
    tags = load_tags()
    rows = []
    for sector, syms in members.items():
        idx = build_sector_index(syms, stock_frames)
        if idx is None:
            continue
        r = _score_sector(idx, len(syms))
        tag_cn = "/".join(TAG_NAMES.get(t, t) for t in tags.get(sector, []))
        rows.append({"sector": sector, "tags": tag_cn, **r})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    return df[["rank", "sector", "score", "tags", "note", "members"]]
