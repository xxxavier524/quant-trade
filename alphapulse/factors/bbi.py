"""BBI 指标套件 — 少妇战法止盈/离场的基础设施。

来源：zettaranc 少妇战法 SOP 第5/6步（docs/research_journal/12_* P0 #1-#3）：
- BBI = (MA3+MA6+MA12+MA24)/4
- 卤煮止盈：站上 BBI 后连续两根中/大阳线 → 减半
- 两日破位离场：收盘价连续两天 < BBI → 清仓
"""

import pandas as pd


def compute_bbi(close: pd.Series) -> pd.Series:
    """BBI 多空指标 = (MA3+MA6+MA12+MA24)/4。"""
    return (close.rolling(3).mean() + close.rolling(6).mean()
            + close.rolling(12).mean() + close.rolling(24).mean()) / 4


def compute(data: pd.DataFrame) -> pd.Series:
    """BBI 数值序列（indicator，供其他因子/评分引用）。"""
    return compute_bbi(data["close"].astype(float))


def compute_luzhu(
    data: pd.DataFrame,
    mid_yang_pct: float = 4.0,
    n_yang: int = 2,
) -> pd.Series:
    """卤煮止盈信号：站上 BBI 后连续 n_yang 根中/大阳线（涨幅≥mid_yang_pct%）→ True=减半。

    「站上 BBI」= 这几根阳线的收盘价都在 BBI 之上。
    """
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    bbi = compute_bbi(close)
    pct = close.pct_change() * 100

    is_big_yang = (close > open_) & (pct >= mid_yang_pct) & (close > bbi)
    sig = is_big_yang.copy()
    for i in range(1, n_yang):
        sig &= is_big_yang.shift(i, fill_value=False)
    return sig.fillna(False).astype(bool)


def compute_bbi_break(data: pd.DataFrame, n_days: int = 2) -> pd.Series:
    """BBI 两日破位离场：收盘价连续 n_days 天 < BBI → True=清仓。"""
    close = data["close"].astype(float)
    below = close < compute_bbi(close)
    sig = below.copy()
    for i in range(1, n_days):
        sig &= below.shift(i, fill_value=False)
    return sig.fillna(False).astype(bool)
