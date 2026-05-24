"""填坑出坑因子。

识别"回落挖坑 → 横盘整理 → 放量出坑"的三段式形态。

坑阶段：价格从局部高位回落 > drop_pct%
整理阶段：坑底横盘 3-10 天，振幅 < 8%
出坑阶段：放量(> breakout_vol_mult 倍均量) 突破整理区间上沿
"""

import pandas as pd
import numpy as np


def compute(
    data: pd.DataFrame,
    drop_pct: float = 15.0,
    consolidation_days: int = 3,
    breakout_vol_mult: float = 1.5,
) -> pd.Series:
    """识别填坑出坑信号，返回布尔 Series。

    三段式形态：
    1. 坑：价格从滚动窗口内高点回落超过 drop_pct%
    2. 整理：坑底横盘，连续 consolidation_days~10 天振幅 < 8%
    3. 出坑：放量突破整理区间上沿（成交量 > breakout_vol_mult × 20日均量）

    Args:
        data: 含 'open','high','low','close','volume' 列的 DataFrame
        drop_pct: 回落幅度阈值（百分比，默认 15.0）
        consolidation_days: 整理最小天数（默认 3，上限固定为 10）
        breakout_vol_mult: 放量倍数（默认 1.5）

    Returns:
        pd.Series[bool]: 出坑日为 True
    """
    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    n = len(data)
    result = pd.Series(False, index=data.index)
    if n < 60:
        return result

    # ============================================================
    # 阶段1: 识别"坑"——回落下行
    # ============================================================
    # 滚动窗口最高价（60天作为参考高位）
    peak = high.rolling(60, min_periods=20).max()
    # 从峰值回落幅度（百分比）
    drawdown = (peak - close) / peak.replace(0, np.nan) * 100
    in_pit = drawdown > drop_pct

    # ============================================================
    # 阶段2: 识别"整理"——坑底窄幅横盘
    # ============================================================
    # 单日振幅
    amplitude_pct = (high - low) / close.shift(1).fillna(close) * 100
    is_narrow = amplitude_pct < 8.0

    # 计算连续窄幅天数（向量化：用 groupby-cumsum 模式）
    # 每次 is_narrow 为 False 时重置计数
    reset_signal = (~is_narrow).cumsum()
    narrow_streak = is_narrow.groupby(reset_signal).cumsum()

    # 整理条件：连续窄幅 >= consolidation_days 且 <= 10
    in_consolidation = (narrow_streak >= consolidation_days) & (narrow_streak <= 10)

    # ============================================================
    # 阶段3: 识别"出坑"——放量突破
    # ============================================================
    # 20日均量（排除当天，避免前瞻偏差）
    vol_ma = volume.shift(1).rolling(20, min_periods=5).mean()
    vol_surge = volume > breakout_vol_mult * vol_ma

    # 整理区间上沿：整理期间的最高价
    # 近似：用最近 10 天最高价（整理阶段上限）
    consolidation_high = high.rolling(10, min_periods=3).max()
    price_breakout = close > consolidation_high.shift(1)

    # ============================================================
    # 组合信号
    # ============================================================
    # 昨日处于整理阶段
    yesterday_consolidation = in_consolidation.shift(1).fillna(False)

    # 近期（20天内）曾出现坑（回落 > drop_pct%）
    recent_pit = in_pit.rolling(20, min_periods=1).max() > 0

    # 出坑信号：昨日整理 + 历史有坑 + 今日放量突破
    signal = yesterday_consolidation & recent_pit & vol_surge & price_breakout

    # 过滤：确保坑出现在整理之前（坑的最高点在整理开始前）
    # 使用一个简化条件：20日内的坑信号窗口包含了整理期之前
    # 已在 recent_pit 中体现（rolling max 覆盖 20 天）

    return signal.fillna(False).astype(bool)
