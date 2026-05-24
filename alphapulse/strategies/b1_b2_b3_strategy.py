"""AlphaPulse-A B1→B2→B3 递进战法。

三阶段递进逻辑：
  B1（底部挖掘）: 7条件AND，信号日定位底部区域，confidence=0.6
  B2（确认）:     B1后5日内阳线放量突破白线，confidence=0.75（暴力K增强0.85）
  B3（锁定）:     B2后3日内缩量阳线+主力锁仓，confidence=0.9

因子依赖：
  kdj_j_low, shrink_to_abnormal, abnormal_vol, zhixing_trend,
  n_struct, violent_kline, double_volume_bar, key_kline
"""

import pandas as pd
import numpy as np

from alphapulse.factors import (
    kdj_j_low,
    shrink_to_abnormal,
    abnormal_vol,
    zhixing_trend,
    n_struct,
    violent_kline,
    double_volume_bar,
)
from alphapulse.factors.key_kline import compute as key_kline_compute


def _empty_result() -> pd.DataFrame:
    """返回空的信号DataFrame（统一schema）。"""
    return pd.DataFrame(columns=[
        "symbol", "date", "signal", "strategy",
        "signal_type", "confidence", "factor_snapshot",
    ])


def _compute_base_indicators(data: pd.DataFrame) -> dict:
    """预计算所有基础指标（向量化）。"""
    close = data["close"]
    high = data["high"]
    low = data["low"]
    open_ = data["open"]
    volume = data["volume"]

    # 白线 = EMA(EMA(C,10),10) 短期趋势
    white_line = zhixing_trend.compute_short_trend(close)
    # 黄线 = (MA20+MA60+MA120+MA250)/4 多空线
    yellow_line = zhixing_trend.compute_bull_bear_line(close)

    # 常用变换
    pct_change = close.pct_change()
    vol_ratio_to_prev = volume / volume.shift(1)

    return {
        "close": close, "high": high, "low": low, "open": open_,
        "volume": volume, "white_line": white_line, "yellow_line": yellow_line,
        "pct_change": pct_change, "vol_ratio_to_prev": vol_ratio_to_prev,
    }


def _compute_b1(data: pd.DataFrame, ind: dict) -> pd.Series:
    """B1 底部挖掘信号（向量化，7条件AND）。

    Returns:
        pd.Series[bool]: B1信号日为True
    """
    close = ind["close"]
    high = ind["high"]
    low = ind["low"]
    open_ = ind["open"]
    white = ind["white_line"]
    yellow = ind["yellow_line"]

    # 条件1: 股价在底部
    #   a) 近60日跌幅 > 10%
    decline_60d = (close / close.shift(60) - 1) < -0.10
    #   b) 近120日横盘（120日振幅 < 20%）
    range_120d = (close.rolling(120).max() / close.rolling(120).min() - 1)
    sideways_120d = range_120d < 0.20
    b1_c1 = decline_60d | sideways_120d

    # 条件2: KDJ J < 13（超卖）
    b1_c2 = kdj_j_low.compute(data, j_threshold=13.0)

    # 条件3: 缩量至异动量1/4以下
    b1_c3 = shrink_to_abnormal.compute(data)

    # 条件4: 近5日内至少1次放量异动
    b1_c4 = abnormal_vol.compute(data, X=1, Y=5)

    # 条件5: 股价 > 白线 OR 掉进碗里（白线以下、黄线以上）
    above_white = close > white
    in_bowl = (close < white) & (close > yellow)
    b1_c5 = above_white | in_bowl

    # 条件6: N_STRUCT = 0（排除已形成N型上涨结构的股票）
    ns_label = n_struct.compute(data)
    b1_c6 = ns_label.isna()

    # 条件7: 近10日振幅 < 15%（排除剧烈波动）
    amp_10d = (high.rolling(10).max() / low.rolling(10).min() - 1)
    b1_c7 = amp_10d < 0.15

    b1 = b1_c1 & b1_c2 & b1_c3 & b1_c4 & b1_c5 & b1_c6 & b1_c7
    return b1.fillna(False).infer_objects(copy=False)


def _compute_b2(data: pd.DataFrame, ind: dict, b1_signal: pd.Series) -> tuple:
    """B2 确认信号（向量化）。

    B2窗口：B1信号日后1~5个交易日内。

    Returns:
        (b2_signal: pd.Series[bool], b2_enhanced: pd.Series[bool])
    """
    close = ind["close"]
    open_ = ind["open"]
    volume = ind["volume"]
    white = ind["white_line"]
    pct_change = ind["pct_change"]

    # B1信号前推窗口：过去1~5天内有B1
    b1_int = b1_signal.fillna(False).astype(int)
    in_b2_window = b1_int.shift(1).rolling(5, min_periods=1).sum().fillna(0) > 0

    # B2条件1: 阳线涨幅 > 3%
    yang_big = (close > open_) & (pct_change > 0.03)

    # B2条件2: 成交量 > 前一日2倍（倍量柱）
    vol_double = volume > (volume.shift(1) * 2)

    # B2条件3: 收盘价 > 白线（脱离成本区）
    above_white = close > white

    # B2基础 = 窗口内 AND 三条件
    b2_base = yang_big & vol_double & above_white
    b2_signal = in_b2_window & b2_base

    # B2增强: 暴力K触发 → 置信度提升
    violent = violent_kline.compute(data)
    b2_enhanced = b2_signal & violent

    return b2_signal.fillna(False).infer_objects(copy=False), b2_enhanced.fillna(False).infer_objects(copy=False)


def _compute_b3(
    data: pd.DataFrame,
    ind: dict,
    b2_signal: pd.Series,
) -> pd.Series:
    """B3 锁定信号（向量化）。

    B3窗口：B2信号日后1~3个交易日内。

    Returns:
        pd.Series[bool]: B3信号日为True
    """
    close = ind["close"]
    low = ind["low"]
    open_ = ind["open"]
    volume = ind["volume"]

    # B2信号前推窗口：过去1~3天内有B2
    b2_int = b2_signal.fillna(False).astype(int)
    in_b3_window = b2_int.shift(1).rolling(3, min_periods=1).sum().fillna(0) > 0

    # B3条件1: 阳线 + 成交量 < 前一日0.7倍（缩量上涨）
    yang_shrink = (close > open_) & (volume < volume.shift(1) * 0.7)

    # B3条件2: 收盘价 > 前一日收盘价
    close_up = close > close.shift(1)

    # B3条件3: 最低价 >= B2日收盘价（主力锁仓，不破B2成本）
    last_b2_close = close.where(b2_signal).ffill().infer_objects(copy=False)
    low_above_b2 = low >= last_b2_close

    b3_signal = in_b3_window & yang_shrink & close_up & low_above_b2
    return b3_signal.fillna(False).infer_objects(copy=False)


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    **params,
) -> pd.DataFrame:
    """生成 B1→B2→B3 递进战法信号。

    Args:
        data: 日线OHLCV DataFrame，index=date，
              列需包含 open/high/low/close/volume
        symbol: 股票代码
        **params: 预留参数覆盖（当前使用默认参数）

    Returns:
        pd.DataFrame，index=date，列：
        - symbol: 股票代码
        - signal: 1（买入）
        - strategy: "B1_B2_B3"
        - signal_type: "B1" | "B2" | "B3"
        - confidence: 0.6(B1) / 0.75(B2) / 0.85(B2增强) / 0.9(B3)
        - factor_snapshot: dict，各阶段关键快照值
    """
    n = len(data)
    if n < 120:
        return _empty_result()

    # ---- 预计算基础指标 ----
    ind = _compute_base_indicators(data)

    # ---- 阶段计算 ----
    b1 = _compute_b1(data, ind)
    b2, b2_enh = _compute_b2(data, ind, b1)
    b3 = _compute_b3(data, ind, b2)

    # ---- 构建输出 ----
    close = ind["close"]
    white = ind["white_line"]
    yellow = ind["yellow_line"]
    pct_change = ind["pct_change"]
    vol_ratio = ind["vol_ratio_to_prev"]
    low = ind["low"]
    volume = ind["volume"]

    # B1快照预计算：是否在碗里
    in_bowl = (close < white) & (close > yellow)

    # B2收盘价前向填充（用于B3快照）
    last_b2_close = close.where(b2).ffill().infer_objects(copy=False)

    results = []

    # B1 signals
    for dt in data.index[b1]:
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1_B2_B3",
            "signal_type": "B1",
            "confidence": 0.6,
            "factor_snapshot": {
                "close": float(close[dt]),
                "white_line": float(white[dt]) if pd.notna(white[dt]) else None,
                "yellow_line": float(yellow[dt]) if pd.notna(yellow[dt]) else None,
                "in_bowl": bool(in_bowl[dt]),
            },
        })

    # B2 signals
    for dt in data.index[b2]:
        conf = 0.85 if b2_enh[dt] else 0.75
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1_B2_B3",
            "signal_type": "B2",
            "confidence": conf,
            "factor_snapshot": {
                "close": float(close[dt]),
                "pct_change": float(pct_change[dt]) if pd.notna(pct_change[dt]) else None,
                "vol_ratio_to_prev": float(vol_ratio[dt]) if pd.notna(vol_ratio[dt]) else None,
                "white_line": float(white[dt]) if pd.notna(white[dt]) else None,
                "violent_k": bool(b2_enh[dt]),
            },
        })

    # B3 signals
    for dt in data.index[b3]:
        b2c = float(last_b2_close[dt]) if pd.notna(last_b2_close[dt]) else None
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1_B2_B3",
            "signal_type": "B3",
            "confidence": 0.9,
            "factor_snapshot": {
                "close": float(close[dt]),
                "prev_close": float(close.shift(1)[dt]) if pd.notna(close.shift(1)[dt]) else None,
                "vol_shrink_ratio": float(vol_ratio[dt]) if pd.notna(vol_ratio[dt]) else None,
                "low": float(low[dt]),
                "b2_close_ref": b2c,
                "locked": True,
            },
        })

    if not results:
        return _empty_result()
    return pd.DataFrame(results).set_index("date").sort_index()
