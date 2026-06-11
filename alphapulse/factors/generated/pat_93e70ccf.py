"""生成因子: 机构票缩量回调

描述: 股价长期在知行黄线上方运行（最近120日内收盘跌破黄线的天数不超过8天），且最近10日处于回调（10日累计跌幅在2%到15%之间），回调期间缩量（近5日均量低于20日均量的0.8倍），且近10日没有出现单日放量大阴线（跌幅超5%且量超20日均量1.5倍）
来源: deepseek
状态: 待验证（validate_signal 后手动启用）
"""

import pandas as pd
import numpy as np


def compute(data: pd.DataFrame, **params) -> pd.Series:
    # 可调参数
    max_below_days = params.get("max_below_days", 8)
    decline_min = params.get("decline_min", 0.02)
    decline_max = params.get("decline_max", 0.15)
    vol_ratio = params.get("volume_ratio", 0.8)
    bearish_pct = params.get("bearish_pct", -0.05)   # 跌幅超5%
    spike_ratio = params.get("volume_spike_ratio", 1.5)

    close = data["close"]
    volume = data["volume"]

    # 知行黄线 = (MA14+MA28+MA57+MA114)/4
    ma14 = close.rolling(14).mean()
    ma28 = close.rolling(28).mean()
    ma57 = close.rolling(57).mean()
    ma114 = close.rolling(114).mean()
    yellow_line = (ma14 + ma28 + ma57 + ma114) / 4

    # 条件1：最近120日内收盘跌破黄线的天数不超过 max_below_days
    below = close < yellow_line
    below_days_120 = below.rolling(120).sum()
    cond1 = below_days_120 <= max_below_days

    # 条件2：最近10日累计跌幅在 decline_min~decline_max 之间
    pct_10d = (close - close.shift(10)) / close.shift(10)  # 负值表示下跌
    cond2 = (pct_10d <= -decline_min) & (pct_10d >= -decline_max)

    # 条件3：近5日均量 < vol_ratio * 20日均量
    vol_ma5 = volume.rolling(5).mean()
    vol_ma20 = volume.rolling(20).mean()
    cond3 = vol_ma5 < vol_ratio * vol_ma20

    # 条件4：近10日无单日放量大阴线
    daily_ret = close.pct_change()
    big_bear = daily_ret < bearish_pct
    vol_spike = volume > spike_ratio * vol_ma20
    bear_event = big_bear & vol_spike
    cond4 = bear_event.rolling(10).max() == 0

    signal = cond1 & cond2 & cond3 & cond4
    return signal.fillna(False).astype(bool)