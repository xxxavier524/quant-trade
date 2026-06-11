"""研究优化区 — 信号复盘 / 信号验证 / 参数搜索 / ML形态 / AI工具。

不打扰日常看板与选股；所有"让系统变得更好"的工作都在这里。
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from alphapulse.ui import style as S

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
REPORTS_DIR = PROJECT_ROOT / "reports"
RESULTS_DIR = PROJECT_ROOT / "backtest_results"


@st.cache_data(ttl=600, show_spinner="加载样本股票池（首次约1分钟）...")
def _universe(sample: int) -> dict:
    from validate_signal import load_universe
    from alphapulse.config.settings import DATA_DIR
    return load_universe(Path(DATA_DIR), sample, "9999-12-31")


# ──────────────────────────── 信号复盘（追踪闭环）────────────────────────────

def _review():
    from alphapulse.tracking import signal_tracker as tk
    st.markdown("##### 信号复盘 · 近一周跟踪")
    st.caption("每日Top50入库 → 跟踪7日逐日表现 → 连涨≥2天归因 → 沉淀为因子/ML强化样本")

    c1, c2 = st.columns([1, 4])
    if c1.button("更新追踪数据"):
        from alphapulse.config.settings import DATA_DIR
        for csv in sorted(REPORTS_DIR.glob("screen_*.csv")):
            tk.record_signals(csv)
        n = tk.update_performance(Path(DATA_DIR))
        st.toast(f"回填 {n} 条表现")
        st.cache_data.clear()

    rep = tk.weekly_report()
    if rep.empty:
        S.card('<div class="ap-sub">暂无追踪数据，先运行选股再点击更新</div>')
        return
    n_streak = int((rep["streak"] >= 2).sum())
    win1 = (rep.get("d1", pd.Series(dtype=float)) > 0).mean() * 100
    m1, m2, m3 = st.columns(3)
    m1.metric("跟踪信号", f"{len(rep)} 条")
    m2.metric("次日红盘率", f"{win1:.0f}%")
    m3.metric("连涨≥2天", f"{n_streak} 条")

    day_cols = [c for c in rep.columns if c.startswith("d") and c[1:].isdigit()]
    show = rep[["date", "symbol", "name", "score", "streak", "cum_pct"] + day_cols].head(30)
    st.dataframe(show, hide_index=True, use_container_width=True, height=380,
                 column_config={
                     "date": "信号日", "symbol": "代码", "name": "名称",
                     "score": st.column_config.NumberColumn("分", format="%.0f"),
                     "streak": st.column_config.NumberColumn("连涨", format="%d天"),
                     "cum_pct": st.column_config.NumberColumn("累计%", format="%.1f"),
                     **{c: st.column_config.NumberColumn(c.replace("d", "第") + "日",
                                                         format="%.1f") for c in day_cols}})

    if st.button("连涨归因 + 因子沉淀（DeepSeek）", type="primary"):
        with st.spinner("归因分析中..."):
            r = tk.distill_streaks(use_llm=True)
        if r.get("n", 0) == 0:
            st.info(r.get("message", "无连涨标的"))
        else:
            st.success(f"{r['n']} 只连涨标的已标记为ML强化样本（下次训练自动加权）")
            st.markdown("**特征偏移**（连涨组相对全体）: " + " · ".join(
                f"{k} +{v}" for k, v in r.get("trait_lift", {}).items()))
            if r.get("llm_summary"):
                S.card(f'<div style="font-size:13px;white-space:pre-wrap">{r["llm_summary"]}</div>')
                st.caption("可把上面的量化条件粘贴到『AI工具』生成因子并验证")


# ──────────────────────────── 信号验证 ────────────────────────────

def _validate():
    from alphapulse.factors.factor_registry import FACTOR_REGISTRY
    names = sorted(FACTOR_REGISTRY.keys())
    c1, c2, c3 = st.columns([2, 1, 1])
    factor = c1.selectbox("因子/公式", names, index=names.index("B1_FORMULA"))
    sample = c2.selectbox("样本数", [200, 500, 1000], index=0)
    params_str = c3.text_input("参数覆盖(JSON)", value="")
    st.caption(f"默认参数: {FACTOR_REGISTRY[factor].get('default_params', {})}")

    if st.button("运行验证", type="primary"):
        from alphapulse.backtest.signal_validator import validate_signal
        params = json.loads(params_str) if params_str.strip() else None
        stocks = _universe(sample)
        with st.spinner("回放全历史信号..."):
            r = validate_signal(factor, stocks, params)
        if r.get("n_signals", 0) == 0:
            st.warning("区间内无信号")
            return
        st.success(f"信号 {r['n_signals']} 个 · 覆盖 {r['n_symbols']} 只")
        rows = [{"窗口": f"{n}日", "样本": w["n"],
                 "胜率": f"{w['win_rate']*100:.1f}%", "净胜率": f"{w['win_rate_net']*100:.1f}%",
                 "净均值": f"{w['mean_net']*100:+.2f}%", "中位": f"{w['median']*100:+.2f}%",
                 "P10": f"{w['p10']*100:+.1f}%", "P90": f"{w['p90']*100:+.1f}%"}
                for n, w in r["windows"].items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        if r.get("by_year"):
            yr = pd.DataFrame(r["by_year"]).T
            st.bar_chart(yr["win_rate"], color=S.UP)

    st.divider()
    st.markdown("**三大战法状态机**（`python scripts/run_playbook.py --playbook ALL` 更新）")
    for name in ["B1B2B3", "NEEDLE30", "BRICK3"]:
        p = RESULTS_DIR / f"playbook_{name}_stats.json"
        if p.exists():
            s = json.loads(p.read_text())
            st.markdown(f"- **{name}**: {s['n_trades']}笔 · 胜率{s['win_rate']*100:.1f}% · "
                        f"净均值{s['mean_net']*100:+.2f}% · PF {s.get('profit_factor', '—')}")


# ──────────────────────────── 参数搜索 ────────────────────────────

def _grid():
    files = sorted(RESULTS_DIR.glob("grid_*.csv"))
    if not files:
        st.info('暂无结果。示例：`python scripts/grid_search.py --factor B1_FORMULA '
                '--grid \'{"j_threshold": [8,10,13,15,18]}\'`')
        return
    f = st.selectbox("结果文件", files, format_func=lambda p: p.name)
    df = pd.read_csv(f)
    st.dataframe(df, use_container_width=True, hide_index=True, height=260)
    metric_cols = {"n_signals", "n", "win_rate", "win_rate_net", "mean", "mean_net",
                   "median", "p10", "p90", "robust_score"}
    param_cols = [c for c in df.columns if c not in metric_cols
                  and not c.startswith("neighborhood_")]
    if len(param_cols) >= 2:
        import plotly.express as px
        metric = st.selectbox("热力图指标", ["mean_net", "win_rate_net", "robust_score"])
        pivot = df.pivot_table(index=param_cols[0], columns=param_cols[1], values=metric)
        fig = px.imshow(pivot, text_auto=".3f", color_continuous_scale="RdYlGn")
        fig.update_layout(template="plotly_dark", paper_bgcolor="#0e1117", height=400)
        st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────── ML 形态 ────────────────────────────

def _ml():
    from alphapulse.ml.pattern_model import MODEL_PATH, META_PATH
    st.markdown("##### GBDT 胜率模型")
    if META_PATH.exists():
        m = json.loads(META_PATH.read_text())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("训练样本", f"{m['n_train']:,}")
        c2.metric("样本外AUC", f"{m.get('test_auc', m.get('valid_auc', '—'))}")
        c3.metric("Top10%胜率", f"{m.get('test_top_decile_win', 0)*100:.0f}%",
                  f"基准 {m['base_win_rate']*100:.0f}%")
        c4.metric("Bot10%胜率", f"{m.get('test_bottom_decile_win', 0)*100:.0f}%")
        imp = pd.DataFrame(m["feature_importance"], columns=["特征", "重要性"]).head(10)
        st.bar_chart(imp.set_index("特征"), color=S.YELLOW, horizontal=True)
        st.caption("ml_score 已作为子分数(权重0.15)进入评分体系 · "
                   "重训: python scripts/train_ml_model.py")
    else:
        st.info("模型未训练：`python scripts/train_ml_model.py --sample 1500`")

    st.divider()
    st.markdown("##### 形态相似度搜索（找和案例长得像的股票）")
    c1, c2 = st.columns([1, 1])
    mode = c1.radio("模板来源", ["黄金案例库（45个模板）", "指定股票当前形态"], horizontal=True)
    target = c2.text_input("指定股票代码", value="605318",
                           disabled=(mode == "黄金案例库（45个模板）"))
    sample = st.select_slider("匹配范围（股票数）", [500, 1000, 2000], value=1000)
    if st.button("开始匹配", type="primary"):
        from alphapulse.ml.similarity import build_templates, find_similar, similar_to_symbol
        stocks = _universe(sample)
        with st.spinner("形态匹配中..."):
            if mode.startswith("黄金"):
                tmpl, labels = build_templates(stocks)
                out = find_similar(stocks, tmpl, labels, top_n=30)
            else:
                out = similar_to_symbol(target, stocks, top_n=30)
        if out.empty:
            st.warning("无匹配结果（检查模板/数据）")
        else:
            st.dataframe(out, hide_index=True, use_container_width=True,
                         column_config={
                             "symbol": "代码",
                             "similarity": st.column_config.ProgressColumn(
                                 "相似度", min_value=0, max_value=1, format="%.3f"),
                             "best_case": "最像的案例", "mean_top3": "前3均值"})


# ──────────────────────────── AI 工具 ────────────────────────────

def _ai():
    from alphapulse.llm.client import is_configured
    if not is_configured():
        st.warning("未配置 DEEPSEEK_API_KEY（项目根 .env）")

    st.markdown("##### 自然语言 → 选股因子")
    desc = st.text_area("中文描述", height=70,
                        placeholder="例：J值小于15，且缩量到5日均量一半，且收盘站上黄线")
    name = st.text_input("因子名（英文）", value="my_factor")
    if st.button("生成因子", type="primary") and desc.strip():
        from alphapulse.llm.factor_gen import generate_factor
        with st.spinner("解析/生成中..."):
            r = generate_factor(desc, name, use_llm=is_configured())
        if r["ok"]:
            st.success(r["message"])
            st.code(r["code"], language="python")
        else:
            st.error(r["message"])

    st.divider()
    st.markdown("##### AI 研判")
    reviews = sorted(REPORTS_DIR.glob("ai_review_*.md"))
    if reviews:
        with st.expander(f"最新研判 · {reviews[-1].stem.replace('ai_review_', '')}", expanded=True):
            st.markdown(reviews[-1].read_text())
    else:
        st.caption("运行 `python scripts/ai_review.py` 生成")


def render():
    sub = st.tabs(["信号复盘", "信号验证", "参数搜索", "ML 形态", "AI 工具"])
    with sub[0]:
        _review()
    with sub[1]:
        _validate()
    with sub[2]:
        _grid()
    with sub[3]:
        _ml()
    with sub[4]:
        _ai()
