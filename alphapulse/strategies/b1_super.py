"""SuperB1 增强策略 — 基于微信公众号文章的 BBI+KDJ 结构参数。

来源：SebastienZh/StockTradebyZ (SuperB1战法)
核心逻辑：
1. 回看N日内有 BBI+KDJ 满足条件的信号日
2. 信号日到当前收盘价波动 ≤ close_vol_pct
3. 当日下跌 ≥ price_drop_pct（回调买入）
4. J值 ≤ j_threshold 或 ≤ j_q_threshold 分位
5. BBI 多头排列 + 知行约束（收盘>多空线 AND 短期>长期）

BBI = (MA(3) + MA(6) + MA(12) + MA(24)) / 4
"""

import pandas as pd
import numpy as np


def compute_bbi(close: pd.Series) -> pd.Series:
    """BBI = (MA3 + MA6 + MA12 + MA24) / 4"""
    ma3 = close.rolling(3).mean()
    ma6 = close.rolling(6).mean()
    ma12 = close.rolling(12).mean()
    ma24 = close.rolling(24).mean()
    return (ma3 + ma6 + ma12 + ma24) / 4


def compute_bbi_mas(close: pd.Series) -> tuple:
    return close.rolling(3).mean(), close.rolling(6).mean(), close.rolling(12).mean(), close.rolling(24).mean()


def compute_kdj_j(high, low, close, n=9):
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = ((close - low_n) / (high_n - low_n).replace(0, np.nan)) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    return 3 * k - 2 * d


def compute_detail(data: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """计算 SuperB1 所有子条件详细值。"""
    if params is None:
        params = {}
    close = data["close"]
    high = data["high"]
    low = data["low"]
    open_ = data["open"]
    volume = data["volume"]

    j = compute_kdj_j(high, low, close)
    bbi = compute_bbi(close)
    j_q = j.rolling(params.get("lookback_n", 10)).rank(pct=True)

    # BBI 多头排列：MA3 > MA6 > MA12 > MA24（简化）
    ma3, ma6, ma12, ma24 = compute_bbi_mas(close)
    bbi_bull = (ma3 > ma6) & (ma6 > ma12) & (ma12 > ma24)

    # 信号日矩阵：BBI 多头 AND J<15（BBIKDJ子策略条件）
    bbi_kdj_signal = bbi_bull & (j < params.get("sub_j_threshold", 15))

    return pd.DataFrame({
        "j": j.round(2),
        "j_q": j_q.round(3),
        "bbi": bbi.round(2),
        "bbi_bull": bbi_bull,
        "bki_signal": bbi_kdj_signal,
        "close": close,
        "pct_change": close.pct_change().round(4),
    }, index=data.index)


def compute(
    data: pd.DataFrame,
    lookback_n: int = 10,
    close_vol_pct: float = 0.02,
    price_drop_pct: float = 0.02,
    j_threshold: float = 10.0,
    j_q_threshold: float = 0.10,
    sub_j_threshold: float = 15.0,
    bbi_window: int = 20,
    max_window: int = 120,
    price_range_pct: float = 1.0,
) -> pd.Series:
    """SuperB1 选股条件。

    Returns:
        pd.Series[bool]
    """
    close = data["close"]
    high = data["high"]
    low = data["low"]

    n = len(data)
    result = pd.Series(False, index=data.index)
    if n < lookback_n + bbi_window:
        return result

    j = compute_kdj_j(high, low, close)
    j_q = j.rolling(lookback_n).rank(pct=True)
    ma3, ma6, ma12, ma24 = compute_bbi_mas(close)

    # 1. BBI 多头排列
    bbi_bull = (ma3 > ma6) & (ma6 > ma12) & (ma12 > ma24)

    # 2. 回看期内 BBI+KDJ 信号日
    bbi_kdj_ok = bbi_bull & (j < sub_j_threshold)

    # 3. 回看期波动约束
    vol_ok = (close.rolling(lookback_n).max() / close.rolling(lookback_n).min() - 1) <= close_vol_pct

    # 4. 当日回调
    drop_ok = close.pct_change() <= -price_drop_pct

    # 5. J值约束
    j_ok = (j < j_threshold) | (j_q <= j_q_threshold)

    # 6. 综合
    # 回看期内有 BBIKDJ 信号日
    has_signal = bbi_kdj_ok.rolling(lookback_n).sum() >= 1

    result = has_signal & vol_ok & drop_ok & j_ok
    return result.fillna(False).astype(bool)


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    **params,
) -> pd.DataFrame:
    """SuperB1 信号生成器。"""
    sig = compute(data, **params)
    results = []
    for dt in data.index[sig]:
        j_val = float(compute_kdj_j(data["high"], data["low"], data["close"]).loc[dt])
        results.append({
            "symbol": symbol, "date": dt, "signal": 1,
            "strategy": "SUPER_B1",
            "factor_snapshot": {
                "j": round(j_val, 2),
                "close": float(data.loc[dt, "close"]),
                "pct_change": round(float(data["close"].pct_change().loc[dt]) * 100, 2),
            },
        })
    if not results:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])
    return pd.DataFrame(results).set_index("date").sort_index()
