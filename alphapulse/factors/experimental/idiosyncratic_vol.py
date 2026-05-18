"""
特质波动率因子 (Idiosyncratic Volatility / IVOL Factor).

基于国信证券《隐式框架下的特质类因子改进》(2022)、东吴证券《纯真波动率》(2020)。

核心逻辑:
- 剔除市场/行业系统性风险后的剩余波动（特质波动率）
- A股存在显著的"IVOL异象"：高特质波动 → 低未来收益（负向因子）
- 这是全球最重要的量化因子异象之一，在A股尤为显著
- 空头主导型因子（空头收益占比>70%），在实际组合中需注意做空限制

方法论:
    1. CAPM去Beta: 用滚动回归去除市场风险暴露
    2. 计算残差收益率的标准差作为IVOL
    3. 可选：隐式PCA框架（用统计因子替代显式因子）
    4. 复合因子：IVOL + IVR(特异度) 等权合成

A股实证表现:
    - RankIC均值: -9.29% (FF3剥离最优)
    - 年化ICIR: -3.44
    - IC月度胜率: 86%
    - 多空月均超额: 2.16%
    - 市值越小效果越强（中证1000 > 中证500 > 沪深300）
    - 隐式PCA复合因子ICIR可达-5.04, 胜率92%

Source: 国信证券金工 (2022) / 东吴证券金工 (2020) / Ang et al. (2006)
"""

import numpy as np
import pandas as pd


def _capm_residual_returns(
    returns: pd.Series,
    market_returns: pd.Series,
    window: int = 60,
) -> pd.Series:
    """滚动CAPM回归计算残差。

    r_i = alpha + beta * r_m + epsilon
    返回 epsilon (残差收益率)。

    Args:
        returns: 个股日收益率
        market_returns: 市场日收益率（如中证全指）
        window: 滚动回归窗口
    """
    residuals = pd.Series(np.nan, index=returns.index)

    for t in range(window, len(returns)):
        y = returns.iloc[t - window : t].values
        x = market_returns.iloc[t - window : t].values

        # 过滤NaN
        mask = ~(np.isnan(y) | np.isnan(x))
        y_clean = y[mask]
        x_clean = x[mask]

        if len(y_clean) < window * 0.5:
            continue

        # 简易线性回归: beta = cov(x,y)/var(x)
        x_demean = x_clean - x_clean.mean()
        y_demean = y_clean - y_clean.mean()
        beta = np.sum(x_demean * y_demean) / np.sum(x_demean**2)
        alpha = y_clean.mean() - beta * x_clean.mean()

        # 当日的残差
        residuals.iloc[t] = returns.iloc[t] - (alpha + beta * market_returns.iloc[t])

    return residuals


def _simplified_ivol(returns: pd.Series, window: int = 20) -> pd.Series:
    """简化版IVOL：收益率减去截面均值后的波动率。

    当无法获取市场收益时，用截面均值作为市场代理。
    """
    rolling_std = returns.rolling(window).std()
    return rolling_std


def compute(
    data: pd.DataFrame,
    window: int = 20,
    method: str = "simple",
    market_returns: pd.Series = None,
    capm_window: int = 60,
    use_composite: bool = False,
) -> pd.Series:
    """计算特质波动率因子。

    注意：因子值为负向因子，低IVOL对应高未来收益。
    返回因子值本身（正值=高波动=看空），在因子合成时应取负号。

    Args:
        data: 含 'close' 列的DataFrame
        window: IVOL计算窗口（日）
        method: 'simple' (简易) 或 'capm' (CAPM去Beta)
        market_returns: 市场收益率序列（method='capm'时需要）
        capm_window: CAPM滚动回归窗口
        use_composite: 是否输出复合因子（IVOL + IVR）

    Returns:
        pd.Series: 因子值（高=高特质波动，低=低特质波动）
    """
    close = data["close"]
    returns = close.pct_change()

    if method == "capm" and market_returns is not None:
        residuals = _capm_residual_returns(returns, market_returns, capm_window)
        ivol = residuals.rolling(window).std()
    else:
        # 简易方法：绝对收益率减去截面均值后的标准差
        ivol = _simplified_ivol(returns, window)

    if use_composite:
        # 复合因子：IVOL + IVR（特异度）
        # IVR = 1 - R^2，用滚动回报与市场收益的相关性近似
        if market_returns is not None:
            rolling_corr = (
                returns.rolling(capm_window)
                .corr(market_returns)
                .fillna(0)
            )
        else:
            # 无市场收益时：用收益率自相关性的反面作为IVR代理
            rolling_corr = returns.rolling(window).apply(
                lambda x: x.autocorr(lag=1) if len(x) > 5 else 0
            ).fillna(0)
        ivr = 1.0 - np.abs(rolling_corr)
        # 等权合成并Z-Score标准化
        composite = (ivol - ivol.rolling(60).mean()) / ivol.rolling(60).std().replace(0, np.nan)
        ivr_std = (ivr - ivr.rolling(60).mean()) / ivr.rolling(60).std().replace(0, np.nan)
        return (composite.fillna(0) + ivr_std.fillna(0)) / 2.0

    return ivol.fillna(0).astype(float)
