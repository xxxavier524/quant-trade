"""波段识别因子。

识别价格运动中的三种波段状态：
- 建仓波 (accumulation)：价格涨幅有限，成交量温和，主力悄悄吸筹
- 拉升波 (lift)：价格快速上涨，成交量明显放大，主升浪启动
- 冲刺波 (sprint)：价格加速冲顶，成交量巨量放大，赶顶/出货特征
"""

import numpy as np
import pandas as pd


def compute(
    data: pd.DataFrame,
    accumulation_max_return: float = 0.10,
    vol_mild_ratio: float = 1.0,
    lift_min_return: float = 0.15,
    vol_expand_ratio: float = 1.5,
    sprint_min_return: float = 0.20,
    vol_huge_ratio: float = 3.0,
    ma_period: int = 20,
) -> pd.DataFrame:
    """识别三种波段状态。

    Args:
        data: 含 'close', 'volume' 列的DataFrame
        accumulation_max_return: 建仓波的最大20日涨幅（默认0.10=10%）
        vol_mild_ratio: 量温和阈值，5日均量/20日均量的上限（默认1.0）
        lift_min_return: 拉升波的最小10日涨幅（默认0.15=15%）
        vol_expand_ratio: 量放大阈值，当日量/20日均量的下限（默认1.5）
        sprint_min_return: 冲刺波的最小5日涨幅（默认0.20=20%）
        vol_huge_ratio: 量巨量阈值，当日量/20日均量的下限（默认3.0）
        ma_period: 均量计算周期（默认20）

    Returns:
        pd.DataFrame: 含 'accumulation', 'lift', 'sprint' 三列布尔值
    """
    close = data["close"]
    volume = data["volume"]

    vol_ma5 = volume.rolling(5).mean()
    vol_ma20 = volume.rolling(ma_period).mean()

    # --- 建仓波：20日涨幅 < 上限 AND 量温和（5日均量不超过20日均量）---
    ret_20d = close / close.shift(20) - 1.0
    vol_mild = vol_ma5 <= vol_ma20 * vol_mild_ratio
    accumulation = (ret_20d < accumulation_max_return) & vol_mild

    # --- 拉升波：10日涨幅 > 下限 AND 量放大 > vol_expand_ratio倍均量 ---
    ret_10d = close / close.shift(10) - 1.0
    vol_expand = volume > vol_ma20 * vol_expand_ratio
    lift = (ret_10d > lift_min_return) & vol_expand

    # --- 冲刺波：5日涨幅 > 下限 AND 量巨量 > vol_huge_ratio倍均量 ---
    ret_5d = close / close.shift(5) - 1.0
    vol_huge = volume > vol_ma20 * vol_huge_ratio
    sprint = (ret_5d > sprint_min_return) & vol_huge

    return pd.DataFrame(
        {
            "accumulation": accumulation.fillna(False).astype(bool),
            "lift": lift.fillna(False).astype(bool),
            "sprint": sprint.fillna(False).astype(bool),
        },
        index=data.index,
    )
