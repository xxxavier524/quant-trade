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


def render():
    try:
        m = _market()
    except Exception:
        m = {"score": 50, "level": "震荡", "advice": "指数数据缺失", "detail": {}}
    date, screen = _screen()
    sectors = _sectors()

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

    # ── 第二行：三指数分项 + 板块强弱 ──
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
                tag = f'<span class="ap-tag">{r["tags"]}</span>' if r.get("tags") else ""
                html += S.hbar(r["sector"], r["score"], 100, S.UP)
            html += f'<div style="border-top:1px solid {S.BORDER};margin:8px 0"></div>'
            for _, r in bot5.iterrows():
                html += S.hbar(r["sector"], r["score"], 100, S.DOWN)
            S.card(html)

    # ── 第三行：今日 Top 信号 ──
    st.markdown("##### 今日 Top 信号")
    if screen.empty:
        S.card('<div class="ap-sub">暂无选股结果 — 运行 python scripts/daily_screener.py</div>')
        return
    top = screen.head(10)
    cols = st.columns(5)
    for i, (_, r) in enumerate(top.iterrows()):
        sigs = [s for s, c in [("B1", "sig_b1"), ("量能", "sig_volume_b1"),
                               ("超短", "sig_zhixing")] if r.get(c)]
        strict = "⭐" if r.get("strict_signal") else ""
        chg = float(r.get("pct_change", 0) or 0)
        ml = r.get("ml_score")
        ml_html = (f'<span class="ap-tag">ML {float(ml)*100:.0f}%</span>'
                   if pd.notna(ml) else "")
        with cols[i % 5]:
            S.card(
                f'<div style="font-size:15px;font-weight:600">{r["symbol"]} '
                f'<span class="ap-sub">{r.get("name", "") if str(r.get("name")) != "nan" else ""}</span> {strict}</div>'
                f'<div style="font-size:26px;font-weight:700;margin:2px 0">{r["score"]:.0f}<span class="ap-sub">分</span></div>'
                f'<div style="color:{S.pct_color(chg)};font-size:13px">{r.get("close", "")} ({chg:+.2f}%)</div>'
                f'<div style="margin-top:4px"><span class="ap-tag">{r.get("sector", "") if str(r.get("sector")) != "nan" else "—"}</span>'
                f'{"".join(f"<span class=ap-tag>" + s + "</span>" for s in sigs)}{ml_html}</div>')
    st.caption("点击『选股工作台』查看完整列表与K线 · ⭐=满足原始通达信公式全部条件")
