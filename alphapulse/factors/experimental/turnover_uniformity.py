"""
换手率分布均匀度因子 (Turnover Distribution Uniformity / UTD).

基于东吴证券《换手率分布均匀度UTD因子》(2024.1) 和 中信建投《筹码分布因子》(2025.8)。

核心逻辑:
- 传统换手率因子(Turn20)是负向因子（低换手→高收益），IC -7.2%，ICIR -2.10
- UTD衡量换手率在时间上的分布均匀程度
- 换手越均匀→筹码结构越稳定→未来收益越好（负向因子）
- UTD显著优于传统换手率因子

方法论:
    1. 计算每日换手率 = volume / 流通股本（无流通股本时用成交量代理）
    2. 滚动窗口内计算换手率的变异系数 (CV = std/mean)
    3. CV越低 = 换手越均匀 = 筹码越稳定
    4. 可选：换手率分布偏度（衡量极端换手日占比）
    5. 可选：Piotroski-style稳定性得分

A股实证表现 (UTD):
    - 月度IC均值: -0.042 (RankIC: -0.067)
    - 年化ICIR: -2.67 (RankICIR: -3.99)
    - 多空年化收益: 20.06%
    - 信息比率: 2.71
    - 月度胜率: 77.30%
    - 最大回撤: 5.51%

vs 传统Turn20:
    - Turn20 IC: -0.072, ICIR -2.10, 胜率 71.58%
    - UTD稳定性(ICIR)和胜率显著优于Turn20

Source: 东吴证券金工 (2024.1) / 中信建投《筹码分布因子系统构建》(2025.8)
"""

import numpy as np
import pandas as pd


def compute(
    data: pd.DataFrame,
    window: int = 20,
    method: str = "cv",
    use_skewness: bool = False,
    use_decay: bool = True,
) -> pd.Series:
    """计算换手率分布均匀度因子。

    因子值为负向因子（低值 = 换手均匀 = 看多）。

    Args:
        data: 含 'volume', 可选 'float_shares' 列的DataFrame
        window: 滚动窗口（日）
        method: 'cv' (变异系数) | 'range_ratio' (极差比) | 'composite' (综合)
        use_skewness: 是否加入换手率偏度
        use_decay: 是否使用指数衰减加权（近期权重更高）

    Returns:
        pd.Series: 因子值（低=均匀稳定=看多, 高=不稳定=看空）
    """
    volume = data["volume"]

    # 计算换手率代理（如果没有流通股本，用成交量变化率代理）
    if "float_shares" in data.columns:
        turnover = volume / data["float_shares"]
    elif "turnover_rate" in data.columns:
        turnover = data["turnover_rate"]
    else:
        # 用成交量相对于自身均值的比率作为换手率代理
        vol_ma = volume.rolling(60).mean()
        turnover = volume / vol_ma.replace(0, np.nan)

    # 构建滚动窗口
    if use_decay:
        # 指数衰减权重（半衰期 = window/2）
        half_life = window / 2
        decay = np.exp(-np.log(2) / half_life * np.arange(window)[::-1])
        decay = decay / decay.sum()

        def weighted_cv(x):
            if len(x) < window:
                return np.nan
            w = decay[-len(x):] if len(x) <= window else decay
            w = w / w.sum()
            w_mean = np.average(x, weights=w)
            w_var = np.average((x - w_mean) ** 2, weights=w)
            return np.sqrt(w_var) / (w_mean + 1e-10)

        cv_series = turnover.rolling(window).apply(weighted_cv, raw=True)
    else:
        rolling_std = turnover.rolling(window).std()
        rolling_mean = turnover.rolling(window).mean()
        cv_series = rolling_std / rolling_mean.replace(0, np.nan)

    if method == "cv":
        factor = cv_series
    elif method == "range_ratio":
        # 极差比: (max - min) / median，衡量极端值占比
        rolling_max = turnover.rolling(window).max()
        rolling_min = turnover.rolling(window).min()
        rolling_median = turnover.rolling(window).median()
        factor = (rolling_max - rolling_min) / rolling_median.replace(0, np.nan)
    elif method == "composite":
        # 综合均匀度: CV + 换手率趋势
        rolling_max = turnover.rolling(window).max()
        rolling_min = turnover.rolling(window).min()
        rolling_median = turnover.rolling(window).median()
        range_ratio = (rolling_max - rolling_min) / rolling_median.replace(0, np.nan)

        # 换手率趋势: 近期/远期换手比
        half_w = max(window // 2, 1)
        recent_avg = turnover.rolling(half_w).mean()
        full_avg = turnover.rolling(window).mean()
        trend_ratio = recent_avg / full_avg.replace(0, np.nan)

        factor = (cv_series + range_ratio + trend_ratio) / 3.0
    else:
        raise ValueError(f"Unknown method: {method}")

    if use_skewness:
        # 换手率偏度：正偏度 → 少数极端高换手日 → 筹码不稳定
        def rolling_skew(x):
            if len(x) < window:
                return np.nan
            x = np.array(x, dtype=float)
            x_demean = x - x.mean()
            m3 = np.mean(x_demean**3)
            m2 = np.mean(x_demean**2)
            return m3 / (m2**1.5 + 1e-10)

        skew = turnover.rolling(window).apply(rolling_skew, raw=True)
        factor = (factor.fillna(0) + skew.fillna(0)) / 2.0

    # 截断面标准化 (Z-Score)
    factor_std = (factor - factor.rolling(60).mean()) / factor.rolling(60).std().replace(0, np.nan)

    return factor_std.fillna(0).astype(float)
