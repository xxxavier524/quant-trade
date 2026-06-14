"""投资判断 — B1概念挖掘 + 产业链/位置分析 + DeepSeek投研（用户需求 2026-06-12）。

回答"当下选到的B1都是什么概念"，挖掘上下游产业链、概念低位、催化因素。
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from alphapulse.ui import style as S

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
REPORTS_DIR = PROJECT_ROOT / "reports"


@st.cache_data(ttl=300)
def _screen():
    files = sorted(REPORTS_DIR.glob("screen_*.csv"))
    if not files:
        return "", pd.DataFrame()
    return files[-1].stem.replace("screen_", ""), pd.read_csv(files[-1], dtype={"symbol": str})


@st.cache_data(ttl=600, show_spinner="聚合概念位置...")
def _enriched(date: str):
    from alphapulse.analysis.concept_miner import b1_concept_distribution, enrich_concepts
    from alphapulse.config.settings import DATA_DIR
    _, df = _screen()
    dist = b1_concept_distribution(df)
    if dist.empty:
        return pd.DataFrame()
    return enrich_concepts(dist, DATA_DIR, top_k=10)


@st.cache_data(ttl=300)
def _macro():
    try:
        from alphapulse.market.market_score import compute_market_score
        m = compute_market_score()
        return f"{m['score']:.0f}/100 [{m['level']}] {m['advice']}"
    except Exception:
        return ""


def _level_chip(level: str) -> str:
    color = {"低位": S.DOWN, "中位": S.YELLOW, "高位": S.UP}.get(level, S.MUTED)
    flag = {"低位": "🟢 低位", "中位": "🟡 中位", "高位": "🔴 高位"}.get(level, level)
    return f'<span style="color:{color};font-weight:600">{flag}</span>'


def render():
    date, df = _screen()
    if df.empty:
        st.info("暂无选股结果 — 运行 `python scripts/daily_screener.py`")
        return

    st.markdown("##### 投资判断 · B1 概念挖掘与产业链分析")
    st.caption(f"数据日 {date} · 回答「当下选到的 B1 都是什么概念」→ 挖掘产业链上下游、概念低位、催化因素")

    enr = _enriched(date)
    if enr.empty:
        st.warning("当日 B1 信号股缺少概念标注（运行 fetch_sector_data.py --concepts 补全概念成员表）")
        return

    # ── 概念分布 + 位置表 ──
    n_low = int((enr["level"] == "低位").sum())
    n_b1 = int(enr["n_stocks"].sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("热点概念数", f"{len(enr)}")
    m2.metric("B1 概念命中(去重前)", f"{n_b1}")
    m3.metric("低位概念", f"{n_low}", help="低位+B1共振=底部启动最优组合")

    st.markdown("**概念分布与量化位置**（B1是底部买点，低位概念里价值最高）")
    show = enr.copy()
    show["位置"] = show["level"]
    show["黄线"] = show["above_yellow"].map({True: "站上", False: "下方"}).fillna("—")
    disp = show[["concept", "n_stocks", "avg_score", "位置", "pct_in_range",
                 "mom_20", "黄线", "stocks"]]
    st.dataframe(
        disp, hide_index=True, use_container_width=True, height=320,
        column_config={
            "concept": "概念", "n_stocks": st.column_config.NumberColumn("B1数", width="small"),
            "avg_score": st.column_config.NumberColumn("均分", format="%.0f"),
            "位置": st.column_config.TextColumn("位置", width="small"),
            "pct_in_range": st.column_config.ProgressColumn("250日区间分位", min_value=0, max_value=100, format="%.0f%%"),
            "mom_20": st.column_config.NumberColumn("20日%", format="%.1f"),
            "黄线": st.column_config.TextColumn("黄线", width="small"),
            "stocks": st.column_config.TextColumn("成分B1股", width="large"),
        })

    # 底部优选速览
    low = enr[enr["level"] == "低位"].sort_values("n_stocks", ascending=False)
    if not low.empty:
        chips = " ".join(
            f'<span class="ap-tag" style="border-color:{S.DOWN};color:{S.DOWN}">{r["concept"]}({r["n_stocks"]}只)</span>'
            for _, r in low.head(5).iterrows())
        S.card(f'<div class="ap-kpi-label">🟢 底部启动优选（低位 + B1 共振）</div>'
               f'<div style="margin-top:6px">{chips}</div>')

    # ── DeepSeek 产业链投研 ──
    st.divider()
    from alphapulse.llm.client import is_configured
    cc1, cc2 = st.columns([1, 3])
    gen = cc1.button("🧠 生成产业链投研判断", type="primary")
    if not is_configured():
        cc2.caption("未配置 DEEPSEEK_API_KEY：仅规则版位置摘要；配置后启用产业链上下游/催化深度分析")

    key = f"judge_{date}"
    if gen:
        from alphapulse.analysis.concept_miner import analyze_concepts
        with st.spinner("DeepSeek 产业链分析中（约15秒）..."):
            st.session_state[key] = analyze_concepts(enr, macro=_macro())
    if key in st.session_state:
        S.card(f'<div class="ap-kpi-label">投研判断 · {date}</div>')
        st.markdown(st.session_state[key])
    elif not is_configured():
        from alphapulse.analysis.concept_miner import _rule_based_summary
        st.markdown(_rule_based_summary(enr))
