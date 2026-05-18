"""
分析师盈利修正因子 (Analyst Earnings Revision Factor).

基于华泰证券《分析师预期类因子初探》(2024.12) 和 国泰君安《预期利润安全垫》。

核心逻辑:
- 分析师一致预期数据是A股重要的基本面alpha来源
- 盈利修正因子捕捉分析师上调盈利预期的股票
- 剔除动量和市值影响后，修正因子仍有显著IC
- 与AI量价因子相关性仅0.03（增量信息）

方法论:
    1. 分析师异常覆盖：剔除市值/动量/换手率后的残差覆盖度
    2. 改进评级：筛选具有异象捕捉能力的分析师
    3. 盈利修正：高创新性 + 剔除动量的盈利修正
    4. 在没有分析师数据时，用价格动量 + 成交量变化作为盈利修正代理
        (盈利上调 → 机构买入 → 正价格动量 + 成交量放大)

A股实证表现 (华泰证券2024.12):
    - 分析师异常覆盖: RankIC 2.34%
    - 改进评级: RankIC 2.26%
    - 盈利修正: RankIC 3.99%
    - 综合因子: RankIC 4.27%, TOP组合年化超额 10.55%
    - 沪深300增强年化超额: 10.64%
    - 中证500增强年化超额: 15.48%
    - 中证1000增强年化超额: 24.73%

Source: 华泰证券金工 林晓明团队 (2024.12) / 国泰君安金工
"""

import numpy as np
import pandas as pd


def compute(
    data: pd.DataFrame,
    short_window: int = 5,
    long_window: int = 20,
    volume_window: int = 10,
    momentum_window: int = 60,
) -> pd.Series:
    """计算分析师盈利修正代理因子。

    使用量价数据代理分析师盈利修正信号:
    - 正的价格动量 + 成交量放大 = 潜在盈利上调
    - 异常成交量（剔除市场量能后的残差）+ 正收益
    - 盈利修正加速度 = 短期修正信号变化

    Args:
        data: 含 'close', 'volume' 列的DataFrame
        short_window: 短期动量窗口
        long_window: 长期动量窗口
        volume_window: 成交量变化窗口
        momentum_window: 动量中性化窗口

    Returns:
        pd.Series: 因子值，正值表示盈利上调预期，值越大越看多
    """
    close = data["close"]
    volume = data["volume"]

    # --- 组件1: 短期价格动量（价格趋势代理盈利修正方向）---
    short_momentum = close.pct_change(short_window)
    long_momentum = close.pct_change(long_window)
    # 短期-长期动量差（加速度）: 捕捉"近期开始上调"的信号
    momentum_acceleration = short_momentum - long_momentum

    # --- 组件2: 成交量异常（机构基于盈利修正调仓的痕迹）---
    vol_ma = volume.rolling(momentum_window).mean()
    vol_std = volume.rolling(momentum_window).std()
    abnormal_volume = (volume - vol_ma) / vol_std.replace(0, np.nan)
    # 只取正异常量（放量买入）
    abnormal_volume = abnormal_volume.clip(lower=0)

    # --- 组件3: 量价协同信号 ---
    # 放量上涨 = 强盈利修正信号
    daily_ret = close.pct_change()
    vol_price_signal = daily_ret * abnormal_volume
    vol_price_signal = vol_price_signal.rolling(volume_window).mean()

    # --- 组件4: 盈利修正稳定性 ---
    # 连续正动量天数 / 总天数，稳定盈利修正
    pos_days = (daily_ret > 0).astype(float)
    stability = pos_days.rolling(long_window).sum() / long_window

    # --- 合成 ---
    # 对每个组件做截面Z-Score（单标的用时间序列标准化）
    zscore = lambda s: (s - s.rolling(momentum_window).mean()) / s.rolling(momentum_window).std().replace(0, np.nan)

    z_momentum = zscore(momentum_acceleration).fillna(0)
    z_vol_signal = zscore(vol_price_signal).fillna(0)
    z_stability = zscore(stability).fillna(0)

    # 加权合成（动量加速度权重最高，因为最接近盈利修正信号）
    factor = 0.40 * z_momentum + 0.35 * z_vol_signal + 0.25 * z_stability

    # 最终标准化
    factor_final = zscore(factor)

    return factor_final.fillna(0).astype(float)
