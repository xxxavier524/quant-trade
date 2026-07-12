"""MACD 增强包 — 零轴多空 / 金叉空·死叉多 / 顶底背离 / 一票否决。

来源：zettaranc indicators 3.12「MACD 指标之王」（docs/research_journal/12_* P0 #5）：
- 参数锁死 (12,26,9)，绝不改参数
- 零轴多空：DIF>0 多头区间可进攻；DIF<0 空头区间什么都不做
- 金叉空：欲金叉未成、DIF 拐头向下 = 最恶毒的诱多（看到金叉多等一天）
- 死叉多：欲死叉未成、跳空拉起 = 空中加油
- 顶背离只看日线（价新高 DIF 不新高）；底背离只看周线（日线 90% 是骗线）
- 一票否决：DIF<0 且近期无底背离 → 不能买
"""

import pandas as pd


def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (DIF, DEA, HIST)。参数默认 (12,26,9)，按体系要求不建议修改。"""
    dif = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea, (dif - dea) * 2


def compute_zero_axis(data: pd.DataFrame) -> pd.Series:
    """零轴多空：DIF > 0 = 多头区间（True 才允许进攻战法）。"""
    dif, _, _ = compute_macd(data["close"].astype(float))
    return (dif > 0).fillna(False).astype(bool)


def compute_fake_gold_cross(
    data: pd.DataFrame,
    approach_days: int = 3,
    gap_eps: float = 0.15,
) -> pd.Series:
    """金叉空：DIF 在 DEA 下方向上逼近（连续 approach_days 天差距收窄且缩到
    |DIF-DEA| ≤ gap_eps*std）后，今日 DIF 拐头向下且未上穿 → True（诱多，回避/离场）。"""
    close = data["close"].astype(float)
    dif, dea, _ = compute_macd(close)
    gap = dif - dea
    narrowing = pd.Series(True, index=gap.index)
    for i in range(approach_days):
        narrowing &= gap.shift(i) > gap.shift(i + 1)
    near = gap.shift(1).abs() <= gap.rolling(60).std() * gap_eps + 1e-12
    below = gap.shift(1) < 0
    turn_down = (dif < dif.shift(1)) & (gap < 0)
    return (below & narrowing.shift(1, fill_value=False) & near & turn_down) \
        .fillna(False).astype(bool)


def compute_fake_dead_cross(
    data: pd.DataFrame,
    approach_days: int = 3,
    gap_eps: float = 0.15,
) -> pd.Series:
    """死叉多：DIF 在 DEA 上方向下逼近后突然拐头向上、死叉未成 → True（空中加油）。"""
    close = data["close"].astype(float)
    dif, dea, _ = compute_macd(close)
    gap = dif - dea
    narrowing = pd.Series(True, index=gap.index)
    for i in range(approach_days):
        narrowing &= gap.shift(i) < gap.shift(i + 1)
    near = gap.shift(1).abs() <= gap.rolling(60).std() * gap_eps + 1e-12
    above = gap.shift(1) > 0
    turn_up = (dif > dif.shift(1)) & (gap > 0)
    return (above & narrowing.shift(1, fill_value=False) & near & turn_up) \
        .fillna(False).astype(bool)


def compute_top_divergence(data: pd.DataFrame, window: int = 60) -> pd.Series:
    """顶背离（日线）：收盘创 window 日新高 且 DIF 未创同窗口新高 且 DIF>0。"""
    close = data["close"].astype(float)
    dif, _, _ = compute_macd(close)
    price_high = close >= close.rolling(window).max()
    dif_not_high = dif < dif.rolling(window).max() * 0.98
    return (price_high & dif_not_high & (dif > 0)).fillna(False).astype(bool)


def compute_bottom_divergence(
    data: pd.DataFrame,
    window: int = 60,
    weekly: bool = True,
) -> pd.Series:
    """底背离：价创新低且 DIF 未创新低且 DIF<0。体系要求只看周线（日线90%是骗线），
    weekly=True 时按周重采样计算后映射回日线。"""
    close = data["close"].astype(float)
    if weekly and isinstance(data.index, pd.DatetimeIndex):
        wclose = close.resample("W-FRI").last().dropna()
        wdif, _, _ = compute_macd(wclose)
        wwin = max(window // 5, 12)
        wlow = wclose <= wclose.rolling(wwin).min()
        wdif_not_low = wdif > wdif.rolling(wwin).min() * 0.98
        wsig = (wlow & wdif_not_low & (wdif < 0)).astype(bool)
        return wsig.reindex(close.index, method="ffill").fillna(False).astype(bool)
    dif, _, _ = compute_macd(close)
    price_low = close <= close.rolling(window).min()
    dif_not_low = dif > dif.rolling(window).min() * 0.98
    return (price_low & dif_not_low & (dif < 0)).fillna(False).astype(bool)


def compute_veto(data: pd.DataFrame, div_lookback: int = 10) -> pd.Series:
    """一票否决：DIF<0 且近 div_lookback 日无（周线）底背离 → True=禁止买入。"""
    close = data["close"].astype(float)
    dif, _, _ = compute_macd(close)
    bottom_div = compute_bottom_divergence(data)
    recent_div = bottom_div.rolling(div_lookback, min_periods=1).max().astype(bool)
    return ((dif < 0) & ~recent_div).fillna(False).astype(bool)


def compute(data: pd.DataFrame, **params) -> pd.Series:
    """registry 默认入口 = 一票否决（type=risk：True=不能买）。"""
    return compute_veto(data, **params)
