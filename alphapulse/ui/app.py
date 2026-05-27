"""AlphaPulse-A v3.0 Streamlit GUI - 6-Tab interactive dashboard."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

st.set_page_config(page_title="AlphaPulse-A", page_icon="📊", layout="wide")

# TODO: Connect to real pipeline data. All tabs currently use placeholder/sample data.
# Tab 1 should load from daily_screener output (reports/daily_report_*.md or SQLite)
# Tab 2 should load from alphapulse/backtest/bt_storage.py query_strategy_stats()
# Tab 3 should load from alphapulse/market/macro_position.compute_macro_score() + sector_strength.rank_sectors()
# Tab 4 should load from alphapulse/ranking/factor_weighter.FactorWeighter
# Tab 5 should call alphapulse/diagnosis classes with real factor values
# Tab 6 should call Vibe-Trading REST API at localhost:8899

# Sidebar
st.sidebar.title("📊 AlphaPulse-A v3.0")
strategy_filter = st.sidebar.selectbox("策略", ["全部", "B1B2", "砖型图超短", "单针"])
grade_filter = st.sidebar.multiselect("评级", ["S","A","B","C","D"], default=["S","A","B"])

# Top metrics
c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("大盘评分", "65/100", "震荡偏多")
c2.metric("强势板块", "3", "电子/医药/计算机")
c3.metric("B1B2信号", "12")
c4.metric("砖型图信号", "8")
c5.metric("单针信号", "5")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🎯 选股结果", "📈 回测追踪", "🏛 大盘板块", "🔬 因子详情", "🤖 AI诊断", "🔮 Vibe"])

with tab1:
    st.subheader("今日选股结果")
    c1,c2,c3 = st.columns(3)
    c1.selectbox("策略", ["全部","B1B2","砖型图超短","单针"], key="s1")
    c2.selectbox("板块", ["全部","银行","电子","医药","计算机"], key="s2")
    c3.selectbox("评级", ["全部","S","A","B","C","D"], key="s3")
    sample = pd.DataFrame({
        "股票": ["000001 平安银行", "000002 万科A", "000333 美的集团"],
        "策略": ["B1B2", "砖型图", "单针"],
        "得分": [82, 75, 68], "评级": ["A","B","B"],
        "诊断摘要": ["J低位+放量突破+周线多头", "N起跳+量能放大+板块共振", "长下影+缩量企稳+洗盘确认"],
        "板块": ["银行","房地产","家电"]})
    st.dataframe(sample, use_container_width=True, hide_index=True)
    dates = pd.date_range("2026-04-01", periods=40, freq="B")
    fig = go.Figure()
    close_prices = [10 + i*0.1 + (i-20)**2*0.01 for i in range(40)]
    fig.add_trace(go.Candlestick(x=dates, open=[c-0.2 for c in close_prices], high=[c+0.3 for c in close_prices],
                                 low=[c-0.5 for c in close_prices], close=close_prices))
    fig.update_layout(height=400, xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("回测追踪 - 买后N日表现")
    st.radio("策略", ["B1B2","砖型图","单针"], horizontal=True, key="bt_metric")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("胜率", "42.3%", "+2.1%")
    c2.metric("平均收益", "+3.8%", "-0.5%")
    c3.metric("平均持仓天数", "5.2天")
    c4.metric("盈亏比", "2.1")
    fig2 = go.Figure()
    fig2.add_trace(go.Histogram(x=np.random.randn(200)*3+1, nbinsx=30))
    fig2.add_vline(x=0, line_dash="dash", line_color="red")
    st.plotly_chart(fig2, use_container_width=True)

with tab3:
    st.subheader("大盘 + 板块")
    fig3 = go.Figure(go.Indicator(mode="gauge+delta", value=65, title={"text":"大盘综合评分"},
        delta={"reference": 50},
        gauge={"axis":{"range":[0,100]},"bar":{"color":"orange"},
               "steps":[{"range":[0,20],"color":"red"},{"range":[20,40],"color":"orange"},
                        {"range":[40,60],"color":"yellow"},{"range":[60,80],"color":"lightgreen"},
                        {"range":[80,100],"color":"green"}]}))
    st.plotly_chart(fig3, use_container_width=True)
    sector_df = pd.DataFrame({"板块":["电子","医药","计算机","银行","房地产"], "强度评分":[85,78,72,60,45],
                              "超额收益":[5.2,3.1,2.8,-1.0,-3.5], "趋势":["↑↑","↑","↑","→","↓"]})
    st.dataframe(sector_df, use_container_width=True, hide_index=True)

with tab4:
    st.subheader("因子详情")
    st.selectbox("选择因子", ["N_STRUCT","KDJ_J_LOW","B1_FORMULA","ABNORMAL_VOL","SHRINK_TO_ABNORMAL"], key="factor")
    ic_data = pd.Series(np.random.randn(60).cumsum()*0.01 + 0.02)
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(y=ic_data, mode="lines"))
    fig4.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig4, use_container_width=True)
    st.metric("当前IC", "0.032", "IC_IR: 0.85")
    st.metric("权重", "12.5%", "+1.2%")

with tab5:
    st.subheader("AI个股诊断")
    stock = st.text_input("输入股票代码", "000001")
    if st.button("诊断"):
        categories = ["技术面","量能","形态","风控","板块共振"]
        values = [25, 18, 15, 12, 10]
        fig5 = go.Figure()
        fig5.add_trace(go.Scatterpolar(r=values+[values[0]], theta=categories+[categories[0]], fill="toself"))
        fig5.update_layout(polar=dict(radialaxis=dict(range=[0,30])))
        st.plotly_chart(fig5)
        st.success("评级: A (82/100)")
        st.info("📝 J值低位超卖+缩量企稳+周线多头支撑")

with tab6:
    st.subheader("Vibe-Trading 因子探索")
    st.text_area("描述交易想法", "找出低位缩量企稳后放量突破的股票")
    if st.button("生成因子"):
        st.info("调用 Vibe-Trading MCP... (需启动 Docker)")
        st.code("async def compute(data):\n    vol_ma = data['volume'].rolling(20).mean()\n    is_breakout = (data['volume'] > vol_ma*1.5) & (data['close'] > data['close'].shift(1))\n    return is_breakout.astype(int)", language="python")

st.divider()
c1,c2,c3 = st.columns(3)
c1.button("📤 推送到飞书")
c2.caption("数据源: akshare/baostock/pytdx")
c3.caption("AlphaPulse-A v3.0 | Powered by DeepSeek")
