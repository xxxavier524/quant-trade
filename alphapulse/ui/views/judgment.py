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


def _run_team(date: str, df: pd.DataFrame, top_n: int, debate: bool):
    """进程内跑 agent team（Top-N），返回 verdicts。"""
    from alphapulse.agent_team import build_context, analyze_batch
    from alphapulse.config.settings import DATA_DIR
    from replay_screen import load_stock

    data_dir = Path(DATA_DIR)
    local_day = PROJECT_ROOT / "data" / "day"
    items = []
    for _, r in df.head(top_n).iterrows():
        sym = str(r["symbol"])
        name = str(r.get("name", "") or "")
        if name == "nan":
            name = ""
        csv = data_dir / f"{sym}.csv"
        if not csv.exists():
            csv = local_day / f"{sym}.csv"
        d = load_stock(csv, "9999-12-31", min_rows=120) if csv.exists() else None
        items.append((sym, name, d))
    ctx = build_context()
    return analyze_batch(items, ctx, debate=debate), ctx


def _agent_team_section(date: str, df: pd.DataFrame):
    """Agent Team 多角色研判区（阶段二）。"""
    from alphapulse.llm.client import is_configured

    st.markdown("##### 🤖 Agent Team 多角色研判")
    st.caption("数据/因子/形态/板块 四角色 → 组合经理聚合评级；高分标的可加 DeepSeek 多空辩论")
    c1, c2, c3 = st.columns([1, 1, 3])
    run_quick = c1.button("运行研判(纯量化)")
    run_debate = c2.button("运行研判(含辩论)", type="primary",
                           disabled=not is_configured(),
                           help="团队分≥65标的跑 Bull/Bear/仲裁(v4-pro)+贝叶斯融合,约¥0.3/股")
    if not is_configured():
        c3.caption("未配置 DEEPSEEK_API_KEY，辩论不可用")

    key = f"team_{date}"
    if run_quick or run_debate:
        with st.spinner("agent team 分析中..."):
            verdicts, ctx = _run_team(date, df, top_n=10, debate=run_debate)
        st.session_state[key] = verdicts

    verdicts = st.session_state.get(key)
    if not verdicts:
        return
    ok = sorted([v for v in verdicts if v.ok], key=lambda v: v.score, reverse=True)
    rows = []
    for v in ok:
        ref = next((op for op in v.opinions if op.agent == "referee"), None)
        rows.append({
            "评级": v.rating, "代码": v.symbol, "名称": v.name,
            "团队分": v.score, "仓位%": v.meta.get("position_pct", 0.0),
            "辩论": (f"{ref.signal[:4]}·{ref.confidence:.0f}" if ref else "—"),
            "摘要": v.reasoning})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                 column_config={"团队分": st.column_config.ProgressColumn(
                     "团队分", min_value=0, max_value=100, format="%.0f")})
    for v in ok:
        with st.expander(f"{v.rating} · {v.symbol} {v.name} — 团队分 {v.score:.0f}"):
            for op in v.opinions:
                if op.agent == "referee":
                    st.markdown(f"**多方** {op.evidence.get('bull','')}")
                    st.markdown(f"**空方** {op.evidence.get('bear','')}")
                    st.markdown(f"**仲裁** [{op.signal} {op.confidence:.0f}] {op.reasoning}"
                                f"（P0 {op.evidence['p0_score']:.0f}→融合 {v.score:.0f}）")
                else:
                    st.markdown(f"**{op.agent}** [{op.signal} {op.confidence:.0f}] {op.reasoning}")
    st.divider()


def render():
    date, df = _screen()
    if df.empty:
        st.info("暂无选股结果 — 运行 `python scripts/daily_screener.py`")
        return

    _agent_team_section(date, df)

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
