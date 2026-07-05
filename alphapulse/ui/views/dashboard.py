"""今日看板 — 30秒看懂今天：大盘基调 → 板块强弱 → 今日Top信号。"""

from pathlib import Path

import pandas as pd
import streamlit as st

from alphapulse.ui import style as S

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"


@st.cache_data(ttl=300)
def _market():
    from alphapulse.market.market_score import compute_market_score
    return compute_market_score()


@st.cache_data(ttl=300)
def _screen():
    files = sorted(REPORTS_DIR.glob("screen_*.csv"))
    if not files:
        return "", pd.DataFrame()
    return files[-1].stem.replace("screen_", ""), pd.read_csv(files[-1], dtype={"symbol": str})


@st.cache_data(ttl=300)
def _sectors():
    files = sorted(REPORTS_DIR.glob("sectors_*.csv"))
    return pd.read_csv(files[-1]) if files else pd.DataFrame()


@st.cache_data(ttl=120)
def _last_update() -> dict:
    """数据/选股更新状态：优先 last_run.json，回退到最新 screen CSV 的 mtime。"""
    import datetime as _dt
    marker = REPORTS_DIR / "last_run.json"
    if marker.exists():
        try:
            import json
            m = json.loads(marker.read_text())
            steps = {s["step"]: s for s in m.get("steps", [])}
            return {"time": m.get("finished_at", "—"),
                    "update_ok": steps.get("数据增量更新", {}).get("ok"),
                    "screen_ok": steps.get("全市场选股", {}).get("ok")}
        except Exception:
            pass
    files = sorted(REPORTS_DIR.glob("screen_*.csv"))
    if files:
        ts = _dt.datetime.fromtimestamp(files[-1].stat().st_mtime)
        return {"time": ts.strftime("%Y-%m-%d %H:%M"), "update_ok": None, "screen_ok": True}
    return {"time": "—", "update_ok": None, "screen_ok": None}


@st.cache_data(ttl=300, show_spinner=False)
def _index_minute() -> pd.DataFrame:
    """上证当日5分钟分时（新浪，剥离代理）。失败返回空。"""
    import os
    import socket
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"
    socket.setdefaulttimeout(15)
    try:
        import akshare as ak
        df = ak.stock_zh_a_minute(symbol="sh000001", period="5", adjust="")
        df["day"] = pd.to_datetime(df["day"])
        last_day = df["day"].dt.date.max()
        cur = df[df["day"].dt.date == last_day].copy()
        prev = df[df["day"].dt.date < last_day]
        cur.attrs["prev_close"] = float(prev["close"].iloc[-1]) if len(prev) else None
        for c in ("open", "high", "low", "close"):
            cur[c] = pd.to_numeric(cur[c], errors="coerce")
        return cur
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def _index_daily(n: int = 120) -> pd.DataFrame:
    p = PROJECT_ROOT / "data" / "index" / "sh000001.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p).tail(n).reset_index(drop=True)


def _market_charts():
    """大盘分时 + 日K 小图（一行两图，紧凑）。"""
    import plotly.graph_objects as go

    c1, c2 = st.columns(2)
    minute = _index_minute()
    with c1:
        st.markdown('<div class="ap-kpi-label" style="margin-bottom:4px">上证指数 · 当日分时</div>',
                    unsafe_allow_html=True)
        if minute.empty:
            st.caption("分时数据暂不可用（盘后或网络）")
        else:
            prev_close = minute.attrs.get("prev_close")
            last = float(minute["close"].iloc[-1])
            up = prev_close is None or last >= prev_close
            color = S.UP if up else S.DOWN
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=minute["day"], y=minute["close"], mode="lines",
                line=dict(color=color, width=1.6),
                fill="tozeroy", fillcolor=("rgba(239,35,42,0.08)" if up else "rgba(20,177,67,0.08)"),
                name="上证"))
            if prev_close:
                fig.add_hline(y=prev_close, line_dash="dot",
                              line_color=S.MUTED, line_width=1)
                chg = (last / prev_close - 1) * 100
                fig.add_annotation(x=1, y=1, xref="paper", yref="paper",
                                   text=f"{last:.2f} ({chg:+.2f}%)", showarrow=False,
                                   font=dict(color=color, size=14), xanchor="right")
            ymin, ymax = minute["close"].min(), minute["close"].max()
            pad = (ymax - ymin) * 0.1 or 1
            fig.update_yaxes(range=[min(ymin, prev_close or ymin) - pad,
                                    max(ymax, prev_close or ymax) + pad])
            fig.update_layout(height=180, template="plotly_dark",
                              paper_bgcolor="#0e1117", plot_bgcolor="#161a23",
                              margin=dict(l=4, r=4, t=4, b=4), showlegend=False)
            fig.update_xaxes(nticks=6, tickformat="%H:%M")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.markdown('<div class="ap-kpi-label" style="margin-bottom:4px">上证指数 · 日K（120日）</div>',
                    unsafe_allow_html=True)
        daily = _index_daily()
        if daily.empty:
            st.caption("指数日线缺失 — 运行 fetch_index_data.py")
        else:
            fig = go.Figure(go.Candlestick(
                x=daily["date"], open=daily["open"], high=daily["high"],
                low=daily["low"], close=daily["close"],
                increasing_line_color=S.UP, increasing_fillcolor=S.UP,
                decreasing_line_color=S.DOWN, decreasing_fillcolor=S.DOWN))
            ma20 = daily["close"].rolling(20).mean()
            fig.add_trace(go.Scatter(x=daily["date"], y=ma20, mode="lines",
                                     line=dict(color=S.YELLOW, width=1), name="MA20"))
            fig.update_layout(height=180, template="plotly_dark",
                              paper_bgcolor="#0e1117", plot_bgcolor="#161a23",
                              margin=dict(l=4, r=4, t=4, b=4), showlegend=False,
                              xaxis_rangeslider_visible=False)
            fig.update_xaxes(type="category", nticks=6)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})



def _board_selector():
    """板块/概念K线查询入口。"""
    from alphapulse.ui.views.board_kline import board_dialog
    from alphapulse.market.sector_score import load_members, load_concept_members
    sectors = list(load_members().keys())
    concepts = list(load_concept_members().keys())
    options = [f"[行业] {s}" for s in sectors] + [f"[概念] {c}" for c in concepts]
    sel = st.selectbox("查看板块 / 概念 K线", ["— 选择 —"] + options, key="board_sel")
    if sel and sel != "— 选择 —":
        board = sel.split("] ", 1)[1]
        board_dialog(board)


@st.cache_data(ttl=600)
def _morning_brief():
    """最新早报（morning_brief.py 每日07:30生成）。"""
    files = sorted(REPORTS_DIR.glob("morning_brief_*.md"))
    if not files:
        return "", ""
    return files[-1].stem.replace("morning_brief_", ""), files[-1].read_text(encoding="utf-8")


def render():
    try:
        m = _market()
    except Exception:
        m = {"score": 50, "level": "震荡", "advice": "指数数据缺失", "detail": {}}
    date, screen = _screen()
    sectors = _sectors()

    # ── 每日早报（东财+新浪快讯 → DeepSeek 摘要，关联概念库）──
    bdate, brief = _morning_brief()
    if brief:
        with st.expander(f"📰 每日早报 {bdate}（宏观/题材/个股/风险）", expanded=False):
            st.markdown(brief)

    # ── 数据/选股更新状态条 ──
    upd = _last_update()
    upd_ok = upd.get("update_ok")
    badge = ("✓ 已更新" if upd_ok else ("⚠ 更新异常" if upd_ok is False else ""))
    badge_color = S.DOWN if upd_ok else (S.UP if upd_ok is False else S.MUTED)
    st.markdown(
        f'<div class="ap-sub" style="margin:-6px 0 10px">'
        f'🕒 数据/选股更新：<b style="color:{S.WHITE}">{upd["time"]}</b>'
        f' <span style="color:{badge_color}">{badge}</span>'
        f' &nbsp;·&nbsp; 数据交易日 <b style="color:{S.WHITE}">{date or "—"}</b>'
        f' &nbsp;·&nbsp; <span style="color:{S.MUTED}">每日15:30收盘后自动更新并选股</span></div>',
        unsafe_allow_html=True)

    # ── 第一行：大盘基调（三块大数字卡）──
    score = m["score"]
    color = S.UP if score >= 60 else (S.DOWN if score < 40 else S.YELLOW)
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        S.card(S.kpi("大盘综合分", f"{score:.0f}", color, f"满分100 · {date or '—'}"))
    with c2:
        S.card(S.kpi("多空档位", m["level"], color, "量能 · 知行BS · N型 三维"))
    with c3:
        S.card(S.kpi("仓位建议", m["advice"].split("（")[0], S.WHITE,
                     m["advice"]))

    # ── 第二行：大盘分时 + 日K 小图 ──
    _market_charts()

    # ── 第三行：三指数分项 + 板块强弱 ──
    left, right = st.columns([1, 1])
    with left:
        st.markdown("##### 指数三维分项")
        rows = []
        for name, det in m.get("detail", {}).items():
            rows.append(
                S.hbar(name, det["total"], 100,
                       S.UP if det["total"] >= 55 else S.DOWN) +
                f'<div class="ap-sub" style="margin-left:100px">'
                f'量能{det["volume"]["score"]:.0f}·{det["volume"]["note"]} | '
                f'知行{det["zhixing_bs"]["score"]:.0f}·{det["zhixing_bs"]["note"]} | '
                f'N型{det["n_struct"]["score"]:.0f}·{det["n_struct"]["note"]}</div>')
        S.card("".join(rows) or '<div class="ap-sub">无指数数据</div>')
    with right:
        st.markdown("##### 板块强弱")
        if sectors.empty:
            S.card('<div class="ap-sub">运行 daily_screener 生成</div>')
        else:
            top5 = sectors.head(5)
            bot5 = sectors.tail(5).iloc[::-1]
            html = ""
            for _, r in top5.iterrows():
                html += S.hbar(r["sector"], r["score"], 100, S.UP)
            html += f'<div style="border-top:1px solid {S.BORDER};margin:8px 0"></div>'
            for _, r in bot5.iterrows():
                html += S.hbar(r["sector"], r["score"], 100, S.DOWN)
            S.card(html)
        _board_selector()

    # ── 第三行：今日 Top 信号 ──
    st.markdown("##### 今日 Top 信号")
    if screen.empty:
        S.card('<div class="ap-sub">暂无选股结果 — 运行 python scripts/daily_screener.py</div>')
        return
    top = screen.head(10)
    cols = st.columns(5)
    for i, (_, r) in enumerate(top.iterrows()):
        strategies = str(r.get("strategies", "") or "")
        if not strategies or strategies == "nan":
            strategies = "+".join(s for s, c in [("B1", "sig_b1"), ("量能", "sig_volume_b1"),
                                                 ("超短", "sig_zhixing")] if r.get(c)) or "综合"
        strict = "⭐" if r.get("strict_signal") else ""
        chg = float(r.get("pct_change", 0) or 0)
        ml = r.get("ml_score")
        ml_html = (f'<span class="ap-tag">ML {float(ml)*100:.0f}%</span>'
                   if pd.notna(ml) else "")
        concepts = str(r.get("concepts", "") or "")
        concept_html = (f'<div class="ap-sub" style="margin-top:2px">{concepts}</div>'
                        if concepts and concepts != "nan" else "")
        with cols[i % 5]:
            S.card(
                f'<div style="font-size:15px;font-weight:600">{r["symbol"]} '
                f'<span class="ap-sub">{r.get("name", "") if str(r.get("name")) != "nan" else ""}</span> {strict}</div>'
                f'<div style="font-size:26px;font-weight:700;margin:2px 0">{r["score"]:.0f}<span class="ap-sub">分</span></div>'
                f'<div style="color:{S.pct_color(chg)};font-size:13px">{r.get("close", "")} ({chg:+.2f}%)</div>'
                f'<div style="margin-top:4px"><span class="ap-tag">{strategies}</span>'
                f'<span class="ap-tag">{r.get("sector", "") if str(r.get("sector")) != "nan" else "—"}</span>'
                f'{ml_html}</div>{concept_html}')
    st.caption("点击『选股工作台』查看完整列表与K线 · ⭐=满足原始通达信公式全部条件")
