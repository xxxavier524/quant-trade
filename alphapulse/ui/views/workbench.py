"""选股工作台 — 列表（评分/策略/板块/概念）→ 点击行展开『选股依据 + 日K线』。

依据明细包含（用户需求 2026-06-11）：
- B1六条件逐条 ✓/✗（含实际值）
- 量能B1要点 / 知行超短状态
- 日线均线多头排列 + 周线M5/M14（上穿=B1加强）
- 全部子分数
"""

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
          "bowl": "碗里", "washout_recover": "单针", "ma_bull": "日线多头",
          "weekly_cross": "周线金叉", "ml_score": "ML"}


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


def _check(label: str, ok: bool, value: str = "") -> str:
    icon = "✓" if ok else "✗"
    color = S.UP if ok else S.MUTED
    val = f' <span class="ap-sub">{value}</span>' if value else ""
    return (f'<div style="margin:3px 0;font-size:13px">'
            f'<span style="color:{color};font-weight:700">{icon}</span> {label}{val}</div>')


def _evidence(symbol: str, df: pd.DataFrame, row: pd.Series | None):
    """选股依据明细面板。"""
    from alphapulse.factors import b1_formula, volume_b1, zhixing_trend, weekly_ma_cross

    html = '<div style="font-size:14px;font-weight:600;margin-bottom:6px">B1 公式六条件</div>'
    try:
        d = b1_formula.compute_detail(df).iloc[-1]
        html += _check("涨幅±3%以内", bool(d["cond1_range"]), f"实际 {d['pct_change']}%")
        html += _check("振幅<9%", bool(d["cond2_amp"]), f"实际 {d['amplitude']}%")
        html += _check("市值>10亿", bool(d["cond3_cap"]))
        html += _check("KDJ J<13", bool(d["cond4_j"]), f"J={d['kdj_j']}")
        html += _check("白线>黄线", bool(d["cond5_trend"]),
                       f"白{d['white_line']} / 黄{d['yellow_line']}")
        html += _check("DIF>-0.1", bool(d["cond6_dif"]), f"DIF={d['macd_dif']}")
    except Exception as e:
        html += f'<div class="ap-sub">计算失败: {e}</div>'

    html += '<div style="font-size:14px;font-weight:600;margin:10px 0 6px">均线体系（B1加强）</div>'
    try:
        ma = weekly_ma_cross.compute_detail(df)
        mas = " ".join(f"{k}={v}" for k, v in ma["daily_mas"].items())
        html += _check("日线多头排列 MA5>MA10>MA20", ma["daily_ma_bull"], mas)
        html += _check("周线 M5 > M14", ma["weekly_above"],
                       f"M5={ma['weekly_m5']} / M14={ma['weekly_m14']}")
        html += _check("周线近4周内M5上穿M14（最强加分）", ma["weekly_crossed_recently"])
    except Exception as e:
        html += f'<div class="ap-sub">均线计算失败: {e}</div>'

    html += '<div style="font-size:14px;font-weight:600;margin:10px 0 6px">量能B1 / 知行超短</div>'
    try:
        v = volume_b1.compute_detail(df).iloc[-1]
        html += _check("量能B1 J≤13", bool(v["j_ok"]), f"J={v['kdj_j']}")
        html += _check("28日阳量/阴量>1.65", bool(v["yangyin_ratio_28"] > 1.65),
                       f"实际 {v['yangyin_ratio_28']}")
        html += _check("28日爆量阳≥3次", bool(v["plry_count_28"] >= 3),
                       f"实际 {int(v['plry_count_28'])}次")
        html += _check("收盘>0.99×QL", bool(v["close_above_ql"]), f"QL={v['ql']}")
        zx = bool(zhixing_trend.compute_ultra(df).iloc[-1])
        html += _check("知行超短5条件", zx)
    except Exception as e:
        html += f'<div class="ap-sub">计算失败: {e}</div>'

    if row is not None:
        subs = " · ".join(f"{cn} <b>{float(row[c]):.2f}</b>"
                          for c, cn in SUB_CN.items()
                          if c in row.index and pd.notna(row.get(c)))
        html += ('<div style="font-size:14px;font-weight:600;margin:10px 0 6px">子分数（0-1）</div>'
                 f'<div style="font-size:12px;line-height:1.9">{subs}</div>')
    S.card(html)


def _plot_kline(symbol: str, n_days: int = 250):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = _kline(symbol)
    if df is None:
        st.warning(f"无 {symbol} 数据")
        return None
    full = df
    df = df.tail(n_days).reset_index(drop=True)

    from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line
    from alphapulse.factors import b1_formula, volume_b1, zhixing_trend, s1_sell_signal, dd_sell_signal
    close = df["close"].astype(float)
    white = compute_short_trend(close)
    yellow = compute_bull_bear_line(close)
    ma5 = close.rolling(5).mean()

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
    fig.add_trace(go.Scatter(x=df["date"], y=ma5, name="MA5",
                             line=dict(color="#7f5af0", width=1, dash="dot")), row=1, col=1)
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
    fig.update_layout(height=520, xaxis_rangeslider_visible=False, template="plotly_dark",
                      paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                      legend=dict(orientation="h", y=1.03, font=dict(size=11)),
                      margin=dict(l=6, r=6, t=24, b=6))
    fig.update_xaxes(type="category", nticks=10)
    st.plotly_chart(fig, use_container_width=True)
    return full


def render():
    date, df = _screen()
    if df.empty:
        st.info("暂无选股结果 — 运行 `python scripts/daily_screener.py`")
        return

    fc1, fc2, fc3 = st.columns([1, 1, 2])
    min_score = fc1.slider("最低总分", 0, 100, 0, 5)
    only_strict = fc2.toggle("仅严格信号 ⭐")
    sectors = ["全部"] + sorted(s for s in df.get("sector", pd.Series()).dropna().unique() if s)
    sel_sector = fc3.selectbox("板块", sectors)

    view = df[df["score"] >= min_score]
    if only_strict and "strict_signal" in view:
        view = view[view["strict_signal"]]
    if sel_sector != "全部":
        view = view[view["sector"] == sel_sector]
    view = view.reset_index(drop=True)

    show_cols = [c for c in ["rank", "symbol", "name", "score", "strategies",
                             "sector", "concepts", "pct_change", "strict_signal",
                             "ml_score"] if c in view.columns]
    event = st.dataframe(
        view[show_cols], height=420, hide_index=True, use_container_width=True,
        column_config={
            "rank": st.column_config.NumberColumn("#", width="small"),
            "symbol": "代码", "name": "名称",
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100, format="%.0f"),
            "strategies": "选股策略",
            "sector": "板块",
            "concepts": st.column_config.TextColumn("概念", width="medium"),
            "pct_change": st.column_config.NumberColumn("涨幅%", format="%.2f"),
            "strict_signal": st.column_config.CheckboxColumn("⭐"),
            "ml_score": st.column_config.NumberColumn("ML", format="%.2f"),
        },
        on_select="rerun", selection_mode="single-row")

    # ── 点击行 → 展开依据 + K线 ──
    if event.selection.rows:
        st.session_state["wb_symbol"] = str(view.iloc[event.selection.rows[0]]["symbol"])
    symbol = st.session_state.get("wb_symbol")
    if not symbol and len(view):
        symbol = str(view.iloc[0]["symbol"])
    if symbol:
        sel = view[view["symbol"] == symbol]
        row = sel.iloc[0] if not sel.empty else None
        title = f"{symbol}"
        if row is not None:
            name = row.get("name", "")
            title += f" {name if str(name) != 'nan' else ''} · 评分 {row['score']:.1f} · {row.get('strategies', '')}"
        with st.expander(f"📋 选股依据与日K线 — {title}", expanded=True):
            c_left, c_right = st.columns([2, 3])
            with c_left:
                kdf = _kline(symbol)
                if kdf is not None:
                    _evidence(symbol, kdf, row)
                # 板块/概念按钮 → 弹出聚合K线
                if row is not None:
                    from alphapulse.ui.views.board_kline import board_dialog
                    boards = []
                    sec = str(row.get("sector", "") or "")
                    if sec and sec != "nan":
                        boards.append(("行业", sec))
                    concepts = str(row.get("concepts", "") or "")
                    if concepts and concepts != "nan":
                        boards += [("概念", c) for c in concepts.split("/") if c]
                    if boards:
                        st.caption("点击查看板块/概念K线：")
                        bcols = st.columns(min(4, len(boards)))
                        for i, (kind, b) in enumerate(boards[:4]):
                            if bcols[i].button(f"{b}", key=f"bd_{symbol}_{b}"):
                                board_dialog(b)
            with c_right:
                _plot_kline(symbol)
