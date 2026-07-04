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


@st.cache_data(ttl=300)
def _factor_frame():
    """全市场因子帧（含全部子分数+黄线位置），供交互重排。"""
    files = sorted(REPORTS_DIR.glob("factor_frame_*.csv"))
    if not files:
        return "", pd.DataFrame()
    return files[-1].stem.replace("factor_frame_", ""), pd.read_csv(files[-1], dtype={"symbol": str})


@st.cache_data(ttl=300)
def _macro_level() -> str:
    try:
        from alphapulse.market.market_score import compute_market_score
        return compute_market_score().get("level", "震荡")
    except Exception:
        return "震荡"


# 可交互调权的子分数（中文名）
ADJ_FACTORS = {
    "j_low": "J值低位", "trend_gap": "趋势强度", "vol_shrink": "缩量",
    "yangyin": "红肥绿瘦", "surge": "爆量阳", "weekly_cross": "周线金叉",
    "ml_score": "ML胜率", "bowl": "掉进碗里",
}


def _interactive_panel(date: str, fdf: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """交互式选股控制面板 → 返回 (全市场重排结果, 每类显示数量)。

    全市场排序一次（不截断），四类视图各自从全量结果切片，
    避免 B1/单针 等小众类别被综合 Top-N 截掉。
    """
    from alphapulse.ranking.composite import rank_all, load_weights

    with st.expander("⚙️ 选股条件与参数（调整后点『重新选股』）", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        above_yellow = c1.toggle("股价必须站上黄线", value=True,
                                 help="知行多空线之上才是多头回调买点（铁律，默认开）")
        only_strict = c2.toggle("仅严格信号 ⭐", value=False,
                                help="只保留满足B1/量能B1/知行超短/单针原始公式的票")
        min_score = c3.slider("最低评分", 0, 100, 0, 5)
        top_n = c4.select_slider("每类显示数量", [20, 30, 50, 80, 100], value=50)

        sec_min = st.slider("所属板块强度下限（0=不限）", 0, 100, 0, 5,
                            help="只保留处于强势板块的个股")

        st.caption("因子权重微调（拖动改变各维度在总分中的占比，0=忽略该因子）")
        weights = dict(load_weights())
        wcols = st.columns(4)
        for i, (k, cn) in enumerate(ADJ_FACTORS.items()):
            if k in weights:
                weights[k] = wcols[i % 4].slider(
                    cn, 0.0, 0.4, float(weights[k]), 0.01, key=f"wbw_{k}")

        rerun = st.button("🔄 重新选股", type="primary")

    # 触发重排（首次进入也算一次）；存全市场排序结果，类别切片在 render 做
    key = f"wb_ranked_{date}"
    cond_key = (above_yellow, only_strict, min_score, sec_min, tuple(sorted(weights.items())))
    if rerun or key not in st.session_state or st.session_state.get(f"{key}_cond") != cond_key:
        work = fdf.copy()
        if sec_min > 0 and "sector_score" in work.columns:
            work = work[pd.to_numeric(work["sector_score"], errors="coerce").fillna(0) >= sec_min]
        # top_n=全量 → 得到完整排序帧，供四类切片
        ranked = rank_all(work, top_n=len(work) or 1, macro_level=_macro_level(),
                          require_above_yellow=above_yellow, weights=weights)
        if not ranked.empty:
            if only_strict and "strict_signal" in ranked.columns:
                ranked = ranked[ranked["strict_signal"]].reset_index(drop=True)
            if min_score > 0:
                ranked = ranked[ranked["score"] >= min_score].reset_index(drop=True)
            ranked["rank"] = range(1, len(ranked) + 1)
            # 补策略/概念列（与daily_screener口径一致）
            ranked = _add_strategy_cols(ranked)
        st.session_state[key] = ranked
        st.session_state[f"{key}_cond"] = cond_key
        if rerun:
            st.toast(f"已重新选股：全市场 {len(ranked)} 只（{'站上黄线' if above_yellow else '不限黄线'}）")
    return st.session_state.get(key, pd.DataFrame()), top_n


# ── 四类选股 ──
def _as_bool(s: pd.Series) -> pd.Series:
    """CSV 读回的 sig_* 可能是 bool 或 'True'/'False' 字符串，统一成 bool。"""
    if s.dtype == bool:
        return s
    return s.astype(str).str.strip().str.lower().isin(("true", "1", "1.0"))


def _category_mask(df: pd.DataFrame, cat: str) -> pd.Series:
    """四类选股的成员掩码。"""
    def col(name):
        return _as_bool(df[name]) if name in df.columns else pd.Series(False, index=df.index)
    if cat == "B1":          # 要求最高：B1六条件公式全满足（完美图形）
        return col("sig_b1")
    if cat == "超短":         # 更宽：知行超短 ∪ 量能B1
        return col("sig_zhixing") | col("sig_volume_b1")
    if cat == "单针下三十":    # 长下影+J超卖+低位+缩量
        return col("sig_needle")
    return pd.Series(True, index=df.index)  # 综合评分：全部


CATEGORIES = ["综合评分", "B1", "超短", "单针下三十"]
CAT_DESC = {
    "综合评分": "全市场加权评分排序（0-100），不限信号类型。",
    "B1": "要求最高：B1 六条件公式全部满足的『完美图形』票（涨幅±3%/振幅<9%/J<13/白>黄/DIF>-0.1/市值>10亿）。",
    "超短": "较多：知行超短 ∪ 量能B1 原始公式触发的短线买点。",
    "单针下三十": "长下影单针探底 + J值超卖 + 近60日区间下30% + 缩量确认。",
}

# Excel 导出列（含子分数明细）
_XLSX_COLS = ["rank", "symbol", "name", "score", "pattern_state",
              "strategies", "sector", "concepts",
              "close", "pct_change", "yellow_line", "above_yellow", "strict_signal",
              "sig_b1", "sig_volume_b1", "sig_zhixing", "sig_needle", "ml_score",
              "j_low", "trend_gap", "vol_shrink", "yangyin", "surge", "dif", "ql_pos",
              "amplitude", "bowl", "washout_recover", "weekly_cross", "sector_score"]
_XLSX_HEAD = {"rank": "排名", "symbol": "代码", "name": "名称", "score": "评分",
              "pattern_state": "战法态",
              "strategies": "选股策略", "sector": "板块", "concepts": "概念",
              "close": "现价", "pct_change": "涨幅%", "yellow_line": "黄线",
              "above_yellow": "站上黄线", "strict_signal": "严格信号",
              "sector_score": "板块强度"}


def _to_excel(df: pd.DataFrame, cat: str) -> bytes:
    """当前类别结果导出为 xlsx 字节流（供 download_button）。"""
    import io
    cols = [c for c in _XLSX_COLS if c in df.columns]
    out = df[cols].rename(columns=_XLSX_HEAD)
    buf = io.BytesIO()
    sheet = (cat or "选股")[:31]
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        out.to_excel(w, index=False, sheet_name=sheet)
    return buf.getvalue()


def _wheel_nav_js():
    """K线上滚轮上下 / ↑↓方向键 → 点击『上一只/下一只』按钮（同源父文档，best-effort）。"""
    import streamlit.components.v1 as components
    components.html(
        """<script>
        const doc = window.parent.document;
        if (!doc.__apNavBound) {
          doc.__apNavBound = true;
          const click = (lbl) => {
            const b = Array.from(doc.querySelectorAll('button'))
              .find(x => ((x.innerText)||'').trim().includes(lbl));
            if (b && !b.disabled) b.click();
          };
          let lock = false;
          const step = (down) => {
            if (lock) return; lock = true; setTimeout(() => { lock = false; }, 320);
            click(down ? '下一只' : '上一只');
          };
          doc.addEventListener('wheel', (e) => {
            const t = e.target;
            if (!t || !t.closest || !t.closest('.stPlotlyChart, .js-plotly-plot')) return;
            e.preventDefault();
            if (e.deltaY > 0) step(true); else if (e.deltaY < 0) step(false);
          }, {passive: false, capture: true});
          doc.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); step(true); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); step(false); }
          });
        }
        </script>""", height=0)


def _add_strategy_cols(df: pd.DataFrame) -> pd.DataFrame:
    def _strat(r):
        tags = []
        if r.get("sig_b1"):
            tags.append("B1")
        if r.get("sig_volume_b1"):
            tags.append("量能B1")
        if r.get("sig_zhixing"):
            tags.append("知行超短")
        if r.get("sig_needle"):
            tags.append("单针下三十")
        if float(r.get("weekly_cross", 0) or 0) >= 1.0:
            tags.append("周线金叉")
        return "+".join(tags) or "综合评分"
    df = df.copy()
    df["strategies"] = df.apply(_strat, axis=1)
    return df


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
    fdate, fdf = _factor_frame()
    if fdf.empty:
        # 回退到静态 Top50（旧版兼容）
        fdate, ranked = _screen()
        if ranked.empty:
            st.info("暂无选股结果 — 运行 `python scripts/daily_screener.py`")
            return
        ranked = ranked.reset_index(drop=True)
        display_n = len(ranked)
    else:
        st.caption(f"数据日 {fdate} · 全市场 {len(fdf)} 只 · "
                   f"站上黄线 {int(fdf['above_yellow'].sum()) if 'above_yellow' in fdf else '—'} 只")
        ranked, display_n = _interactive_panel(fdate, fdf)
        if ranked.empty:
            st.warning("当前条件下无选股结果，放宽条件后重试")
            return

    # ── 四类选股切换（综合评分 / B1 / 超短 / 单针下三十）──
    counts = {c: int(_category_mask(ranked, c).sum()) for c in CATEGORIES}
    cat_labels = {f"{c}（{counts[c]}）": c for c in CATEGORIES}
    choice = st.radio("选股类型", list(cat_labels), horizontal=True, key="wb_category",
                      label_visibility="collapsed")
    cat = cat_labels[choice]
    st.caption(CAT_DESC[cat])

    cat_df = ranked[_category_mask(ranked, cat)].reset_index(drop=True)
    if cat_df.empty:
        if cat == "单针下三十" and "sig_needle" not in ranked.columns:
            st.warning("当前选股结果尚无『单针下三十』信号列 — 请重新运行 "
                       "`python scripts/daily_screener.py` 生成最新因子帧。")
        else:
            st.info(f"今日无『{cat}』类选股结果。")
        return
    cat_df = cat_df.head(display_n).copy()
    cat_df["rank"] = range(1, len(cat_df) + 1)

    # 板块快速筛选（在类别结果上）
    sectors = ["全部"] + sorted(s for s in cat_df.get("sector", pd.Series()).dropna().unique() if s)
    sel_sector = st.selectbox("板块快筛", sectors, key="wb_sec_filter")
    view = cat_df if sel_sector == "全部" else cat_df[cat_df["sector"] == sel_sector]
    view = view.reset_index(drop=True)

    # ── 一键导出 Excel（当前类别 + 板块筛选后的结果）──
    dl_col, info_col = st.columns([1, 5])
    dl_col.download_button(
        "⬇️ 导出 Excel", _to_excel(view, cat),
        file_name=f"选股_{cat}_{fdate or 'latest'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True, key="wb_xlsx")
    info_col.caption(f"『{cat}』共 {len(view)} 只"
                     + (f" · 板块：{sel_sector}" if sel_sector != "全部" else "")
                     + " · 点击行查看依据与K线")

    show_cols = [c for c in ["rank", "symbol", "name", "score", "pattern_state",
                             "strategies", "sector", "concepts", "pct_change",
                             "strict_signal", "ml_score"] if c in view.columns]
    event = st.dataframe(
        view[show_cols], height=420, hide_index=True, use_container_width=True,
        column_config={
            "rank": st.column_config.NumberColumn("#", width="small"),
            "symbol": "代码", "name": "名称",
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100, format="%.0f"),
            "pattern_state": st.column_config.TextColumn(
                "战法态", width="small",
                help="B2确认=放量确认已现(统计优势所在,B1→B2序列72%+胜率) / "
                     "B1候B2=信号已出等确认 / 单针探底 / 无"),
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
    syms = view["symbol"].astype(str).tolist()
    if not symbol or symbol not in syms:
        symbol = syms[0] if syms else None
    if symbol:
        # ── 上一只/下一只切换（按钮 + K线滚轮上下 + ↑↓方向键）──
        cur_i = syms.index(symbol)
        nprev, nnext, nlbl = st.columns([2, 2, 6])
        if nprev.button("◀ 上一只", use_container_width=True,
                        disabled=cur_i <= 0, key="wb_prev"):
            st.session_state["wb_symbol"] = syms[cur_i - 1]
            st.rerun()
        if nnext.button("下一只 ▶", use_container_width=True,
                        disabled=cur_i >= len(syms) - 1, key="wb_next"):
            st.session_state["wb_symbol"] = syms[cur_i + 1]
            st.rerun()
        nlbl.caption(f"第 {cur_i + 1}/{len(syms)} 只 · 鼠标在K线上滚轮上下 或 ↑↓方向键 切换股票")
        _wheel_nav_js()
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
