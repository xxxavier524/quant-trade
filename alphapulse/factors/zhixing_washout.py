"""知行洗盘短线因子。

来源：知行洗盘短线.txt

四线系统：
- 短期: 100*(C-LLV(L,N1))/(HHV(C,N1)-LLV(L,N1))  (参数N1)
- 中期: 100*(C-LLV(L,10))/(HHV(C,10)-LLV(L,10))
- 中长期: 100*(C-LLV(L,20))/(HHV(C,20)-LLV(L,20))
- 长期: 100*(C-LLV(L,N2))/(HHV(C,N2)-LLV(L,N2))  (参数N2)

买入信号（知行超短选股方案.txt引用条件4）：
- 四线归零买: 短期≤6 AND 中期≤6 AND 中长期≤6 AND 长期≤6
- 白线下20买: 短期≤20 AND 长期≥60
- 白穿红线买: CROSS(短期, 长期) AND 长期<20
- 白穿黄线买: CROSS(短期, 中期) AND 中期<30
- 中长期值 > 65（来自知行超短选股方案.txt条件4）
"""

import pandas as pd
import numpy as np


def _stochastic_range(close, low, period):
    """计算通达信风格的随机指标值: 100*(C-LLV(L,P))/(HHV(C,P)-LLV(L,P))。"""
    llv_l = low.rolling(period).min()
    hhv_c = close.rolling(period).max()
    hhv_l = low.rolling(period).min()
    rng = (hhv_c - llv_l).replace(0, np.nan)
    return ((close - llv_l) / rng) * 100


def compute_lines(
    data: pd.DataFrame,
    n1: int = 5,
    n2: int = 30,
) -> pd.DataFrame:
    """计算四线值。

    Returns:
        DataFrame: 含 short/medium/med_long/long 四列
    """
    close = data["close"].astype(float)
    low = data["low"].astype(float)

    return pd.DataFrame({
        "short": _stochastic_range(close, low, n1),        # 短期
        "medium": _stochastic_range(close, low, 10),       # 中期
        "med_long": _stochastic_range(close, low, 20),     # 中长期
        "long": _stochastic_range(close, low, n2),         # 长期
    }, index=data.index)


def compute(
    data: pd.DataFrame,
    n1: int = 5,
    n2: int = 30,
) -> pd.Series:
    """知行洗盘短线：任一买入条件满足则返回True。

    买入条件:
    1. 四线归零: 全部 ≤ 6
    2. 白线下20: 短期 ≤ 20 AND 长期 ≥ 60
    3. 白穿红: CROSS(短期,长期) AND 长期 < 20
    4. 白穿黄: CROSS(短期,中期) AND 中期 < 30
    5. 中长期 > 65（知行超短方案条件4）

    Returns:
        pd.Series[bool]
    """
    lines = compute_lines(data, n1, n2)
    short = lines["short"]
    medium = lines["medium"]
    med_long = lines["med_long"]
    long_ = lines["long"]

    # 1. 四线归零买
    cond_zero = (short <= 6) & (medium <= 6) & (med_long <= 6) & (long_ <= 6)
    # 2. 白线下20买
    cond_white20 = (short <= 20) & (long_ >= 60)
    # 3. 白穿红线买: CROSS(短期,长期) AND 长期<20
    prev_short, prev_long = short.shift(1), long_.shift(1)
    cross_red = (prev_short <= prev_long) & (short > long_) & (long_ < 20)
    # 4. 白穿黄线买: CROSS(短期,中期) AND 中期<30
    prev_medium = medium.shift(1)
    cross_yellow = (prev_short <= prev_medium) & (short > medium) & (medium < 30)
    # 5. 中长期 > 65（知行超短方案用）
    cond_med_long_65 = med_long > 65

    result = cond_zero | cond_white20 | cross_red | cross_yellow | cond_med_long_65
    return result.fillna(False).astype(bool)


def compute_detail(data: pd.DataFrame, n1: int = 5, n2: int = 30) -> pd.DataFrame:
    """返回四线和所有买入条件的详细信息。"""
    lines = compute_lines(data, n1, n2)
    short = lines["short"]
    medium = lines["medium"]
    med_long = lines["med_long"]
    long_ = lines["long"]

    prev_short, prev_long = short.shift(1), long_.shift(1)
    prev_medium = medium.shift(1)

    return pd.DataFrame({
        "short": short.round(1),
        "medium": medium.round(1),
        "med_long": med_long.round(1),
        "long": long_.round(1),
        "cond_zero": (short <= 6) & (medium <= 6) & (med_long <= 6) & (long_ <= 6),
        "cond_white20": (short <= 20) & (long_ >= 60),
        "cond_cross_red": (prev_short <= prev_long) & (short > long_) & (long_ < 20),
        "cond_cross_yellow": (prev_short <= prev_medium) & (short > medium) & (medium < 30),
        "cond_med_long_65": med_long > 65,
    }, index=data.index)
