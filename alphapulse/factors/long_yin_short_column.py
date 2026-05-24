"""长阴短柱因子。

识别"长阴短柱"K线形态：
- 阴线（收盘价 < 开盘价）
- 成交量较前日大幅萎缩（vol_shrink 倍以下）
- 实体幅度超过 body_min_pct%

含义：价格下跌但量能萎缩，说明抛压不重，可能是洗盘而非出货。
"""

import numpy as np
import pandas as pd


def compute(
    data: pd.DataFrame,
    vol_shrink: float = 0.7,
    body_min_pct: float = 1.0,
) -> pd.Series:
    """计算长阴短柱信号。

    Args:
        data: 含 'open', 'close', 'volume' 列的DataFrame
        vol_shrink: 成交量相对于前日的最大比例（默认0.7，即缩量30%以上）
        body_min_pct: 实体最小百分比（默认1.0，即实体 > 1%）

    Returns:
        pd.Series: 布尔Series，满足长阴短柱条件为True
    """
    # 阴线：收盘低于开盘
    yin_line = data["close"] < data["open"]

    # 成交量较前日萎缩
    prev_vol = data["volume"].shift(1)
    vol_shrunk = data["volume"] < prev_vol * vol_shrink

    # 实体幅度：|收盘-开盘| / 开盘 > body_min_pct / 100
    body_ratio = (data["close"] - data["open"]).abs() / data["open"]
    body_sufficient = body_ratio > (body_min_pct / 100.0)

    result = yin_line & vol_shrunk & body_sufficient

    return result.fillna(False).astype(bool)
