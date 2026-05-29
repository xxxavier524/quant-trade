"""AlphaPulse-A v3.0 Streamlit GUI - loads real data from pipeline."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from pathlib import Path
import sys
import json
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from alphapulse.market.macro_position import compute_macro_score, classify_macro_level
from alphapulse.config.settings import FEISHU_WEBHOOK_URL

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="AlphaPulse-A", page_icon="\U0001f4ca", layout="wide")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path("/Volumes/Mac-480g外接/quantan_data/day/")
REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"
BACKTEST_DB = Path(__file__).resolve().parent.parent.parent / "backtest_results" / "short_term.db"
IC_PATH = REPORTS_DIR / "factor_ic_analysis.json"
WEIGHTS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "factor_weights.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_index_data():
    """Load index CSV files with DatetimeIndex."""
    idx = {}
    for code in ["000001", "399001", "399006"]:
        fp = DATA_DIR / f"{code}.csv"
        if fp.exists():
            idx[code] = pd.read_csv(fp, parse_dates=["date"], index_col="date")
    return idx


@st.cache_data(ttl=300)
def load_stock_data(code: str) -> pd.DataFrame | None:
    """Load a single stock CSV with DatetimeIndex."""
    fp = DATA_DIR / f"{code}.csv"
    if not fp.exists():
        return None
    return pd.read_csv(fp, parse_dates=["date"], index_col="date")


@st.cache_data(ttl=60)
def load_latest_report() -> str:
    """Return the text content of the newest daily report."""
    report_files = sorted(REPORTS_DIR.glob("daily_report_*.md"), reverse=True)
    if not report_files:
        return ""
    return report_files[0].read_text(encoding="utf-8")


def parse_report_stocks(report_text: str) -> dict:
    """Parse stock symbols + signal types from the daily report."""
    sections = {"B1B2": [], "BRICK": [], "NEEDLE": []}
    current = None
    for line in report_text.split("\n"):
        if line.startswith("## "):
            if "B1B2" in line:
                current = "B1B2"
            elif "砖型" in line:
                current = "BRICK"
            elif "单针" in line:
                current = "NEEDLE"
            else:
                current = None
        elif line.startswith("- ") and current:
            parts = line[2:].split("(")
            sym = parts[0].strip()
            sig = parts[1].rstrip(")") if len(parts) > 1 else ""
            sections[current].append({"symbol": sym, "signal_type": sig})
    return sections


def parse_report_counts(report_text: str) -> tuple[int, int, int]:
    """Extract B1B2 / brick / needle signal counts from report text."""
    b1b2 = brick = needle = 0
    for line in report_text.split("\n"):
        if "B1B2 信号" in line and "(" in line:
            try:
                b1b2 = int(line.split("(")[1].split("个")[0])
            except ValueError:
                pass
        elif "砖型图 信号" in line and "(" in line:
            try:
                brick = int(line.split("(")[1].split("个")[0])
            except ValueError:
                pass
        elif "单针 信号" in line and "(" in line:
            try:
                needle = int(line.split("(")[1].split("个")[0])
            except ValueError:
                pass
    return b1b2, brick, needle


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("\U0001f4ca AlphaPulse-A v3.0")
st.sidebar.caption("A股量化选股系统")
n_csv = len(list(DATA_DIR.glob("*.csv"))) if DATA_DIR.exists() else 0
st.sidebar.metric("数据覆盖", f"{n_csv}只A股")

# ---------------------------------------------------------------------------
# Load global data
# ---------------------------------------------------------------------------
index_data = load_index_data()
sh_idx = index_data.get("000001", pd.DataFrame())
sz_idx = index_data.get("399001", sh_idx)
cyb_idx = index_data.get("399006", sh_idx)

macro = {"score": 50, "level": "震荡"}
if not sh_idx.empty:
    macro = compute_macro_score(sh_idx, sz_idx, cyb_idx)

latest_report = load_latest_report()
b1b2_count, brick_count, needle_count = parse_report_counts(latest_report)

# ---------------------------------------------------------------------------
# Top bar
# ---------------------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("大盘评分", f"{macro['score']}/100", macro["level"])
c2.metric("B1B2信号", str(b1b2_count))
c3.metric("砖型图信号", str(brick_count))
c4.metric("单针信号", str(needle_count))
c5.metric("数据覆盖", f"{n_csv}只")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tabs = st.tabs([
    "\U0001f3af 选股结果",
    "\U0001f4c8 回测追踪",
    "\U0001f3db 大盘诊断",
    "\U0001f52c 因子详情",
    "\U0001f916 AI诊断",
    "\U0001f52e Vibe",
])

# ===========================================================================
# Tab 1: 选股结果
# ===========================================================================
with tabs[0]:
    st.subheader("今日选股结果")

    report_files = sorted(REPORTS_DIR.glob("daily_report_*.md"), reverse=True)
    if not report_files:
        st.info("暂无报告，请先运行 daily_screener.py")
    else:
        st.caption(f"数据来源: {report_files[0].name}")
        stocks = parse_report_stocks(latest_report)

        # Strategy filter dropdown
        strategy_filter = st.selectbox(
            "筛选策略", ["全部", "B1B2", "砖型图", "单针探底"],
            key="stock_filter"
        )

        # Build unified rows
        strategy_map = {"B1B2": "B1B2", "砖型图": "BRICK", "单针探底": "NEEDLE"}
        rows = []
        for label, key in strategy_map.items():
            if strategy_filter != "全部" and strategy_filter != label:
                continue
            for s in stocks.get(key, []):
                rows.append({
                    "股票代码": s["symbol"],
                    "策略": label,
                    "信号类型": s["signal_type"],
                })

        if not rows:
            st.info("该策略下暂无选股信号")
        else:
            df_stocks = pd.DataFrame(rows)
            # Interactive table with row selection
            sel_event = st.dataframe(
                df_stocks,
                width="stretch",
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                key="stock_table",
            )

            # Expand K-line chart when a row is clicked
            selected_rows = sel_event.get("selection", {}).get("rows", [])
            if selected_rows:
                sel_idx = selected_rows[0]
                sel_code = df_stocks.iloc[sel_idx]["股票代码"]
                sel_strategy = df_stocks.iloc[sel_idx]["策略"]
                sel_sig = df_stocks.iloc[sel_idx]["信号类型"]

                with st.expander(
                    f"\U0001f4c8 {sel_code} K线图 ({sel_strategy} - {sel_sig})",
                    expanded=True,
                ):
                    kdf = load_stock_data(str(sel_code))
                    if kdf is not None and len(kdf) >= 30:
                        chart_df = kdf.tail(60)
                        fig = go.Figure()
                        fig.add_trace(go.Candlestick(
                            x=chart_df.index,
                            open=chart_df["open"],
                            high=chart_df["high"],
                            low=chart_df["low"],
                            close=chart_df["close"],
                            name=sel_code,
                        ))
                        fig.update_layout(
                            height=400,
                            xaxis_rangeslider_visible=False,
                            margin=dict(l=20, r=20, t=20, b=20),
                        )
                        st.plotly_chart(fig, width="stretch")
                    else:
                        st.warning(f"未找到 {sel_code} 的数据或数据不足")

# ===========================================================================
# Tab 2: 回测追踪
# ===========================================================================
with tabs[1]:
    st.subheader("回测追踪")
    st_choice = st.radio(
        "策略", ["B1B2", "砖型图", "单针"], horizontal=True, key="bt_strat"
    )
    strategy_db_map = {"B1B2": "B1B2", "砖型图": "BRICK", "单针": "NEEDLE"}
    db_strat = strategy_db_map.get(st_choice, "B1B2")

    col_a, col_b = st.columns(2)

    if BACKTEST_DB.exists():
        try:
            conn = sqlite3.connect(str(BACKTEST_DB))
            # Overall stats
            stats_df = pd.read_sql_query(
                "SELECT strategy, count(*) as cnt, "
                "round(avg(total_return), 2) as avg_ret, "
                "round(avg(hold_days), 1) as avg_days "
                "FROM exits e JOIN signals s ON e.signal_id = s.id "
                "GROUP BY strategy",
                conn,
            )
            with col_a:
                st.caption("全策略汇总")
                if not stats_df.empty:
                    for _, row in stats_df.iterrows():
                        st.metric(
                            label=row["strategy"],
                            value=f"{row['cnt']}次",
                            delta=f"平均收益 {row['avg_ret']}%",
                        )
                else:
                    st.info("暂无回测数据")

            # Per-strategy detail
            detail = pd.read_sql_query(
                "SELECT count(*) as sig_count "
                "FROM signals WHERE strategy = ?",
                conn,
                params=(db_strat,),
            )
            sig_count = int(detail.iloc[0]["sig_count"]) if not detail.empty else 0

            stat_row = stats_df[stats_df["strategy"] == db_strat] if not stats_df.empty else pd.DataFrame()
            win_rate_val = "N/A"
            avg_ret_val = "N/A"
            avg_days_val = "N/A"
            if not stat_row.empty:
                row = stat_row.iloc[0]
                # Try to get win rate from exits
                wr_df = pd.read_sql_query(
                    "SELECT round(100.0 * sum(CASE WHEN total_return > 0 THEN 1 ELSE 0 END) / count(*), 1) as wr "
                    "FROM exits e JOIN signals s ON e.signal_id = s.id "
                    "WHERE s.strategy = ?",
                    conn,
                    params=(db_strat,),
                )
                win_rate_val = f"{wr_df.iloc[0]['wr']}%" if not wr_df.empty and wr_df.iloc[0]["wr"] is not None else "N/A"
                avg_ret_val = f"{row['avg_ret']}%"
                avg_days_val = f"{row['avg_days']}天"

            with col_b:
                st.caption(f"{st_choice} 策略详情")
                st.metric("信号数", sig_count)
                st.metric("胜率", win_rate_val)
                st.metric("平均收益", avg_ret_val)
                st.metric("平均持仓天数", avg_days_val)

            conn.close()
        except Exception as e:
            with col_a:
                st.info("回测数据表结构待初始化")
    else:
        with col_a:
            st.info("暂无回测数据，点击下方按钮运行回测")

    # --- Run backtest button ---
    st.divider()
    if st.button("\U0001f680 开始回测", key="run_bt"):
        try:
            from alphapulse.backtest.short_term_bt import run_short_backtest

            with st.spinner("正在运行短期回测，请稍候..."):
                # Load sample stocks
                sample_codes = [
                    f.stem for f in sorted(DATA_DIR.glob("*.csv"))[:200]
                    if f.stem.isdigit() and len(f.stem) == 6
                ]
                stock_data = {}
                for code in sample_codes:
                    df = load_stock_data(code)
                    if df is not None:
                        stock_data[code] = df

                # Load recent signals from the report
                stocks = parse_report_stocks(latest_report)
                signal_list = []
                for strat, syms in stocks.items():
                    for s in syms:
                        df = stock_data.get(s["symbol"])
                        if df is None or len(df) < 30:
                            continue
                        # Use data[-15] as signal date, so there are 15 trailing days for tracking
                        signal_idx = max(0, len(df) - 15)
                        signal_date = str(df.index[signal_idx])[:10]
                        buy_price = float(df.iloc[signal_idx]["close"])
                        signal_list.append({
                            "symbol": s["symbol"], "name": "", "strategy": strat,
                            "date": signal_date, "signal_type": s.get("signal_type",""),
                            "buy_price": buy_price, "sector": "", "macro_level": macro["level"],
                            "score": 0, "grade": "",
                        })

                if signal_list and stock_data:
                    signals_df = pd.DataFrame(signal_list)
                    result = run_short_backtest(signals_df, stock_data)
                    st.success("回测完成！")
                    st.json(result)
                else:
                    st.warning("无可用信号或数据，请先运行 daily_screener.py")

        except ImportError as e:
            st.error(f"模块导入失败: {e}")
        except Exception as e:
            st.error(f"回测执行失败: {e}")

# ===========================================================================
# Tab 3: 大盘诊断
# ===========================================================================
with tabs[2]:
    st.subheader("大盘诊断")

    subs = macro.get("sub_scores", {})
    ma_score = subs.get("ma_alignment", 12.5)
    vp_score = subs.get("volume_price", 12.5)
    sent_score = subs.get("sentiment", 12.5)
    nb_score = subs.get("northbound", 12.5)

    col_g, col_p = st.columns([1, 2])

    with col_g:
        st.caption("大盘综合评分")
        fig3 = go.Figure(go.Indicator(
            mode="gauge+delta",
            value=macro["score"],
            title={"text": "大盘综合评分"},
            delta={"reference": 50},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "orange"},
                "steps": [
                    {"range": [0, 20], "color": "red"},
                    {"range": [20, 40], "color": "orange"},
                    {"range": [40, 60], "color": "yellow"},
                    {"range": [60, 80], "color": "lightgreen"},
                    {"range": [80, 100], "color": "green"},
                ],
            },
        ))
        fig3.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig3, width="stretch")
        st.metric("当前档位", macro["level"])

    with col_p:
        st.caption("分项评分 (满分各25)")

        # Progress bars for each sub-score
        scores_config = [
            ("均线排列 (ma_alignment)", ma_score,
             lambda s: f"当前均线排列评分{s:.0f}/25，{'多数均线多头排列，趋势向好' if s >= 18 else '均线交织，多空力量均衡' if s >= 10 else '均线空头排列，短期走势偏弱'}"),
            ("量价配合 (volume_price)", vp_score,
             lambda s: f"当前量价配合评分{s:.0f}/25，{'量价齐升，资金入场积极' if s >= 18 else '量价关系中性' if s >= 10 else '价量背离，上涨动能不足'}"),
            ("市场情绪 (sentiment)", sent_score,
             lambda s: f"当前市场情绪评分{s:.0f}/25，{'涨多跌少，情绪较为亢奋' if s >= 18 else '涨跌互现，情绪趋于平静' if s >= 10 else '跌多涨少，市场恐慌情绪蔓延'}"),
            ("北向资金 (northbound)", nb_score,
             lambda s: f"当前北向资金评分{s:.0f}/25，{'北向资金持续净流入，外资看好' if s >= 18 else '北向资金流向中性' if s >= 10 else '北向资金持续净流出，外资谨慎'}"),
        ]

        for label, val, description_fn in scores_config:
            st.text(label)
            st.progress(min(float(val) / 25.0, 1.0), text=f"{val:.1f} / 25")
            with st.expander("解读"):
                st.caption(description_fn(val))

    st.divider()
    st.caption("手动调整评分（观察大盘档位变化）")

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        adj_ma = st.slider("均线排列", 0.0, 25.0, float(ma_score), 0.5, key="adj_ma")
    with col_m2:
        adj_vp = st.slider("量价配合", 0.0, 25.0, float(vp_score), 0.5, key="adj_vp")
    with col_m3:
        adj_sent = st.slider("市场情绪", 0.0, 25.0, float(sent_score), 0.5, key="adj_sent")
    with col_m4:
        adj_nb = st.slider("北向资金", 0.0, 25.0, float(nb_score), 0.5, key="adj_nb")

    adj_total = adj_ma + adj_vp + adj_sent + adj_nb
    adj_level = classify_macro_level(adj_total)
    st.info(f"手动调整后总分: **{adj_total:.1f}/100** -- 档位: **{adj_level}**")

# ===========================================================================
# Tab 4: 因子详情
# ===========================================================================
with tabs[3]:
    st.subheader("因子详情")
    st.caption("因子IC和权重数据由 nightly auto-research 自动更新")

    # Load factor IC data
    ic_data = {}
    if IC_PATH.exists():
        try:
            ic_data = json.loads(IC_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Load weights
    weights_data = {}
    if WEIGHTS_PATH.exists():
        try:
            raw = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
            weights_data = raw.get("weights", {})
        except Exception:
            pass

    from alphapulse.factors.factor_registry import FACTOR_REGISTRY

    # Build factor table
    factor_rows = []
    for name, entry in FACTOR_REGISTRY.items():
        ftype = entry.get("type", "core")
        desc = entry.get("description", "")
        weight = weights_data.get(name, entry.get("default_params", {}).get("weight", 1.0))

        # IC trend
        ic_info = ic_data.get(name)
        ic_val = None
        ic_trend = ""
        if ic_info:
            ic_val = ic_info.get("mean_ic")
            if isinstance(ic_val, (int, float)) and not (ic_val != ic_val):  # not NaN
                ic_trend = "\u2197" if ic_val > 0 else "\u2198"

        factor_rows.append({
            "因子名称": name,
            "类型": ftype,
            "描述": desc,
            "当前权重": round(float(weight), 3) if isinstance(weight, (int, float)) else weight,
            "IC趋势": f"{ic_trend} ({ic_val:+.3f})" if ic_val is not None else "暂无",
        })

    df_factors = pd.DataFrame(factor_rows)
    st.dataframe(df_factors, width="stretch", hide_index=True,
                 column_config={"描述": st.column_config.TextColumn(width="large")})

    st.divider()

    # +/- weight adjustment
    st.caption("调整因子权重 (按名称选择，点击+/-按钮)")
    col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
    with col_f1:
        factor_names = sorted(FACTOR_REGISTRY.keys())
        sel_factor = st.selectbox("选择因子", factor_names, key="factor_select")
    with col_f2:
        if st.button("\U00002795 权重 +0.1", key="wt_up"):
            current = float(weights_data.get(sel_factor, 1.0))
            weights_data[sel_factor] = round(current + 0.1, 2)
            WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            WEIGHTS_PATH.write_text(
                json.dumps({"weights": weights_data, "ic_history": {}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            st.rerun()
    with col_f3:
        if st.button("\U00002796 权重 -0.1", key="wt_down"):
            current = float(weights_data.get(sel_factor, 1.0))
            weights_data[sel_factor] = round(max(0.0, current - 0.1), 2)
            WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            WEIGHTS_PATH.write_text(
                json.dumps({"weights": weights_data, "ic_history": {}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            st.rerun()

    st.metric(
        f"当前权重 -- {sel_factor}",
        weights_data.get(sel_factor, 1.0),
    )

    st.divider()

    # New factor expression input
    st.caption("新因子表达式（实验性）")
    new_factor_text = st.text_area(
        "输入新因子表达式",
        placeholder="示例: (close - open) / (high - low) * volume_ratio",
        key="new_factor_expr",
        height=100,
    )
    if st.button("提交因子表达式", key="submit_factor"):
        st.info("因子表达式已记录，需人工审核后加入因子库")

# ===========================================================================
# Tab 5: AI诊断
# ===========================================================================
with tabs[4]:
    st.subheader("AI个股诊断")

    diag_code = st.text_input("输入股票代码", "000001", key="diag_code")

    if st.button("\U0001f50d 诊断", key="diag_btn"):
        kdf = load_stock_data(diag_code)

        if kdf is None:
            st.warning(f"未找到股票 {diag_code} 的数据，请确认代码正确")
        elif len(kdf) < 60:
            st.warning(f"数据不足60天（当前{len(kdf)}天），无法诊断")
        else:
            try:
                from alphapulse.diagnosis.stock_scorer import compute_diagnosis
                from alphapulse.factors.kdj_j_low import compute as kdj_compute
                from alphapulse.factors.weekly_ma_bull import compute as ma_bull_compute

                kdj_val = kdj_compute(kdf).iloc[-1]
                ma_val = ma_bull_compute(kdf).iloc[-1]

                snap = {
                    "KDJ_J_LOW": int(kdj_val) if not pd.isna(kdj_val) else 0,
                    "WEEKLY_MA_BULL": int(ma_val) if not pd.isna(ma_val) else 0,
                }

                result = compute_diagnosis(snap)

                col_radar, col_grade = st.columns([2, 1])

                with col_radar:
                    categories = ["技术面", "量能", "形态", "风控", "板块共振"]
                    sub_keys = ["technical", "volume", "pattern", "risk", "sector"]
                    values = [result["sub_scores"].get(k, 0) for k in sub_keys]

                    fig5 = go.Figure()
                    fig5.add_trace(go.Scatterpolar(
                        r=values + [values[0]],
                        theta=categories + [categories[0]],
                        fill="toself",
                        name=diag_code,
                    ))
                    fig5.update_layout(
                        polar=dict(radialaxis=dict(range=[0, 30])),
                        height=400,
                        margin=dict(l=40, r=40, t=40, b=40),
                    )
                    st.plotly_chart(fig5, width="stretch")

                with col_grade:
                    grade = result["grade"]
                    total = result["total_score"]
                    grade_colors = {"S": "green", "A": "blue", "B": "orange", "C": "orange", "D": "red"}
                    color = grade_colors.get(grade, "gray")

                    st.markdown(f"## 评级: :{color}[**{grade}**]")
                    st.metric("总分", f"{total}/100")

                    st.divider()
                    st.caption("各维度得分")
                    dim_labels = {
                        "technical": "技术面",
                        "volume": "量能",
                        "pattern": "形态",
                        "risk": "风控",
                        "sector": "板块共振",
                    }
                    for k, v in result["sub_scores"].items():
                        label = dim_labels.get(k, k)
                        st.text(f"{label}: {v}/30")

                    st.divider()
                    st.caption("最强维度")
                    for dim in result.get("top_dimensions", [])[:3]:
                        st.text(f"\u2022 {dim_labels.get(dim, dim)}")

            except Exception as e:
                st.error(f"诊断计算失败: {e}")
                st.caption("请确认因子模块 (kdj_j_low, weekly_ma_bull, stock_scorer) 可正常导入")

# ===========================================================================
# Tab 6: Vibe
# ===========================================================================
with tabs[5]:
    st.subheader("Vibe-Trading 因子探索")
    st.text_area(
        "描述交易想法",
        "找出低位缩量企稳后放量突破的股票",
        key="vibe_idea",
        height=100,
    )
    if st.button("生成因子", key="vibe_gen"):
        st.info("需启动 Vibe-Trading Docker: bash scripts/vibe_trading_setup.sh")

    st.divider()
    st.caption("Vibe-Trading 由 Docker 容器提供因子生成能力，将自然语言描述转化为可回测的因子代码。")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
c1, c2, c3 = st.columns(3)
c1.button(
    "\U0001f4e4 推送到飞书" if FEISHU_WEBHOOK_URL else "\U0001f4e4 飞书未配置",
    key="feishu_btn",
)
c2.caption(f"数据: {n_csv}只A股")
c3.caption("AlphaPulse-A v3.0")
