"""AlphaPulse-A 单针下三十策略 — N型上涨中主力洗盘补票。

完整逻辑链：
  前提（N型上涨中主力洗盘）:
    1. 标的在近60日内被B1_FORMULA选中（前期完美图形）
    2. 存在N型结构（N_STRUCT触发）
    3. 当前价格在N型T1→T2回调阶段（B峰之后、C谷之前）

  入场条件（全部满足=买入信号）:
    1. 长下影: 下影线长度(取min(open,close)-low) > 实体长度×3
    2. J超卖: KDJ_J_LOW触发(J<13)
    3. 缩量: 成交量 < 20日均量×0.7
    4. 回调30%-62%（Fibonacci区间，从N型T1高点B计算）
    5. 价格在近60日最低30%区间
    6. ZHIXING_TREND走平或回升（短期趋势线近5日斜率>=0）

  持仓管理（内建规则，供回测/实盘引用）:
    - 脱离成本3%以上 → 持有
    - 止损: 入场日最低价 - 0.03
    - 止盈: fly_away 逐步减仓
"""

import pandas as pd
import numpy as np

from alphapulse.factors.kdj_j_low import compute_kdj
from alphapulse.factors import b1_formula, zhixing_trend, n_struct


# ============================================================================
# 辅助函数
# ============================================================================

def _lower_shadow_length(open_: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """下影线长度 = min(open, close) - low。"""
    body_low = pd.concat([open_, close], axis=1).min(axis=1)
    return body_low - low


def _body_length(open_: pd.Series, close: pd.Series) -> pd.Series:
    """实体长度 = abs(close - open)。"""
    return (close - open_).abs()


def _price_position_in_range(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    N: int = 60,
) -> pd.Series:
    """价格在近N日波动区间内的相对位置，0=最低，1=最高。"""
    range_high = high.rolling(N).max()
    range_low = low.rolling(N).min()
    position = (close - range_low) / (range_high - range_low).replace(0, np.nan)
    return position.fillna(0.5)


def _build_n_structure_context(
    ns_labels: pd.Series,
    high: pd.Series,
    low: pd.Series,
) -> tuple:
    """从n_struct的A/B/C/D标签构建每根bar的N型上下文。

    遍历所有A-B-C序列，为每根bar标记：
      - phase: 1=上升段(A→B), 2=回调段(B→C=T1→T2), 3=再上升段(C→D), 0=无
      - a_price: 该N型结构中A点的价格
      - b_price: 该N型结构中B点的价格

    Returns:
        (phase, a_price, b_price) 三个 pd.Series
    """
    n = len(ns_labels)
    phase = pd.Series(0, index=ns_labels.index, dtype=int)
    a_price = pd.Series(np.nan, index=ns_labels.index, dtype=float)
    b_price = pd.Series(np.nan, index=ns_labels.index, dtype=float)

    # 收集所有有标签的枢轴点
    pivots = []
    for i in range(n):
        lbl = ns_labels.iloc[i]
        if isinstance(lbl, str) and lbl in ("A", "B", "C", "D"):
            pivots.append((i, lbl))

    if len(pivots) < 3:
        return phase, a_price, b_price

    # 遍历A-B-C三元组，标记各阶段
    for j in range(len(pivots) - 2):
        i1, l1 = pivots[j]
        i2, l2 = pivots[j + 1]
        i3, l3 = pivots[j + 2]

        if l1 != "A" or l2 != "B" or l3 != "C":
            continue

        b_val = high.iloc[i2]
        a_val = low.iloc[i1]

        # 上升段: A → B (含A和B)
        phase.iloc[i1 : i2 + 1] = 1
        a_price.iloc[i1 : i2 + 1] = a_val
        b_price.iloc[i1 : i2 + 1] = b_val

        # 回调段: B之后 → C (T1→T2，核心关注区域)
        phase.iloc[i2 + 1 : i3 + 1] = 2
        a_price.iloc[i2 + 1 : i3 + 1] = a_val
        b_price.iloc[i2 + 1 : i3 + 1] = b_val

        # 再上升段: C之后 → D (如果存在)
        for k in range(j + 3, len(pivots)):
            ik, lk = pivots[k]
            if lk == "D":
                phase.iloc[i3 + 1 : ik + 1] = 3
                a_price.iloc[i3 + 1 : ik + 1] = a_val
                b_price.iloc[i3 + 1 : ik + 1] = b_val
                break

    return phase, a_price, b_price


# ============================================================================
# 主信号生成函数
# ============================================================================

def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    all_stocks: dict | None = None,
    b1_lookback: int = 60,
    j_threshold: float = 13.0,
    volume_shrink_ratio: float = 0.7,
    volume_ma_period: int = 20,
    fib_min: float = 0.30,
    fib_max: float = 0.62,
    position_lookback: int = 60,
    position_threshold: float = 0.30,
    shadow_mult: float = 3.0,
    trend_slope_window: int = 5,
    **params,
) -> pd.DataFrame:
    """生成 AlphaPulse-A 单针下三十策略信号。

    Args:
        data: 日线OHLCV DataFrame，含 open/high/low/close/volume
        symbol: 股票代码
        all_stocks: 全市场股票数据dict（预留，用于跨标的B1历史交叉验证）
        b1_lookback: B1历史选中回溯天数
        j_threshold: KDJ J值超卖阈值
        volume_shrink_ratio: 缩量比例（相对于20日均量）
        volume_ma_period: 均量计算周期
        fib_min: Fibonacci回调区间下限（0.30=30%）
        fib_max: Fibonacci回调区间上限（0.62=62%）
        position_lookback: 价格位置判断窗口
        position_threshold: 价格低位阈值（<此值=低位）
        shadow_mult: 下影线/实体长度最小倍数
        trend_slope_window: 趋势走平判断窗口（日内diff）

    Returns:
        DataFrame，含列: symbol, date, signal, strategy, confidence, factor_snapshot
    """
    close = data["close"]
    open_ = data["open"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]
    idx = data.index
    n = len(data)

    # ---- 快速返回：数据不足 ----
    min_bars = max(b1_lookback, volume_ma_period, position_lookback, trend_slope_window + 10, 60)
    if n < min_bars:
        return pd.DataFrame(
            columns=["symbol", "date", "signal", "strategy", "confidence", "factor_snapshot"]
        )

    empty_result = pd.DataFrame(
        columns=["symbol", "date", "signal", "strategy", "confidence", "factor_snapshot"]
    )

    # ========================================================================
    # 前提条件 P1: 近60日内被B1_FORMULA选中
    # ========================================================================
    b1_signal = b1_formula.compute(data)
    b1_recent_60d = b1_signal.rolling(b1_lookback, min_periods=1).max().fillna(0).astype(bool)

    # ========================================================================
    # 前提条件 P2: N型结构触发
    # ========================================================================
    ns_labels = n_struct.compute(data)
    has_any_n_struct = ns_labels.notna().any()
    ns_triggered = pd.Series(False, index=idx)
    if has_any_n_struct:
        first_ns = ns_labels.first_valid_index()
        if first_ns is not None:
            ns_triggered = pd.Series(idx >= first_ns, index=idx)

    # ========================================================================
    # 前提条件 P3: 当前在N型T1→T2回调阶段 + AB价格上下文
    # ========================================================================
    n_phase, a_price_ctx, b_price_ctx = _build_n_structure_context(ns_labels, high, low)
    in_pullback = n_phase == 2  # phase=2 即 B→C 回调段

    # ========================================================================
    # 入场条件 C1: 长下影 — 下影线长度 > 实体长度 × shadow_mult
    # ========================================================================
    lower_shadow = _lower_shadow_length(open_, low, close)
    body = _body_length(open_, close)
    cond_long_shadow = lower_shadow > body * shadow_mult

    # ========================================================================
    # 入场条件 C2: J超卖 — KDJ J值 < j_threshold
    # ========================================================================
    _, _, j = compute_kdj(high, low, close)
    cond_j_oversold = j < j_threshold

    # ========================================================================
    # 入场条件 C3: 缩量 — 成交量 < 20日均量 × volume_shrink_ratio
    # ========================================================================
    vol_ma = volume.rolling(volume_ma_period).mean()
    cond_volume_shrink = volume < vol_ma * volume_shrink_ratio

    # ========================================================================
    # 入场条件 C4: 回调30%-62%（Fibonacci区间）
    #   retrace = (B_price - close) / (B_price - A_price)
    #   其中 B 是T1高点，A 是前一个低点
    # ========================================================================
    ab_range = b_price_ctx - a_price_ctx
    # 只在有效N型上下文中计算回撤比
    valid_ctx = in_pullback & ab_range.notna() & (ab_range > 0)
    fib_retrace_value = pd.Series(np.nan, index=idx, dtype=float)
    fib_retrace_value[valid_ctx] = (
        (b_price_ctx[valid_ctx] - close[valid_ctx]) / ab_range[valid_ctx]
    )
    cond_fib_retrace = (fib_retrace_value >= fib_min) & (fib_retrace_value <= fib_max)
    cond_fib_retrace = cond_fib_retrace.fillna(False)

    # ========================================================================
    # 入场条件 C5: 价格在近60日最低30%区间
    # ========================================================================
    price_pos = _price_position_in_range(close, high, low, position_lookback)
    cond_low_position = price_pos < position_threshold

    # ========================================================================
    # 入场条件 C6: ZHIXING_TREND 走平或回升
    #   短期趋势线 = EMA(EMA(C,10),10)，近N日斜率 >= 0
    # ========================================================================
    short_trend = zhixing_trend.compute_short_trend(close)
    trend_slope = short_trend.diff(trend_slope_window)
    cond_trend_flat_rising = trend_slope >= 0

    # ---- 额外：确认前一日非长下影（单针，非连续下影） ----
    prev_long_shadow = cond_long_shadow.shift(1).fillna(False)

    # ========================================================================
    # 综合信号：全部前提 + 全部入场条件 + 单针确认
    # ========================================================================
    signal_mask = (
        b1_recent_60d
        & ns_triggered
        & in_pullback
        & cond_long_shadow
        & ~prev_long_shadow
        & cond_j_oversold
        & cond_volume_shrink
        & cond_fib_retrace
        & cond_low_position
        & cond_trend_flat_rising
    )

    # ========================================================================
    # 构建输出
    # ========================================================================
    signal_dates = idx[signal_mask]
    if len(signal_dates) == 0:
        return empty_result

    results = []
    for dt in signal_dates:
        # 综合置信度：各条件加权求和（满分1.0）
        c_b1 = float(b1_recent_60d[dt])
        c_ns = float(ns_triggered[dt])
        c_pb = float(in_pullback[dt])
        c_shadow = float(cond_long_shadow[dt])
        c_j = float(cond_j_oversold[dt])
        c_vol = float(cond_volume_shrink[dt])
        c_fib = float(cond_fib_retrace[dt])
        c_pos = float(cond_low_position[dt])
        c_tr = float(cond_trend_flat_rising[dt])

        # 前提3项各0.10 + 入场6项各~0.117
        confidence = (
            c_b1 * 0.10 + c_ns * 0.10 + c_pb * 0.10
            + c_shadow * 0.15 + c_j * 0.10 + c_vol * 0.10
            + c_fib * 0.15 + c_pos * 0.10 + c_tr * 0.10
        )
        # 由于AND逻辑，全部满足时confidence=1.0；这里保留计算框架供日后
        # 引入软条件（部分满足）时使用。

        snapshot = {
            "shadow_mult": round(
                float(lower_shadow[dt] / max(body[dt], 1e-8)), 2
            ),
            "j_value": round(float(j[dt]), 2),
            "volume_ratio": round(float(volume[dt] / max(vol_ma[dt], 1)), 3),
            "fib_retrace": (
                round(float(fib_retrace_value[dt]), 3)
                if pd.notna(fib_retrace_value[dt])
                else None
            ),
            "price_position": round(float(price_pos[dt]), 3),
            "trend_slope": round(float(trend_slope[dt]), 4),
            "close": float(close[dt]),
            "volume": float(volume[dt]),
            "low": float(low[dt]),
            "b1_selected_recent": c_b1 == 1.0,
            "in_pullback": c_pb == 1.0,
        }
        results.append(
            {
                "symbol": symbol,
                "date": dt,
                "signal": 1,
                "strategy": "NEEDLE_WASHOUT",
                "confidence": round(confidence, 4),
                "factor_snapshot": snapshot,
            }
        )

    return pd.DataFrame(results).set_index("date").sort_index()
