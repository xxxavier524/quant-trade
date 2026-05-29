"""AlphaPulse-A v3.0 Streamlit GUI - loads real data from pipeline."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from pathlib import Path
import sys, json
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from alphapulse.market.macro_position import compute_macro_score, classify_macro_level
from alphapulse.config.settings import FEISHU_WEBHOOK_URL

st.set_page_config(page_title="AlphaPulse-A", page_icon="📊", layout="wide")

DATA_DIR = Path("/Volumes/Mac-480g外接/quantan_data/day/")
REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"

st.sidebar.title("📊 AlphaPulse-A v3.0")
st.sidebar.caption("A股量化选股系统")

# Load the latest report for display
latest_report = ""
report_files = sorted(REPORTS_DIR.glob("daily_report_*.md"), reverse=True)
if report_files:
    latest_report = report_files[0].read_text(encoding="utf-8")

# === TOP BAR: Real Macro Score ===
sh_path, sz_path, cyb_path = DATA_DIR / "000001.csv", DATA_DIR / "399001.csv", DATA_DIR / "399006.csv"
sh_idx = pd.read_csv(sh_path, parse_dates=["date"]) if sh_path.exists() else pd.DataFrame()
sz_idx = pd.read_csv(sz_path, parse_dates=["date"]) if sz_path.exists() else pd.DataFrame()
cyb_idx = pd.read_csv(cyb_path, parse_dates=["date"]) if cyb_path.exists() else pd.DataFrame()

macro = {"score": 50, "level": "震荡"}
if not sh_idx.empty:
    macro = compute_macro_score(sh_idx, sz_idx if not sz_idx.empty else sh_idx, cyb_idx if not cyb_idx.empty else sh_idx)

# Parse report for signal counts
b1b2_count = brick_count = needle_count = 0
strong_sectors = []
for line in latest_report.split("\n"):
    if "B1B2 信号" in line:
        b1b2_count = int(line.split("(")[1].split("个")[0]) if "(" in line else 0
    elif "砖型图 信号" in line:
        brick_count = int(line.split("(")[1].split("个")[0]) if "(" in line else 0
    elif "单针 信号" in line:
        needle_count = int(line.split("(")[1].split("个")[0]) if "(" in line else 0
    elif "强势板块" in line and "无数据" not in line:
        parts = line.split(":")[1].strip() if ":" in line else ""
        strong_sectors = parts.split("、") if parts else []

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("大盘评分", f"{macro['score']}/100", macro['level'])
c2.metric("强势板块", str(len(strong_sectors)) if strong_sectors else "暂无")
c3.metric("B1B2信号", str(b1b2_count))
c4.metric("砖型图信号", str(brick_count))
c5.metric("单针信号", str(needle_count))

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🎯 选股结果", "📈 回测追踪", "🏛 大盘板块", "🔬 因子详情", "🤖 AI诊断", "🔮 Vibe"])

with tab1:
    st.subheader("今日选股结果")
    st.caption(f"数据来源: {report_files[0].name if report_files else '暂无报告，请先运行 daily_screener.py'}")

    # Parse stocks from report
    stocks = {"B1B2": [], "BRICK": [], "NEEDLE": []}
    current_section = None
    for line in latest_report.split("\n"):
        if line.startswith("## "):
            if "B1B2" in line: current_section = "B1B2"
            elif "砖型" in line: current_section = "BRICK"
            elif "单针" in line: current_section = "NEEDLE"
            else: current_section = None
        elif line.startswith("- ") and current_section:
            parts = line[2:].split("(")
            sym = parts[0].strip()
            sig = parts[1].rstrip(")") if len(parts) > 1 else ""
            stocks[current_section].append({"symbol": sym, "signal_type": sig})

    if any(stocks.values()):
        rows = []
        for strategy, syms in stocks.items():
            for s in syms[:10]:
                rows.append({"股票": s["symbol"], "策略": strategy, "信号类型": s["signal_type"]})
        df = pd.DataFrame(rows)
        st.dataframe(df, width='stretch', hide_index=True) if not df.empty else st.info("今日无信号")
    else:
        st.info("暂无选股信号，请在 15:30 后运行 daily_screener.py")

    # K-line chart for a selected stock
    st.subheader("K线分析")
    sel_stock = st.text_input("输入股票代码查看K线", "000001")
    kline_path = DATA_DIR / f"{sel_stock}.csv"
    if kline_path.exists():
        kdf = pd.read_csv(kline_path, parse_dates=["date"]).tail(60)
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=kdf["date"], open=kdf["open"], high=kdf["high"],
            low=kdf["low"], close=kdf["close"]))
        fig.update_layout(height=400, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, width='stretch')
    else:
        st.warning(f"未找到股票 {sel_stock} 的数据")

with tab2:
    st.subheader("回测追踪 - 买后N日表现")
    st.radio("策略", ["B1B2","砖型图","单针"], horizontal=True, key="bt_metric")
    bt_path = Path("backtest_results/short_term.db")
    if bt_path.exists():
        import sqlite3
        conn = sqlite3.connect(str(bt_path))
        try:
            stats_df = pd.read_sql_query(
                "SELECT strategy, count(*) as cnt, round(avg(total_return),2) as avg_ret, "
                "round(avg(hold_days),1) as avg_days FROM exits e "
                "JOIN signals s ON e.signal_id = s.id GROUP BY strategy", conn)
            if not stats_df.empty:
                for _, row in stats_df.iterrows():
                    st.metric(row["strategy"], f"{row['cnt']}次", f"平均收益{row['avg_ret']}%")
            conn.close()
        except Exception:
            conn.close()
            st.info("回测数据表结构待初始化")
    else:
        st.info("暂无回测数据，夜间自动运行后将生成本地SQLite数据库")

with tab3:
    st.subheader("大盘 + 板块")
    fig3 = go.Figure(go.Indicator(mode="gauge+delta", value=macro["score"],
        title={"text":"大盘综合评分"}, delta={"reference": 50},
        gauge={"axis":{"range":[0,100]},"bar":{"color":"orange"},
               "steps":[{"range":[0,20],"color":"red"},{"range":[20,40],"color":"orange"},
                        {"range":[40,60],"color":"yellow"},{"range":[60,80],"color":"lightgreen"},
                        {"range":[80,100],"color":"green"}]}))
    st.plotly_chart(fig3, width='stretch')
    st.caption(f"评分: {macro['score']}/100 | 档位: {macro['level']}")
    subs = macro.get("sub_scores", {})
    if subs:
        st.json(subs)

with tab4:
    st.subheader("因子详情")
    st.info("因子IC和权重数据由 nightly auto-research 自动计算更新，存储在 config/factor_weights.json")
    weights_path = Path("config/factor_weights.json")
    if weights_path.exists():
        wdata = json.loads(weights_path.read_text())
        st.json(wdata)

with tab5:
    st.subheader("AI个股诊断")
    diag_stock = st.text_input("输入股票代码", "000001", key="diag_code")
    if st.button("诊断"):
        kdf = pd.read_csv(DATA_DIR / f"{diag_stock}.csv", parse_dates=["date"]) if (DATA_DIR / f"{diag_stock}.csv").exists() else None
        if kdf is not None and len(kdf) >= 60:
            from alphapulse.diagnosis.stock_scorer import compute_diagnosis
            from alphapulse.factors.kdj_j_low import compute as kdj_compute
            from alphapulse.factors.weekly_ma_bull import compute as ma_bull_compute
            snap = {"KDJ_J_LOW": int(kdj_compute(kdf).iloc[-1]) if kdj_compute(kdf).notna().iloc[-1] else 0}
            snap["WEEKLY_MA_BULL"] = int(ma_bull_compute(kdf).iloc[-1]) if ma_bull_compute(kdf).notna().iloc[-1] else 0
            result = compute_diagnosis(snap)
            categories = ["技术面","量能","形态","风控","板块共振"]
            values = [result["sub_scores"].get(d,0) for d in ["technical","volume","pattern","risk","sector"]]
            fig5 = go.Figure()
            fig5.add_trace(go.Scatterpolar(r=values+[values[0]], theta=categories+[categories[0]], fill="toself"))
            fig5.update_layout(polar=dict(radialaxis=dict(range=[0,30])))
            st.plotly_chart(fig5)
            st.success(f"评级: {result['grade']} ({result['total_score']}/100)")
        else:
            st.warning("数据不足60天")

with tab6:
    st.subheader("Vibe-Trading 因子探索")
    st.text_area("描述交易想法", "找出低位缩量企稳后放量突破的股票")
    if st.button("生成因子"):
        st.info("需启动 Vibe-Trading Docker: bash scripts/vibe_trading_setup.sh")

st.divider()
c1,c2,c3 = st.columns(3)
c1.button("📤 推送到飞书" if FEISHU_WEBHOOK_URL else "📤 飞书未配置")
c2.caption(f"数据: {len(list(DATA_DIR.glob('*.csv')))}只A股")
c3.caption("AlphaPulse-A v3.0")
