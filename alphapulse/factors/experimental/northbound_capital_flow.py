"""北向资金因子 (North-bound Capital Flow Factor).

基于广发证券《北向选股2.0：因子篇》(2024.5) 和 国金证券 (2024) 研究。

核心逻辑:
- 北向资金（陆股通）是A股重要的"聪明钱"指标
- 持续净流入的股票未来收益显著为正
- 披露机制变化后（2024.8起日度→季度），通过日内量价数据代理

方法论:
    1. 计算每日资金流向代理: 成交量 * 价格变化方向 * 涨跌幅
    2. 短期(5日)和长期(20日)净流入比率
    3. 计算流入比率的滚动Z-Score（相对截面标准化）
    4. 短期与长期流入比率的差值（加速度）

A股实证表现:
    - 全市场季频IC均值: 5.1%
    - 年化ICIR: 2.7
    - IC胜率: 89.3%
    - 多空年化收益: 12.8%
    - 行业层面IC: 19.72% (2024)

Source: 广发证券《北向选股2.0》/ 国金证券《量化行业配置》系列
"""

import numpy as np
import pandas as pd


def _proxy_capital_flow(data: pd.DataFrame) -> pd.Series:
    """用日内量价估计资金流向方向。

    公式: flow = volume * log_return * sign(log_return)
    正值表示净流入倾向，负值表示净流出倾向。
    """
    close = data["close"]
    prev_close = close.shift(1)
    log_ret = np.log(close / prev_close)
    volume = data["volume"]
    # 方向性资金流: 放量上涨=流入，放量下跌=流出
    flow = volume * log_ret * np.abs(log_ret)
    return flow


def _rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """滚动Z-Score标准化。"""
    rolling_mean = series.rolling(window).mean()
    rolling_std = series.rolling(window).std()
    zscore = (series - rolling_mean) / rolling_std.replace(0, np.nan)
    return zscore


def compute(
    data: pd.DataFrame,
    short_window: int = 5,
    long_window: int = 20,
    zscore_window: int = 60,
    use_acceleration: bool = True,
) -> pd.Series:
    """计算北向资金代理因子值。

    Args:
        data: 含 'close', 'volume' 列的DataFrame
        short_window: 短期流入计算窗口（日）
        long_window: 长期流入计算窗口（日）
        zscore_window: Z-Score标准化窗口
        use_acceleration: 是否使用加速度（短期-长期差值）

    Returns:
        pd.Series: 因子值，正值表示资金持续流入，值越大越看多
    """
    # Step 1: 每日资金流向代理
    flow_proxy = _proxy_capital_flow(data)

    # Step 2: 短期和长期累计净流入
    short_flow = flow_proxy.rolling(short_window).sum()
    long_flow = flow_proxy.rolling(long_window).sum()

    # 归一化: 净流入 / 总成交量
    total_vol_short = data["volume"].rolling(short_window).sum()
    total_vol_long = data["volume"].rolling(long_window).sum()

    short_ratio = short_flow / total_vol_short.replace(0, np.nan)
    long_ratio = long_flow / total_vol_long.replace(0, np.nan)

    if use_acceleration:
        # 资金流入加速度：短期-长期比率差
        raw_factor = short_ratio - long_ratio
    else:
        raw_factor = short_ratio

    # Step 3: 滚动Z-Score标准化
    factor = _rolling_zscore(raw_factor, zscore_window)

    return factor.fillna(0).astype(float)
