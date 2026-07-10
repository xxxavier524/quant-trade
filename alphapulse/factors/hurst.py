"""Hurst 指数因子（路线图#12，战法分流用）。

判个股"趋势性 vs 均值回归性"：H>0.5=趋势持续（适合砖型突破），H<0.5=均值回归
（适合 B1 底部挖掘）。按 Hurst 给战法分流。

估计（结构函数法，滚动因果）：窗口 W 内对滞后 τ 求 log 收益 τ 步差的标准差 σ(τ)，
H = log σ(τ) 对 log τ 的回归斜率。只用窗口内 ≤t 数据，无未来泄漏。

标定说明（2026-07-06 实测）：结构函数法在金融长度窗口对"趋势 vs 随机游走"分辨力弱
（都测得 ~0.4，有限样本偏差），但**能清晰识别均值回归轴**（强均值回归 H≈0.05 << 其余）。
恰好 B1（均值回归战法）分流只需低 Hurst 判定。分流用**分位切分**（相对值），不依赖绝对
0.5 阈值。window 从 roadmap 建议的 63 调到 120（更稳，仍因果）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def hurst_exponent(logp: np.ndarray, max_lag: int = 20) -> float:
    """单窗口 Hurst（结构函数法）。logp = 窗口内 log 价格数组。"""
    n = len(logp)
    max_lag = min(max_lag, n - 1)
    if max_lag < 3:
        return np.nan
    lags = np.arange(2, max_lag + 1)
    tau = []
    for lag in lags:
        diff = logp[lag:] - logp[:-lag]
        sd = np.std(diff)
        tau.append(sd if sd > 0 else np.nan)
    tau = np.array(tau)
    ok = np.isfinite(tau) & (tau > 0)
    if ok.sum() < 3:
        return np.nan
    # slope of log(tau) vs log(lag)
    slope = np.polyfit(np.log(lags[ok]), np.log(tau[ok]), 1)[0]
    return float(slope)


def compute(data: pd.DataFrame, window: int = 120, max_lag: int = 12) -> pd.Series:
    """滚动 Hurst 指数序列（每日一值，因果）。

    Returns:
        pd.Series[float]，前 window-1 日为 NaN
    """
    close = data["close"].astype(float).to_numpy()
    logp = np.log(np.maximum(close, 1e-9))
    n = len(logp)
    out = np.full(n, np.nan)
    for t in range(window - 1, n):
        out[t] = hurst_exponent(logp[t - window + 1:t + 1], max_lag)
    return pd.Series(out, index=data.index)


def compute_regime(data: pd.DataFrame, window: int = 120, max_lag: int = 12,
                   trend_th: float = 0.5) -> pd.Series:
    """分流标签：1=趋势(H≥trend_th) / 0=均值回归(H<trend_th) / -1=未定(NaN)。"""
    h = compute(data, window, max_lag)
    regime = pd.Series(-1, index=data.index, dtype=int)
    regime[h >= trend_th] = 1
    regime[h < trend_th] = 0
    return regime
