"""扁平化设计系统 — 统一色彩/字阶/卡片组件（GUI v5）。

原则：红涨绿跌只用于数据语义；装饰零阴影零渐变；信息分层靠字阶与留白。
"""

import streamlit as st

UP = "#ef232a"       # 红涨
DOWN = "#14b143"     # 绿跌
YELLOW = "#f0b90b"   # 黄线/中性强调
WHITE = "#e8e8e8"
MUTED = "#8b919e"    # 次要文字
BORDER = "#262a35"   # 分割线
CARD_BG = "#161a23"  # 卡片底


def inject_css():
    st.markdown(f"""
<style>
.block-container {{padding-top: 1rem; padding-bottom: 2rem; max-width: 1400px;}}
h1,h2,h3,h4 {{color:{WHITE}; font-weight:600;}}
hr {{border-color:{BORDER};}}
[data-testid="stMetric"] {{background:{CARD_BG}; border:1px solid {BORDER};
  border-radius:8px; padding:14px 18px;}}
[data-testid="stMetricLabel"] {{color:{MUTED}; font-size:12px;}}
[data-testid="stMetricValue"] {{font-size:32px;}}
[data-testid="stMetricDelta"] svg {{display:none;}}
div[data-testid="stDataFrame"] {{border:1px solid {BORDER}; border-radius:8px;}}
.stTabs [data-baseweb="tab-list"] {{gap:4px; border-bottom:1px solid {BORDER};}}
.stTabs [data-baseweb="tab"] {{font-size:15px; padding:10px 22px; border-radius:6px 6px 0 0;}}
.stTabs [aria-selected="true"] {{background:{CARD_BG};}}
.ap-card {{background:{CARD_BG}; border:1px solid {BORDER}; border-radius:8px;
  padding:16px 18px; margin-bottom:10px;}}
.ap-kpi {{font-size:40px; font-weight:700; line-height:1.1;}}
.ap-kpi-label {{font-size:12px; color:{MUTED}; margin-bottom:2px;}}
.ap-sub {{font-size:13px; color:{MUTED};}}
.ap-tag {{display:inline-block; padding:1px 8px; border-radius:4px;
  font-size:12px; border:1px solid {BORDER}; color:{MUTED}; margin-right:4px;}}
.ap-bar-row {{display:flex; align-items:center; gap:10px; margin:4px 0;}}
.ap-bar-label {{width:90px; font-size:13px; text-align:right; color:{WHITE};}}
.ap-bar-track {{flex:1; background:#0e1117; border-radius:3px; height:14px;}}
.ap-bar-fill {{height:14px; border-radius:3px;}}
.ap-bar-val {{width:48px; font-size:13px;}}
</style>""", unsafe_allow_html=True)


def card(html: str):
    st.markdown(f'<div class="ap-card">{html}</div>', unsafe_allow_html=True)


def kpi(label: str, value: str, color: str = WHITE, sub: str = "") -> str:
    """大数字KPI块的HTML（嵌入card）。"""
    sub_html = f'<div class="ap-sub">{sub}</div>' if sub else ""
    return (f'<div class="ap-kpi-label">{label}</div>'
            f'<div class="ap-kpi" style="color:{color}">{value}</div>{sub_html}')


def hbar(label: str, value: float, max_value: float = 100,
         color: str = UP, suffix: str = "") -> str:
    """横向条形行HTML。"""
    pct = max(0, min(100, value / max_value * 100))
    return (f'<div class="ap-bar-row"><div class="ap-bar-label">{label}</div>'
            f'<div class="ap-bar-track"><div class="ap-bar-fill" '
            f'style="width:{pct:.0f}%;background:{color}"></div></div>'
            f'<div class="ap-bar-val">{value:.0f}{suffix}</div></div>')


def pct_color(v: float) -> str:
    return UP if v > 0 else (DOWN if v < 0 else MUTED)
