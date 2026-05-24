"""AlphaPulse-A B1->B2->B3 递进战法（基于B1选股公式）。

三阶段递进逻辑（独立输出，非合并信号）：
  B1（底部挖掘）: b1_formula (80%权重) + volume_b1 (20%增强)
  B2（确认信号）: B1出现后任意时间，放量阳线+收盘>白线
  B3（锁仓信号）: B2出现后任意时间，缩量阳线+主力锁仓

核心原则：
  - B1/B2/B3各自独立输出，不是合并信号
  - B2不要求紧接B1后N天——只要B1曾经出现过，之后任何时间出现B2条件就算
  - B3同理——只要B2出现过，之后任何时间出现B3条件就算
  - B1必须基于原始b1_formula（80%权重），增强信号用量能B1（20%权重）
  - 递进关系通过shift(1).cummax()实现，不设"B1后N天内"限制

因子依赖：
  b1_formula (主信号，80%权重), volume_b1 (增强信号，+20%),
  zhixing_trend (白线), violent_kline (B2暴力K增强)
"""

import pandas as pd
import numpy as np

from alphapulse.factors.b1_formula import compute as b1_compute
from alphapulse.factors.volume_b1 import compute as vol_b1_compute
from alphapulse.factors.zhixing_trend import compute_short_trend
from alphapulse.factors.violent_kline import compute as violent_kline_compute


def _empty_result() -> pd.DataFrame:
    """返回空的信号DataFrame（统一schema）。"""
    return pd.DataFrame(columns=[
        "symbol", "date", "signal", "strategy",
        "signal_type", "confidence", "factor_snapshot",
    ])


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    **params,
) -> pd.DataFrame:
    """生成 B1->B2->B3 递进战法信号（三列独立输出）。

    B1 入场逻辑（b1_formula 80%权重 + volume_b1 20%权重）:
      - 主信号: b1_formula.compute() 触发（cond1~cond6全部满足，决定性因素）
      - 增强信号: volume_b1.compute() 同时触发 -> 置信度 +0.2
      - B1信号 = 原始b1_formula触发
      - 置信度: b1_formula单独=0.6，量能B1叠加=0.8

    B2 确认逻辑（B1出现后任意时间，不要求连续几天内）:
      - has_b1_history = b1_signal.shift(1).cummax() 记录历史上是否出现过B1
        同时支持同日触发: b1_signal当天触发时也标记B2（如果满足条件）
      - 条件: 阳线涨幅>3% + 成交量>前日2倍 + 收盘>白线
      - 暴力K触发 = 增强（置信度 0.75->0.85）

    B3 锁定逻辑（B2出现后任意时间，不要求连续几天内）:
      - has_b2_history = b2_signal.shift(1).cummax() 记录历史上是否出现过B2
      - 条件: 阳线 + 缩量(<前日0.7) + 收盘>前日 + 最低>=B2日收盘
      - B3=主力锁仓，confidence最高0.9

    注意:
      - B1/B2在同一天可以同时出现（B1首次触发+当天就是放量阳线->同时标B1和B2）
      - 递进关系通过历史cummax实现，不设"N天内"限制

    Args:
        data: 日线OHLCV DataFrame，index=date，
              列需包含 open/high/low/close/volume
              可选: market_cap, pct_change, amplitude
        symbol: 股票代码
        **params: 参数覆盖，传递给b1_formula（如pct_change_range, j_threshold等）

    Returns:
        pd.DataFrame，index=date，列：
        - symbol: 股票代码
        - date: 信号日期（设为index）
        - signal: 1（买入）
        - strategy: "B1_B2_B3"
        - signal_type: "B1" | "B2" | "B3"
        - confidence: 0.6(B1) / 0.8(B1+量能) / 0.75(B2) / 0.85(B2增强) / 0.9(B3)
        - factor_snapshot: dict，各阶段关键快照值
    """
    n = len(data)
    if n < 120:
        return _empty_result()

    close = data["close"]
    open_ = data["open"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    # ---- 白线 = EMA(EMA(C,10),10) 知行短期趋势线 ----
    white_line = compute_short_trend(close)

    # ============================================================
    # B1 底部挖掘信号（b1_formula 80%权重决定，volume_b1 20%增强）
    # ============================================================

    # 主信号 (80%权重): b1_formula 6条件AND -- 决定性因素
    b1_main = b1_compute(data, **params)

    # 增强信号 (20%权重): volume_b1 量能体系 -- 增强信心但不强制
    b1_vol = vol_b1_compute(data)

    # B1 信号 = 原始b1_formula触发
    b1_signal = b1_main.fillna(False).astype(bool)

    # 量能B1叠加标记（用于置信度提升）
    b1_vol_on_signal = b1_signal & b1_vol.fillna(False)

    # ============================================================
    # B2 确认信号（B1出现后任意时间，不要求连续几天内）
    # ============================================================

    # 历史上是否出现过B1：shift(1).cummax() 记录前日及之前是否有B1
    # 同时允许当日B1触发时也满足B2（has_b1_history_or_today）
    has_b1_history = b1_signal.shift(1).cummax().fillna(False)
    has_b1_history_or_today = has_b1_history | b1_signal

    # B2条件: 阳线涨幅>3% + 成交量>前日2倍 + 收盘>白线
    yang_big = (close > open_) & (close.pct_change() > 0.03)
    vol_double = volume > (volume.shift(1) * 2)
    above_white = close > white_line
    b2_conditions = yang_big & vol_double & above_white

    b2_signal = has_b1_history_or_today & b2_conditions
    b2_signal = b2_signal.fillna(False).astype(bool)

    # B2增强: 暴力K触发 -> 置信度从0.75提升到0.85
    violent = violent_kline_compute(data)
    b2_enhanced = b2_signal & violent.fillna(False)

    # ============================================================
    # B3 锁定信号（B2出现后任意时间，不要求连续几天内）
    # ============================================================

    # 历史上是否出现过B2：shift(1).cummax() 记录前日及之前是否有B2
    has_b2_history = b2_signal.shift(1).cummax().fillna(False)

    # B3条件: 阳线 + 缩量(<前日0.7) + 收盘>前日 + 最低>=B2日收盘
    yang_line = close > open_
    vol_shrink = volume < (volume.shift(1) * 0.7)
    close_up = close > close.shift(1)

    # 最低不破B2收盘：追踪最近一次B2日的收盘价（主力锁仓特征）
    last_b2_close = close.where(b2_signal).ffill()
    low_above_b2 = low >= last_b2_close

    b3_signal = has_b2_history & yang_line & vol_shrink & close_up & low_above_b2
    b3_signal = b3_signal.fillna(False).astype(bool)

    # ============================================================
    # 构建输出（三列独立信号: B1 / B2 / B3）
    # ============================================================

    pct_change = close.pct_change()
    vol_ratio = volume / volume.shift(1)
    last_b2_close_filled = close.where(b2_signal).ffill()

    results = []

    # B1 signals
    for dt in data.index[b1_signal]:
        with_vol = bool(b1_vol_on_signal.loc[dt]) if dt in b1_vol_on_signal.index else False
        conf = 0.8 if with_vol else 0.6
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1_B2_B3",
            "signal_type": "B1",
            "confidence": conf,
            "factor_snapshot": {
                "close": float(close[dt]),
                "white_line": float(white_line[dt]) if pd.notna(white_line[dt]) else None,
                "b1_main": True,
                "volume_b1_enhanced": with_vol,
            },
        })

    # B2 signals
    for dt in data.index[b2_signal]:
        conf = 0.85 if bool(b2_enhanced.loc[dt]) else 0.75
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
                "white_line": float(white_line[dt]) if pd.notna(white_line[dt]) else None,
                "violent_k": bool(b2_enhanced.loc[dt]) if dt in b2_enhanced.index else False,
            },
        })

    # B3 signals
    for dt in data.index[b3_signal]:
        b2c = float(last_b2_close_filled[dt]) if pd.notna(last_b2_close_filled[dt]) else None
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
