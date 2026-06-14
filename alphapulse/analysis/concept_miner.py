"""投资判断 — B1信号股的概念挖掘 + 产业链/位置分析（用户需求 2026-06-12）。

核心问题："当下选到的 B1 都是什么概念？" → 通过挖掘上下游产业链、概念指数低位、
催化因素，给出投资判断。结合量化位置数据 + DeepSeek 金融分析。

流程：
1. b1_concept_distribution: 聚合当日 B1/严格信号股的概念分布 → 热点概念排名
2. concept_position: 用本地聚合的概念指数K线算位置（区间百分位/相对黄线/动量/形态）
3. analyze_concepts: 把"概念+成分B1股+量化位置"喂给 DeepSeek，
   产出产业链上下游、位置研判、催化因素、投资结论（equity-research 框架）
"""

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def b1_concept_distribution(screen_df: pd.DataFrame, min_count: int = 1) -> pd.DataFrame:
    """当日 B1/严格信号股的概念分布。

    Returns:
        DataFrame[concept, n_stocks, stocks(代码名称串), avg_score] 按命中数降序
    """
    if screen_df.empty:
        return pd.DataFrame()
    sig_col = "sig_b1" if "sig_b1" in screen_df.columns else "strict_signal"
    b1 = screen_df[screen_df.get(sig_col, False) == True]  # noqa: E712
    if b1.empty:
        b1 = screen_df  # 无严格信号时退化为全体Top
    rows = {}
    for _, r in b1.iterrows():
        concepts = str(r.get("concepts", "") or "")
        if not concepts or concepts == "nan":
            continue
        label = f"{r['symbol']}{str(r.get('name','')) if str(r.get('name','')) != 'nan' else ''}"
        for c in concepts.split("/"):
            c = c.strip()
            if not c:
                continue
            rows.setdefault(c, {"stocks": [], "scores": []})
            rows[c]["stocks"].append(label)
            rows[c]["scores"].append(float(r.get("score", 0)))
    out = []
    for c, v in rows.items():
        if len(v["stocks"]) >= min_count:
            out.append({"concept": c, "n_stocks": len(v["stocks"]),
                        "stocks": " ".join(v["stocks"]),
                        "avg_score": round(float(np.mean(v["scores"])), 1)})
    df = pd.DataFrame(out)
    if df.empty:
        return df
    return df.sort_values(["n_stocks", "avg_score"], ascending=False).reset_index(drop=True)


def concept_position(concept: str, data_dir: Path | str, kind: str = "auto") -> dict:
    """概念指数当前位置量化（本地聚合K线，不依赖外部API）。

    Returns:
        dict: pct_in_range(250日区间百分位)/above_yellow/mom_20/mom_60/shape/level
    """
    from alphapulse.market.sector_score import board_index_kline
    from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line

    idx = board_index_kline(concept, Path(data_dir), kind=kind, lookback=250)
    if idx is None or len(idx) < 60:
        return {"available": False}
    close = idx["close"].astype(float)
    cur = float(close.iloc[-1])
    lo, hi = float(close.min()), float(close.max())
    pct_in_range = round((cur - lo) / (hi - lo) * 100, 0) if hi > lo else 50
    mom_20 = round((cur / float(close.iloc[-21]) - 1) * 100, 1) if len(close) > 21 else 0.0
    mom_60 = round((cur / float(close.iloc[-61]) - 1) * 100, 1) if len(close) > 61 else 0.0

    above_yellow = None
    if len(close) >= 120:
        white = compute_short_trend(close)
        yellow = compute_bull_bear_line(close)
        above_yellow = bool(white.iloc[-1] > yellow.iloc[-1] and cur > yellow.iloc[-1])

    if pct_in_range <= 35:
        level = "低位"
    elif pct_in_range <= 65:
        level = "中位"
    else:
        level = "高位"
    # 形态简判
    if mom_20 > 5 and mom_60 > 0:
        shape = "上行"
    elif mom_20 < -5:
        shape = "下行"
    else:
        shape = "横盘"
    return {"available": True, "pct_in_range": pct_in_range, "level": level,
            "above_yellow": above_yellow, "mom_20": mom_20, "mom_60": mom_60,
            "shape": shape, "cur": round(cur, 1)}


def enrich_concepts(dist_df: pd.DataFrame, data_dir: Path | str,
                    top_k: int = 8) -> pd.DataFrame:
    """给概念分布表附上量化位置（取前 top_k 个热点概念）。"""
    if dist_df.empty:
        return dist_df
    head = dist_df.head(top_k).copy()
    pos = head["concept"].apply(lambda c: concept_position(c, data_dir))
    head["level"] = pos.apply(lambda p: p.get("level", "—"))
    head["pct_in_range"] = pos.apply(lambda p: p.get("pct_in_range"))
    head["mom_20"] = pos.apply(lambda p: p.get("mom_20"))
    head["above_yellow"] = pos.apply(lambda p: p.get("above_yellow"))
    head["shape"] = pos.apply(lambda p: p.get("shape", "—"))
    return head


ANALYSIS_SYSTEM = """你是资深A股行业研究员，擅长产业链分析与主题投资。
用户的量化系统当日筛出一批 B1 底部买点信号股（B1 = 超跌缩量+站上知行黄线的底部启动买点），
按所属概念聚类。请你对每个热点概念做一份精炼的投研判断。

分析框架（每个概念≤180字，务实不空话）：
1. **产业链定位**：该概念在产业链的上/中/下游，核心环节与代表公司类型
2. **位置研判**：结合给出的量化位置数据（区间百分位/动量/是否站上黄线），判断
   当前是底部启动、中继、还是高位——B1信号在低位概念里价值最高
3. **催化与逻辑**：当前时点该概念的潜在催化（政策/景气/事件），以及风险
4. **操作建议**：结合B1信号股，给出"重点关注/谨慎/回避"的明确倾向

只基于给出的数据和你的行业知识，不编造具体数字。输出 markdown。"""


def build_analysis_prompt(enriched: pd.DataFrame, macro: str = "") -> str:
    lines = [f"当前大盘环境：{macro or '未知'}\n", "当日 B1 信号股的概念分布与量化位置：\n"]
    for _, r in enriched.iterrows():
        ay = "站上黄线" if r.get("above_yellow") else ("黄线下" if r.get("above_yellow") is False else "—")
        lines.append(
            f"- **{r['concept']}**：{r['n_stocks']}只B1（均分{r['avg_score']}）| "
            f"概念指数位置 {r.get('level','—')}（区间{r.get('pct_in_range','—')}%分位，"
            f"20日动量{r.get('mom_20','—')}%，{r.get('shape','—')}，{ay}）| "
            f"成分：{r['stocks'][:60]}")
    lines.append("\n请按框架逐个概念分析，并在最后给出【今日主题优选】1-2个最值得关注的概念及理由。")
    return "\n".join(lines)


def analyze_concepts(enriched: pd.DataFrame, macro: str = "",
                     model: str | None = None) -> str:
    """调用 DeepSeek 产出投研判断（未配置KEY则返回规则版摘要）。"""
    from alphapulse.llm.client import is_configured, chat, MODEL_REASONING
    if enriched.empty:
        return "_当日无 B1 概念可分析_"
    if not is_configured():
        return _rule_based_summary(enriched)
    prompt = build_analysis_prompt(enriched, macro)
    try:
        return chat(prompt, system=ANALYSIS_SYSTEM,
                    model=model or MODEL_REASONING, temperature=0.4, max_tokens=3000)
    except Exception as e:
        return f"_LLM 分析失败（{e}），以下为规则版摘要：_\n\n" + _rule_based_summary(enriched)


def _rule_based_summary(enriched: pd.DataFrame) -> str:
    """无 LLM 时的规则版位置摘要。"""
    low = enriched[enriched["level"] == "低位"]
    lines = ["### 概念位置速览（规则版，配置 DEEPSEEK_API_KEY 启用深度产业链分析）\n"]
    for _, r in enriched.iterrows():
        flag = "🟢低位B1" if r["level"] == "低位" else ("🟡中位" if r["level"] == "中位" else "🔴高位")
        lines.append(f"- **{r['concept']}** {flag} · {r['n_stocks']}只 · "
                     f"区间{r.get('pct_in_range','—')}%分位 · 20日{r.get('mom_20','—')}%")
    if not low.empty:
        lines.append(f"\n**底部启动优选**（低位+B1共振）：{', '.join(low['concept'].head(3))}")
    return "\n".join(lines)
