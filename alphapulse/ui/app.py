"""AlphaPulse-A v4 — 经典炒股软件风格交易台（Phase 5 重写）。

深色主题 + 红涨绿跌（涨#ef232a 跌#14b143），6个工作区：
选股雷达 / 个股K线 / 大盘板块 / 信号验证 / 参数搜索 / AI工具

数据来源全部为结构化文件（screen_*.csv / sectors_*.csv / data/index/），
不再做 markdown 正则解析。旧版存档于 app_v3_legacy.py。

启动：streamlit run alphapulse/ui/app.py
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402

REPORTS_DIR = PROJECT_ROOT / "reports"

UP = "#ef232a"      # 红涨
DOWN = "#14b143"    # 绿跌
YELLOW = "#f0b90b"  # 黄线
WHITE = "#e8e8e8"   # 白线

st.set_page_config(page_title="AlphaPulse-A 交易台", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
[data-testid="stMetricDelta"] svg {display: none;}
.block-container {padding-top: 1.2rem; padding-bottom: 0;}
div[data-testid="stDataFrame"] {border: 1px solid #2a2e39; border-radius: 6px;}
h1, h2, h3 {color: #e8e8e8;}
.stTabs [data-baseweb="tab"] {font-size: 15px; padding: 8px 18px;}
</style>
""", unsafe_allow_html=True)


# ──────────────────────────── 数据加载（缓存）────────────────────────────

@st.cache_data(ttl=300)
def latest_screen() -> tuple[str, pd.DataFrame]:
    files = sorted(REPORTS_DIR.glob("screen_*.csv"))
    if not files:
        return "", pd.DataFrame()
    f = files[-1]
    return f.stem.replace("screen_", ""), pd.read_csv(f, dtype={"symbol": str})


@st.cache_data(ttl=300)
def latest_sectors() -> pd.DataFrame:
    files = sorted(REPORTS_DIR.glob("sectors_*.csv"))
    return pd.read_csv(files[-1]) if files else pd.DataFrame()


@st.cache_data(ttl=300)
def market_diag() -> dict:
    from alphapulse.market.market_score import compute_market_score
    return compute_market_score()


@st.cache_data(ttl=600, show_spinner="加载日线...")
def load_kline(symbol: str) -> pd.DataFrame | None:
    from replay_screen import load_stock
    return load_stock(Path(DATA_DIR) / f"{symbol}.csv", "9999-12-31")


@st.cache_data(ttl=600, show_spinner="加载样本股票池（首次约1分钟）...")
def load_universe_cached(sample: int) -> dict:
    from validate_signal import load_universe
    return load_universe(Path(DATA_DIR), sample, "9999-12-31")


# ──────────────────────────── 顶部信息条 ────────────────────────────

def header_strip():
    try:
        m = market_diag()
    except Exception:
        m = {"score": 50, "level": "震荡", "advice": "指数数据缺失"}
    date, screen = latest_screen()
    c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1.6, 1, 1])
    c1.metric("📊 大盘综合分", f"{m['score']:.0f}/100", m["level"])
    color = UP if m["score"] >= 60 else (DOWN if m["score"] < 40 else YELLOW)
    c2.markdown(f"<div style='padding-top:18px'><span style='color:{color};"
                f"font-size:20px;font-weight:700'>{m['level']}</span></div>",
                unsafe_allow_html=True)
    c3.markdown(f"<div style='padding-top:18px;color:#aaa'>💡 {m['advice']}</div>",
                unsafe_allow_html=True)
    c4.metric("最新选股日", date or "—")
    n_strict = int(screen["strict_signal"].sum()) if not screen.empty and "strict_signal" in screen else 0
    c5.metric("严格信号", f"{n_strict} 只")
    st.divider()


# ──────────────────────────── Tab1 选股雷达 ────────────────────────────

SUB_CN = {"j_low": "J低", "trend_gap": "趋势", "vol_shrink": "缩量", "yangyin": "红肥绿瘦",
          "surge": "爆量", "dif": "DIF", "ql_pos": "QL", "pct_calm": "涨幅", "amplitude": "振幅",
          "bowl": "碗里", "washout_recover": "单针"}


def tab_radar():
    date, df = latest_screen()
    if df.empty:
        st.info("暂无选股结果，请先运行 `python scripts/daily_screener.py`")
        return
    st.subheader(f"选股雷达 · {date}")

    f1, f2, f3, _ = st.columns([1, 1, 1, 2])
    min_score = f1.slider("最低总分", 0, 100, 0, 5)
    only_strict = f2.toggle("仅严格信号 ⭐", value=False)
    sectors = ["全部"] + sorted(df["sector"].dropna().unique().tolist()) if "sector" in df else ["全部"]
    sel_sector = f3.selectbox("板块", sectors)

    view = df[df["score"] >= min_score]
    if only_strict and "strict_signal" in view:
        view = view[view["strict_signal"]]
    if sel_sector != "全部" and "sector" in view:
        view = view[view["sector"] == sel_sector]
    view = view.reset_index(drop=True)

    show_cols = [c for c in ["rank", "symbol", "name", "score", "strict_signal",
                             "sig_b1", "sig_volume_b1", "sig_zhixing", "sector",
                             "sector_score", "close", "pct_change", "top_factors"]
                 if c in view.columns]
    event = st.dataframe(
        view[show_cols], use_container_width=True, height=480, hide_index=True,
        column_config={
            "rank": st.column_config.NumberColumn("排名", width="small"),
            "symbol": "代码", "name": "名称",
            "score": st.column_config.ProgressColumn("总分", min_value=0, max_value=100, format="%.1f"),
            "strict_signal": st.column_config.CheckboxColumn("⭐严格"),
            "sig_b1": st.column_config.CheckboxColumn("B1"),
            "sig_volume_b1": st.column_config.CheckboxColumn("量能B1"),
            "sig_zhixing": st.column_config.CheckboxColumn("知行超短"),
            "sector": "板块", "sector_score": st.column_config.NumberColumn("板块分", format="%.0f"),
            "close": "现价", "pct_change": st.column_config.NumberColumn("涨幅%", format="%.2f"),
            "top_factors": "主要贡献",
        },
        on_select="rerun", selection_mode="single-row",
    )
    if event.selection.rows:
        sym = view.iloc[event.selection.rows[0]]["symbol"]
        st.session_state["kline_symbol"] = str(sym)
        st.success(f"已选 {sym}，切换到『📊 个股K线』查看信号标注")

    with st.expander("📋 子分数明细（0-1）"):
        sub_cols = [c for c in SUB_CN if c in view.columns]
        detail = view[["symbol", "name"] + sub_cols].rename(columns=SUB_CN)
        st.dataframe(detail, use_container_width=True, hide_index=True)


# ──────────────────────────── Tab2 个股K线 ────────────────────────────

def tab_kline():
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    c1, c2, _ = st.columns([1.2, 1, 3])
    default_sym = st.session_state.get("kline_symbol", "605318")
    symbol = c1.text_input("股票代码", value=default_sym, max_chars=6)
    n_days = c2.selectbox("显示天数", [120, 250, 500], index=1)
    if not symbol or len(symbol) < 6:
        return
    df = load_kline(symbol)
    if df is None:
        st.warning(f"无 {symbol} 数据")
        return
    df = df.tail(n_days).reset_index(drop=True)

    from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line
    from alphapulse.factors import b1_formula, volume_b1, zhixing_trend, s1_sell_signal, dd_sell_signal
    close = df["close"].astype(float)
    white = compute_short_trend(close)
    yellow = compute_bull_bear_line(close)
    ql = (0.4 * close.rolling(20).mean() + 0.3 * close.rolling(60).mean()
          + 0.2 * close.rolling(120).mean() + 0.1 * close.rolling(250).mean())

    sig_b1 = b1_formula.compute(df).fillna(False)
    try:
        sig_vb1 = volume_b1.compute(df).fillna(False)
        sig_zx = zhixing_trend.compute_ultra(df).fillna(False)
        sig_s1 = s1_sell_signal.compute(df).fillna(False)
        sig_dd = dd_sell_signal.compute(df).fillna(False)
    except Exception:
        sig_vb1 = sig_zx = sig_s1 = sig_dd = pd.Series(False, index=df.index)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
                        vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color=UP, increasing_fillcolor=UP,
        decreasing_line_color=DOWN, decreasing_fillcolor=DOWN,
        name=symbol), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=white, name="白线(知行趋势)",
                             line=dict(color=WHITE, width=1.2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=yellow, name="黄线(多空14/28/57/114)",
                             line=dict(color=YELLOW, width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=ql, name="QL线",
                             line=dict(color="#7f5af0", width=1, dash="dot")), row=1, col=1)

    marker_sets = [
        (sig_b1, "B1买", "triangle-up", "#ff7700", df["low"] * 0.985),
        (sig_vb1, "量能B1", "star", "#ffd700", df["low"] * 0.97),
        (sig_zx, "知行超短", "diamond", "#00bfff", df["low"] * 0.955),
        (sig_s1, "S1卖", "triangle-down", "#ff1744", df["high"] * 1.015),
        (sig_dd, "DD卖", "x", "#aaff00", df["high"] * 1.03),
    ]
    for sig, name, shape, color, ypos in marker_sets:
        if sig.any():
            mask = sig.values
            fig.add_trace(go.Scatter(
                x=df["date"][mask], y=ypos[mask], mode="markers", name=name,
                marker=dict(symbol=shape, size=10, color=color)), row=1, col=1)

    vol_colors = [UP if c >= o else DOWN for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=vol_colors,
                         name="成交量"), row=2, col=1)
    fig.update_layout(height=620, xaxis_rangeslider_visible=False,
                      template="plotly_dark", paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                      legend=dict(orientation="h", y=1.02),
                      margin=dict(l=10, r=10, t=30, b=10))
    fig.update_xaxes(type="category", nticks=12)
    st.plotly_chart(fig, use_container_width=True)

    st.caption(f"区间内信号: B1×{int(sig_b1.sum())} 量能B1×{int(sig_vb1.sum())} "
               f"知行超短×{int(sig_zx.sum())} | S1×{int(sig_s1.sum())} DD×{int(sig_dd.sum())}")


# ──────────────────────────── Tab3 大盘与板块 ────────────────────────────

def tab_market():
    try:
        m = market_diag()
    except Exception as e:
        st.error(f"大盘诊断失败: {e}")
        return
    st.subheader(f"大盘诊断 · {m['score']:.0f}/100 [{m['level']}]")
    st.markdown(f"**仓位建议：** {m['advice']}")
    if m["detail"]:
        cols = st.columns(len(m["detail"]))
        for col, (name, det) in zip(cols, m["detail"].items()):
            with col:
                st.metric(name, f"{det['total']:.0f}")
                st.caption(f"量能 {det['volume']['score']:.0f} · {det['volume']['note']}")
                st.caption(f"知行BS {det['zhixing_bs']['score']:.0f} · {det['zhixing_bs']['note']}")
                st.caption(f"N型 {det['n_struct']['score']:.0f} · {det['n_struct']['note']}")
    st.divider()

    sec = latest_sectors()
    if sec.empty:
        st.info("暂无板块数据，运行 daily_screener 生成")
        return
    st.subheader("板块强度排名")
    st.dataframe(
        sec, use_container_width=True, height=520, hide_index=True,
        column_config={
            "rank": st.column_config.NumberColumn("排名", width="small"),
            "sector": "板块",
            "score": st.column_config.ProgressColumn("强度", min_value=0, max_value=100, format="%.0f"),
            "tags": "性质", "note": "状态", "members": "成员数",
        })


# ──────────────────────────── Tab4 信号验证 ────────────────────────────

def tab_validate():
    st.subheader("信号胜率验证（一键回测）")
    from alphapulse.factors.factor_registry import FACTOR_REGISTRY
    names = sorted(FACTOR_REGISTRY.keys())
    c1, c2, c3 = st.columns([2, 1, 1])
    factor = c1.selectbox("因子/公式", names, index=names.index("B1_FORMULA"))
    sample = c2.selectbox("样本股票数", [200, 500, 1000], index=0)
    params_str = c3.text_input("参数覆盖(JSON)", value="")
    st.caption(f"默认参数: {FACTOR_REGISTRY[factor].get('default_params', {})}")

    if st.button("🚀 运行验证", type="primary"):
        from alphapulse.backtest.signal_validator import validate_signal
        params = json.loads(params_str) if params_str.strip() else None
        stocks = load_universe_cached(sample)
        with st.spinner(f"回放 {factor} 全历史信号..."):
            r = validate_signal(factor, stocks, params)
        if r.get("n_signals", 0) == 0:
            st.warning("区间内无信号")
            return
        st.success(f"信号 {r['n_signals']} 个 · 覆盖 {r['n_symbols']} 只 · "
                   f"{' ~ '.join(r['date_range'])}")
        rows = []
        for n, w in r["windows"].items():
            rows.append({"窗口": f"{n}日", "样本": w["n"],
                         "胜率": f"{w['win_rate']*100:.1f}%", "净胜率": f"{w['win_rate_net']*100:.1f}%",
                         "均值": f"{w['mean']*100:+.2f}%", "净均值": f"{w['mean_net']*100:+.2f}%",
                         "中位": f"{w['median']*100:+.2f}%",
                         "P10": f"{w['p10']*100:+.1f}%", "P90": f"{w['p90']*100:+.1f}%"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        if r.get("by_year"):
            yr = pd.DataFrame(r["by_year"]).T
            yr.index.name = "年份"
            st.bar_chart(yr["win_rate"], color=UP)

    st.divider()
    st.markdown("##### 三大战法状态机（最近结果）")
    for name in ["B1B2B3", "NEEDLE30", "BRICK3"]:
        p = PROJECT_ROOT / "backtest_results" / f"playbook_{name}_stats.json"
        if p.exists():
            s = json.loads(p.read_text())
            st.markdown(f"**{name}**: {s['n_trades']}笔 · 胜率{s['win_rate']*100:.1f}% · "
                        f"净均值{s['mean_net']*100:+.2f}% · PF {s.get('profit_factor', '—')}")
    st.caption("更新：python scripts/run_playbook.py --playbook ALL")


# ──────────────────────────── Tab5 参数搜索 ────────────────────────────

def tab_grid():
    st.subheader("参数网格搜索结果")
    files = sorted((PROJECT_ROOT / "backtest_results").glob("grid_*.csv"))
    if not files:
        st.info('暂无结果。运行示例：\n```\npython scripts/grid_search.py --factor B1_FORMULA '
                '--grid \'{"j_threshold": [8,10,13,15,18], "dif_threshold": [-0.3,-0.1,0.1]}\'\n```')
        return
    f = st.selectbox("结果文件", files, format_func=lambda p: p.name)
    df = pd.read_csv(f)
    st.dataframe(df, use_container_width=True, hide_index=True)
    metric_cols = {"n_signals", "n", "win_rate", "win_rate_net", "mean", "mean_net",
                   "median", "p10", "p90", "robust_score"}
    param_cols = [c for c in df.columns if c not in metric_cols
                  and not c.startswith("neighborhood_")]
    if len(param_cols) >= 2:
        import plotly.express as px
        metric = st.selectbox("热力图指标", ["mean_net", "win_rate_net", "robust_score"])
        pivot = df.pivot_table(index=param_cols[0], columns=param_cols[1], values=metric)
        fig = px.imshow(pivot, text_auto=".3f", color_continuous_scale="RdYlGn",
                        labels=dict(color=metric))
        fig.update_layout(template="plotly_dark", paper_bgcolor="#0e1117", height=420)
        st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────── Tab6 AI 工具 ────────────────────────────

def tab_ai():
    from alphapulse.llm.client import is_configured
    if not is_configured():
        st.warning("未配置 DEEPSEEK_API_KEY。在 ~/.zshrc 添加 "
                   "`export DEEPSEEK_API_KEY=sk-...` 后重启即可启用：自然语言转因子（LLM兜底）、AI研判。"
                   "未配置时仍可用正则解析路径。")

    st.subheader("🧪 自然语言 → 选股因子")
    desc = st.text_area("用中文描述选股条件",
                        placeholder="例：J值小于15，且当日成交量缩到5日均量的一半以下",
                        height=80)
    name = st.text_input("因子名（英文）", value="my_factor")
    if st.button("生成因子", type="primary") and desc.strip():
        from alphapulse.llm.factor_gen import generate_factor
        with st.spinner("解析/生成中..."):
            r = generate_factor(desc, name, use_llm=is_configured())
        if r["ok"]:
            st.success(r["message"])
            st.code(r["code"], language="python")
            st.caption(f"已存 {r['path']}。先在『信号验证』看胜率，确认有效后再启用。")
        else:
            st.error(r["message"])
            if r.get("code"):
                st.code(r["code"], language="python")

    st.divider()
    st.subheader("🤖 AI 研判")
    reviews = sorted(REPORTS_DIR.glob("ai_review_*.md"))
    if reviews:
        st.markdown(reviews[-1].read_text())
    else:
        st.caption("暂无研判。配置 API key 后运行 `python scripts/ai_review.py`")


# ──────────────────────────── 主框架 ────────────────────────────

st.title("📈 AlphaPulse-A 交易台")
header_strip()

t1, t2, t3, t4, t5, t6 = st.tabs(
    ["🎯 选股雷达", "📊 个股K线", "🌐 大盘板块", "✅ 信号验证", "🔬 参数搜索", "🤖 AI工具"])
with t1:
    tab_radar()
with t2:
    tab_kline()
with t3:
    tab_market()
with t4:
    tab_validate()
with t5:
    tab_grid()
with t6:
    tab_ai()
