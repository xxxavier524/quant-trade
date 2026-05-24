"""砖型图超短选股因子。

来源：砖型图.txt + 砖型图超短选股.txt

通达信源码翻译为Python：
  VAR1A := (HHV(H,4)-C)/(HHV(H,4)-LLV(L,4))*100-90
  VAR2A := SMA(VAR1A,4,1)+100
  VAR3A := (C-LLV(L,4))/(HHV(H,4)-LLV(L,4))*100
  VAR4A := SMA(VAR3A,6,1)
  VAR5A := SMA(VAR4A,6,1)+100
  VAR6A := VAR5A-VAR2A
  砖型图 := IF(VAR6A>4, VAR6A-4, 0)

选股条件（砖型图超短选股.txt）：
  昨日为绿柱（昨值<前值，有实体差）
  今日为红柱（今值>昨值，有实体差）
  今红实体 >= 昨日绿柱实体的 2/3
"""

import pandas as pd
import numpy as np


def _sma(series: pd.Series, n: int, m: float) -> pd.Series:
    """通达信SMA实现: SMA(X,N,M) = (M*X + (N-M)*Y')/N。

    使用 numpy 数组加速替代 pandas .iloc 逐行访问。
    """
    values = series.values.astype(np.float64)
    alpha = m / n
    result = values.copy()
    for i in range(1, len(values)):
        if not np.isnan(values[i]) and not np.isnan(result[i - 1]):
            result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return pd.Series(result, index=series.index)


def compute_brick_indicator(data: pd.DataFrame) -> pd.Series:
    """计算砖型图指标（等同通达信砖型图:=...）。

    Returns:
        pd.Series: 砖型图值，>=0
    """
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)

    # HHV(H,4), LLV(L,4)
    hhv4 = high.rolling(4).max()
    llv4 = low.rolling(4).min()
    hhv4_llv4_range = (hhv4 - llv4).replace(0, np.nan)

    # VAR1A := (HHV(H,4)-C)/(HHV(H,4)-LLV(L,4))*100-90
    var1a = ((hhv4 - close) / hhv4_llv4_range) * 100 - 90

    # VAR2A := SMA(VAR1A,4,1)+100
    var2a = _sma(var1a, 4, 1) + 100

    # VAR3A := (C-LLV(L,4))/(HHV(H,4)-LLV(L,4))*100
    var3a = ((close - llv4) / hhv4_llv4_range) * 100

    # VAR4A := SMA(VAR3A,6,1), VAR5A := SMA(VAR4A,6,1)+100
    var4a = _sma(var3a, 6, 1)
    var5a = _sma(var4a, 6, 1) + 100

    # VAR6A := VAR5A-VAR2A
    var6a = var5a - var2a

    # 砖型图 := IF(VAR6A>4, VAR6A-4, 0)
    brick = pd.Series(np.where(var6a > 4, var6a - 4, 0), index=data.index)

    return brick.fillna(0)


def compute(
    data: pd.DataFrame,
    min_ratio: float = 2 / 3,
) -> pd.Series:
    """砖型图超短选股：昨日绿柱→今日红柱，红实体≥绿实体×2/3。

    Args:
        data: 日线OHLC DataFrame
        min_ratio: 红实体/绿实体最小比例

    Returns:
        pd.Series[bool]
    """
    brick = compute_brick_indicator(data)
    result = pd.Series(False, index=data.index)

    if len(brick) < 3:
        return result

    # 逐日检查绿→红转换
    for i in range(2, len(brick)):
        val_today = brick.iloc[i]
        val_yest = brick.iloc[i - 1]
        val_prev = brick.iloc[i - 2]

        # 昨日绿柱: 昨值 < 前值 且有实体差
        green_body = val_prev - val_yest
        yesterday_green = (val_yest < val_prev) and (green_body > 0)

        # 今日红柱: 今值 > 昨值 且有实体差
        red_body = val_today - val_yest
        today_red = (val_today > val_yest) and (red_body > 0)

        # 红实体 >= 绿实体 * min_ratio
        if yesterday_green and today_red and (red_body >= min_ratio * green_body):
            result.iloc[i] = True

    return result


def compute_detail(data: pd.DataFrame) -> pd.DataFrame:
    """返回砖型图指标和选股条件的详细值。"""
    brick = compute_brick_indicator(data)
    prev_brick = brick.shift(1)
    prev2_brick = brick.shift(2)

    green_body = prev2_brick - prev_brick
    red_body = brick - prev_brick

    return pd.DataFrame({
        "brick_value": brick.round(2),
        "prev_brick": prev_brick.round(2),
        "green_body": green_body.round(2),
        "red_body": red_body.round(2),
        "yesterday_green": (prev_brick < prev2_brick) & (green_body > 0),
        "today_red": (brick > prev_brick) & (red_body > 0),
    }, index=data.index)
