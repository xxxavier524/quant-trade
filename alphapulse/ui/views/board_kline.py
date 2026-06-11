"""板块/概念K线弹窗 — 共享组件（看板/工作台共用）。"""

from pathlib import Path

import pandas as pd
import streamlit as st

from alphapulse.ui import style as S

@st.cache_data(ttl=600, show_spinner="聚合板块K线...")
def board_kline_data(board: str) -> pd.DataFrame | None:
    from alphapulse.market.sector_score import board_index_kline
    from alphapulse.config.settings import DATA_DIR
    return board_index_kline(board, Path(DATA_DIR))


@st.dialog("板块 / 概念 K线", width="large")
def board_dialog(board: str):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    idx = board_kline_data(board)
    if idx is None or idx.empty:
        st.warning(f"{board}: 成员数据不足，无法聚合")
        return
    close = idx["close"].astype(float)
    chg20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) > 21 else 0
    st.markdown(f"**{board}** · 等权聚合指数（基期=100）· 近20日 "
                f"<span style='color:{S.pct_color(chg20)}'>{chg20:+.1f}%</span>",
                unsafe_allow_html=True)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.75, 0.25], vertical_spacing=0.03)
    up = close.iloc[-1] >= close.iloc[0]
    fig.add_trace(go.Scatter(x=idx["date"], y=close, mode="lines",
                             line=dict(color=S.UP if up else S.DOWN, width=1.6),
                             name=board), row=1, col=1)
    for n, color in [(20, S.YELLOW), (60, "#7f5af0")]:
        if len(close) > n:
            fig.add_trace(go.Scatter(x=idx["date"], y=close.rolling(n).mean(),
                                     mode="lines", line=dict(color=color, width=1),
                                     name=f"MA{n}"), row=1, col=1)
    if "amount" in idx.columns and idx["amount"].notna().any():
        fig.add_trace(go.Bar(x=idx["date"], y=idx["amount"],
                             marker_color="#4a5060", name="成交额", showlegend=False),
                      row=2, col=1)
    fig.update_layout(height=460, template="plotly_dark", paper_bgcolor="#0e1117",
                      plot_bgcolor="#161a23", margin=dict(l=6, r=6, t=10, b=6),
                      legend=dict(orientation="h", y=1.05))
    fig.update_xaxes(type="category", nticks=10)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

