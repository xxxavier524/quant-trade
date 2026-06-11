"""RPS 相对强度因子（融合自 Sequoia-X，docs/research_journal/05）。

RPS(N) = 个股 N 日涨幅在全市场的百分位排名（0-100）。
欧奈尔体系经典因子：RPS 低的"弱者恒弱"，B1 底部买点叠加 RPS 下限
可剔除阴跌不止的假底（AB 验证见 scripts/ab_test_rps.py）。

注意：RPS 是截面因子，需要全市场数据——与单股 compute(df) 契约不同，
提供面板接口；daily_screener 在全量加载后调用。
"""

import numpy as np
import pandas as pd


def build_close_panel(stock_frames: dict[str, pd.DataFrame],
                      lookback: int = 300) -> pd.DataFrame:
    """全市场收盘价面板（date × symbol）。"""
    cols = {}
    for sym, df in stock_frames.items():
        tail = df.tail(lookback)
        cols[sym] = pd.Series(tail["close"].astype(float).values,
                              index=tail["date"].values)
    return pd.DataFrame(cols).sort_index()


def rps_panel(close_panel: pd.DataFrame, period: int = 120) -> pd.DataFrame:
    """逐日 RPS 面板：每日截面上 N 日涨幅的百分位 ×100。"""
    ret = close_panel / close_panel.shift(period) - 1
    return ret.rank(axis=1, pct=True) * 100


def latest_rps(stock_frames: dict[str, pd.DataFrame],
               periods: tuple[int, ...] = (60, 120)) -> pd.DataFrame:
    """最新一日各周期 RPS → DataFrame[symbol, rps_60, rps_120]。"""
    panel = build_close_panel(stock_frames, lookback=max(periods) + 30)
    out = {"symbol": list(panel.columns)}
    for p in periods:
        rp = rps_panel(panel, p)
        out[f"rps_{p}"] = rp.iloc[-1].reindex(panel.columns).values
    return pd.DataFrame(out)


def score_rps(rps_values: pd.Series) -> pd.Series:
    """RPS → 0-1 子分数：RPS=50→0.5 线性；<20 重罚（假底高危区）。"""
    s = (rps_values / 100).clip(0, 1)
    s = np.where(rps_values < 20, s * 0.5, s)
    return pd.Series(s, index=rps_values.index)
