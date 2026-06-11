"""选股工作台 — 左表右图单屏：列表点击即看K线，决策动线最短。"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from alphapulse.ui import style as S

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
REPORTS_DIR = PROJECT_ROOT / "reports"

SUB_CN = {"j_low": "J低", "trend_gap": "趋势", "vol_shrink": "缩量", "yangyin": "红肥绿瘦",
          "surge": "爆量", "dif": "DIF", "ql_pos": "QL", "pct_calm": "涨幅", "amplitude": "振幅",
          "bowl": "碗里", "washout_recover": "单针", "ml_score": "ML"}


@st.cache_data(ttl=300)
def _screen():
    files = sorted(REPORTS_DIR.glob("screen_*.csv"))
    if not files:
        return "", pd.DataFrame()
    return files[-1].stem.replace("screen_", ""), pd.read_csv(files[-1], dtype={"symbol": str})


@st.cache_data(ttl=600, show_spinner="加载日线...")
def _kline(symbol: str):
    from replay_screen import load_stock
    from alphapulse.config.settings import DATA_DIR
    return load_stock(Path(DATA_DIR) / f"{symbol}.csv", "9999-12-31")


def _plot_kline(symbol: str, n_days: int):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = _kline(symbol)
    if df is None:
        st.warning(f"无 {symbol} 数据")
        return
    df = df.tail(n_days).reset_index(drop=True)

    from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line
    from alphapulse.factors import b1_formula, volume_b1, zhixing_trend, s1_sell_signal, dd_sell_signal
    close = df["close"].astype(float)
    white = compute_short_trend(close)
    yellow = compute_bull_bear_line(close)

    sig_b1 = b1_formula.compute(df).fillna(False)
    try:
        sig_vb1 = volume_b1.compute(df).fillna(False)
        sig_zx = zhixing_trend.compute_ultra(df).fillna(False)
        sig_s1 = s1_sell_signal.compute(df).fillna(False)
        sig_dd = dd_sell_signal.compute(df).fillna(False)
    except Exception:
        sig_vb1 = sig_zx = sig_s1 = sig_dd = pd.Series(False, index=df.index)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.78, 0.22], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color=S.UP, increasing_fillcolor=S.UP,
        decreasing_line_color=S.DOWN, decreasing_fillcolor=S.DOWN, name=symbol), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=white, name="白线",
                             line=dict(color=S.WHITE, width=1.2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=yellow, name="黄线",
                             line=dict(color=S.YELLOW, width=1.5)), row=1, col=1)
    for sig, name, shape, color, ypos in [
            (sig_b1, "B1买", "triangle-up", "#ff7700", df["low"] * 0.985),
            (sig_vb1, "量能B1", "star", "#ffd700", df["low"] * 0.97),
            (sig_zx, "知行超短", "diamond", "#00bfff", df["low"] * 0.955),
            (sig_s1, "S1卖", "triangle-down", "#ff1744", df["high"] * 1.015),
            (sig_dd, "DD卖", "x", "#aaff00", df["high"] * 1.03)]:
        if sig.any():
            mask = sig.values
            fig.add_trace(go.Scatter(x=df["date"][mask], y=ypos[mask], mode="markers",
                                     name=name, marker=dict(symbol=shape, size=9, color=color)),
                          row=1, col=1)
    vol_colors = [S.UP if c >= o else S.DOWN for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=vol_colors,
                         name="成交量", showlegend=False), row=2, col=1)
    fig.update_layout(height=560, xaxis_rangeslider_visible=False, template="plotly_dark",
                      paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                      legend=dict(orientation="h", y=1.03, font=dict(size=11)),
                      margin=dict(l=6, r=6, t=24, b=6))
    fig.update_xaxes(type="category", nticks=10)
    st.plotly_chart(fig, use_container_width=True)


def render():
    date, df = _screen()
    if df.empty:
        st.info("暂无选股结果 — 运行 `python scripts/daily_screener.py`")
        return

    fc1, fc2, fc3, fc4 = st.columns([1, 1, 1.2, 1.4])
    min_score = fc1.slider("最低总分", 0, 100, 0, 5)
    only_strict = fc2.toggle("仅严格信号 ⭐")
    sectors = ["全部"] + sorted(s for s in df.get("sector", pd.Series()).dropna().unique() if s)
    sel_sector = fc3.selectbox("板块", sectors)
    n_days = fc4.select_slider("K线天数", [120, 250, 500], value=250)

    view = df[df["score"] >= min_score]
    if only_strict and "strict_signal" in view:
        view = view[view["strict_signal"]]
    if sel_sector != "全部":
        view = view[view["sector"] == sel_sector]
    view = view.reset_index(drop=True)

    left, right = st.columns([2, 3])
    with left:
        show_cols = [c for c in ["rank", "symbol", "score", "strict_signal",
                                 "ml_score", "sector", "pct_change"] if c in view.columns]
        event = st.dataframe(
            view[show_cols], height=560, hide_index=True, use_container_width=True,
            column_config={
                "rank": st.column_config.NumberColumn("#", width="small"),
                "symbol": "代码",
                "score": st.column_config.ProgressColumn("总分", min_value=0, max_value=100, format="%.0f"),
                "strict_signal": st.column_config.CheckboxColumn("⭐"),
                "ml_score": st.column_config.NumberColumn("ML", format="%.2f"),
                "sector": "板块",
                "pct_change": st.column_config.NumberColumn("涨幅%", format="%.2f"),
            },
            on_select="rerun", selection_mode="single-row")
        if event.selection.rows:
            st.session_state["wb_symbol"] = str(view.iloc[event.selection.rows[0]]["symbol"])
    with right:
        symbol = st.session_state.get("wb_symbol") or (str(view.iloc[0]["symbol"]) if len(view) else "")
        if symbol:
            row = view[view["symbol"] == symbol]
            if not row.empty:
                r = row.iloc[0]
                subs = " · ".join(f"{cn}{float(r[c]):.2f}" for c, cn in SUB_CN.items()
                                  if c in row.columns and pd.notna(r.get(c)))
                st.markdown(f"**{symbol}** 总分 {r['score']:.1f} <span class='ap-sub'>{subs}</span>",
                            unsafe_allow_html=True)
            _plot_kline(symbol, n_days)
