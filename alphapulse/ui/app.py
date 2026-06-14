"""AlphaPulse-A v5 — 三层任务流交易台（扁平化设计）。

信息架构（用户确认 2026-06-11）：
1. 今日看板 — 30秒看懂今天：大盘基调 / 板块强弱 / Top信号
2. 选股工作台 — 当日任务：左表右图，点击即看K线决策
3. 研究优化 — 让系统更好：信号复盘闭环 / 验证 / 网格 / ML / AI

v4 版存档于 git 历史；视图模块在 alphapulse/ui/views/。
启动：streamlit run alphapulse/ui/app.py
"""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

st.set_page_config(page_title="AlphaPulse-A", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")

from alphapulse.ui import style as S  # noqa: E402

S.inject_css()

tab_dash, tab_work, tab_judge, tab_research = st.tabs(
    ["今日看板", "选股工作台", "投资判断", "研究优化"])

with tab_dash:
    from alphapulse.ui.views import dashboard
    dashboard.render()

with tab_work:
    from alphapulse.ui.views import workbench
    workbench.render()

with tab_judge:
    from alphapulse.ui.views import judgment
    judgment.render()

with tab_research:
    from alphapulse.ui.views import research
    research.render()
