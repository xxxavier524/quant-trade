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


# ──────────────────────────── 信号验证（因子微调工作流）────────────────────────────

def _validate():
    st.markdown('''<div class="ap-sub" style="margin-bottom:8px">
    工作流：① 选因子 → ② 调参数（控件直接改）→ ③ 运行验证看胜率变化 →
    ④ 满意后到『参数搜索』全网格扫描 → ⑤ 到『因子权重』调整其在总分中的占比</div>''',
                unsafe_allow_html=True)
    from alphapulse.factors.factor_registry import FACTOR_REGISTRY
    names = sorted(FACTOR_REGISTRY.keys())
    c1, c2 = st.columns([2, 1])
    factor = c1.selectbox("① 选择因子/公式", names, index=names.index("B1_FORMULA"))
    sample = c2.selectbox("样本股票数", [200, 500, 1000], index=0)
    st.caption(FACTOR_REGISTRY[factor].get("description", ""))

    # ② 参数动态控件（替代手写JSON）
    defaults = FACTOR_REGISTRY[factor].get("default_params", {})
    params = {}
    if defaults:
        st.markdown("**② 参数微调**（默认值即通达信原始参数）")
        pcols = st.columns(min(4, max(1, len(defaults))))
        for i, (k, v) in enumerate(defaults.items()):
            with pcols[i % len(pcols)]:
                if isinstance(v, bool):
                    params[k] = st.toggle(k, value=v, key=f"p_{factor}_{k}")
                elif isinstance(v, int) and not isinstance(v, bool):
                    params[k] = st.number_input(k, value=v, step=1, key=f"p_{factor}_{k}")
                elif isinstance(v, float):
                    step = abs(v) / 10 or 0.1
                    params[k] = st.number_input(k, value=float(v), step=round(step, 4),
                                                format="%.4g", key=f"p_{factor}_{k}")
                else:
                    st.text_input(k, value=str(v), disabled=True, key=f"p_{factor}_{k}")
                    params[k] = v
        changed = {k: v for k, v in params.items() if defaults.get(k) != v}
        if changed:
            st.info(f"已修改: {changed}（与默认对比）")

    if st.button("③ 运行验证", type="primary"):
        from alphapulse.backtest.signal_validator import validate_signal
        stocks = _universe(sample)
        with st.spinner("回放全历史信号..."):
            r = validate_signal(factor, stocks, params or None)
        if r.get("n_signals", 0) == 0:
            st.warning("区间内无信号（参数过严？）")
            return
        st.session_state[f"val_{factor}"] = r
    r = st.session_state.get(f"val_{factor}")
    if r:
        st.success(f"信号 {r['n_signals']} 个 · 覆盖 {r['n_symbols']} 只 · 参数 {r.get('params') or '默认'}")
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


# ──────────────────────────── 因子权重编辑器 ────────────────────────────

WEIGHT_CN = {"j_low": "J值低位", "trend_gap": "趋势强度(白-黄)", "vol_shrink": "缩量",
             "yangyin": "红肥绿瘦", "surge": "爆量阳", "dif": "MACD DIF",
             "ql_pos": "QL位置", "pct_calm": "涨幅温和", "amplitude": "振幅",
             "bowl": "掉进碗里", "washout_recover": "单针回收",
             "ml_score": "ML胜率分", "ma_bull": "日线多头排列", "weekly_cross": "周线M5上穿M14"}


def _weights():
    st.markdown('''<div class="ap-sub" style="margin-bottom:8px">
    这里决定每个子分数在总分(0-100)中的占比。改完点保存，下次选股即生效；
    判断某因子是否值钱：先到『信号验证』看它单独的胜率。</div>''', unsafe_allow_html=True)
    from alphapulse.ranking.composite import WEIGHTS_FILE, DEFAULT_WEIGHTS, load_weights
    weights = load_weights()
    new_weights = {}
    cols = st.columns(3)
    for i, (k, v) in enumerate(weights.items()):
        with cols[i % 3]:
            new_weights[k] = st.slider(
                WEIGHT_CN.get(k, k), 0.0, 0.3, float(v), 0.01, key=f"w_{k}")
    total = sum(new_weights.values())
    st.caption(f"权重合计 {total:.2f}（无需=1，仅相对比例有意义）")
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("保存权重", type="primary"):
        cfg = json.loads(WEIGHTS_FILE.read_text())
        cfg["weights"]["B1_SCORE"] = {k: round(v, 3) for k, v in new_weights.items()}
        WEIGHTS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        st.success("已保存 — 重跑 daily_screener 后生效")
    if c2.button("恢复默认"):
        cfg = json.loads(WEIGHTS_FILE.read_text())
        cfg["weights"]["B1_SCORE"] = DEFAULT_WEIGHTS
        WEIGHTS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        st.success("已恢复种子权重")
        st.rerun()


# ──────────────────────────── 参数搜索 ────────────────────────────

METRIC_CN = {"mean_net": "净均值收益", "win_rate_net": "净胜率", "robust_score": "稳健分"}


def _grid():
    with st.expander("这是什么？怎么用？", expanded=False):
        st.markdown("""
**参数网格搜索** = 把因子的参数（如 J 阈值）按网格批量回测，找到既好又稳的取值。

**怎么读热力图**：每个格子 = 一组参数的回测结果，越红越好。
- 不要只挑最红的一格（可能是过拟合的运气格）
- 要挑**周围一片都偏红**的区域 —— "稳健分"列已自动算好（自身50%+邻域50%）

**怎么跑**：终端运行
```
python scripts/grid_search.py --factor B1_FORMULA --grid '{"j_threshold": [8,10,13,15,18], "dif_threshold": [-0.3,-0.1,0.1]}'
```
跑完结果自动出现在下方。找到满意参数后 → 回『信号验证』确认 → 改 config 或权重。""")
    files = sorted(RESULTS_DIR.glob("grid_*.csv"))
    if not files:
        st.info("暂无网格结果，按上方说明运行一次")
        return
    f = st.selectbox("结果文件", files, format_func=lambda p: p.name)
    df = pd.read_csv(f)
    metric_cols = {"n_signals", "n", "win_rate", "win_rate_net", "mean", "mean_net",
                   "median", "p10", "p90", "robust_score"}
    param_cols = [c for c in df.columns if c not in metric_cols
                  and not c.startswith("neighborhood_")]

    best = df.sort_values("robust_score", ascending=False).iloc[0] if "robust_score" in df.columns else None
    if best is not None:
        st.success("稳健最优参数: " + " · ".join(f"{p}={best[p]}" for p in param_cols)
                   + f" （净均值 {best.get('mean_net', 0)*100:+.2f}% / 稳健分 {best.get('robust_score', 0)*100:.2f}）")

    if len(param_cols) >= 2:
        import plotly.express as px
        m1, m2 = st.columns([1, 3])
        metric = m1.radio("指标", list(METRIC_CN), format_func=METRIC_CN.get)
        with m2:
            pivot = df.pivot_table(index=param_cols[0], columns=param_cols[1], values=metric)
            fig = px.imshow(pivot, text_auto=".2%",
                            color_continuous_scale=[[0, S.DOWN], [0.5, "#262a35"], [1, S.UP]],
                            labels=dict(x=param_cols[1], y=param_cols[0], color=METRIC_CN[metric]),
                            aspect="auto")
            if best is not None:
                fig.add_annotation(x=best[param_cols[1]], y=best[param_cols[0]],
                                   text="◎ 稳健最优", showarrow=False,
                                   font=dict(color="#fff", size=12), yshift=18)
            fig.update_layout(template="plotly_dark", paper_bgcolor="#0e1117",
                              height=380, margin=dict(l=10, r=10, t=10, b=10),
                              coloraxis_colorbar=dict(title=""))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    elif len(param_cols) == 1:
        st.bar_chart(df.set_index(param_cols[0])["mean_net"], color=S.UP)

    with st.expander("完整结果表"):
        st.dataframe(df, use_container_width=True, hide_index=True, height=260)


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
    sub = st.tabs(["信号复盘", "信号验证", "因子权重", "参数搜索", "ML 形态", "AI 工具"])
    with sub[0]:
        _review()
    with sub[1]:
        _validate()
    with sub[2]:
        _weights()
    with sub[3]:
        _grid()
    with sub[4]:
        _ml()
    with sub[5]:
        _ai()
