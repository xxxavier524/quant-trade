"""CSRankNorm 标签变换（路线图#12，qlib 去 beta 污染）。

问题：二分类标签 label=(fwd>0) 受市场 beta 污染——大盘下跌日多数股 fwd<0，标签与
个股 alpha 无关。CSRankNorm = 按日截面对 fwd 排名归一，只留相对强弱、去 beta。

可选工具，验证去 beta 性质后由用户决定是否用于 LGBM 重训（不改生产标签）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def csrank_norm(df: pd.DataFrame, value_col: str = "fwd5",
                date_col: str = "date", method: str = "binary") -> pd.Series:
    """按日截面对 value_col 排名归一。

    Args:
        method:
            'binary' → 截面 rank > 中位 = 1（去 beta 二分类标签，正样本率恒≈50%）
            'zscore' → 截面 rank 百分位居中并缩放（回归/排序模型标签，均值0）
            'pct'    → 截面百分位 [0,1]

    Returns:
        pd.Series，index 对齐 df
    """
    g = df.groupby(date_col)[value_col]
    pct = g.rank(pct=True)                       # 截面百分位 (0,1]
    if method == "binary":
        return (pct > 0.5).astype(int)
    if method == "pct":
        return pct
    if method == "zscore":
        # 百分位 → 近似标准正态（居中，去 beta 的连续标签）
        return (pct - 0.5) * np.sqrt(12.0)       # 均匀[0,1]→均值0方差1的线性缩放
    raise ValueError(f"未知 method: {method}")
