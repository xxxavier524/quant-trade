"""AlphaPulse-A 单针下三十策略 — N型上涨中主力洗盘补票（优化版v2）。

  放宽条件以提升命中率（4.4% → 目标>40%）：
    - J值阈值: 13 → 20（可调 j_threshold=20）
    - Fibonacci回调区间: 30%-62% → 20%-70%
    - 缩量比率: 0.7 → 0.85
    - B1前期选中前提: 默认关闭（require_b1_history=False）
    - N型回调阶段: 仍保留，但允许无N型上下文时用通用价格低位判断

  完整逻辑链：
    前提（可选，可配置开关）:
      1. [可选] 标的在近60日内被B1_FORMULA选中（前期完美图形）
      2. [核心] 存在N型结构（N_STRUCT触发）
      3. [核心] 当前价格在N型T1→T2回调阶段（B峰之后、C谷之前）
         - 若无N型上下文，退化为：近60日高点回落>15%

    入场条件（全部满足=买入信号）:
      1. 长下影: 下影线长度(取min(open,close)-low) > 实体长度×3
      2. J超卖: KDJ J值 < j_threshold (默认20)
      3. 缩量: 成交量 < 20日均量×volume_shrink_ratio (默认0.85)
      4. 回调20%-70%（Fibonacci区间放宽）
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


# ============================================================================
# 主信号生成函数
# ============================================================================

def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    all_stocks: dict | None = None,
    b1_lookback: int = 60,
    require_b1_history: bool = False,
    j_threshold: float = 20.0,
    volume_shrink_ratio: float = 0.85,
    volume_ma_period: int = 20,
    fib_min: float = 0.20,
    fib_max: float = 0.70,
    position_lookback: int = 60,
    position_threshold: float = 0.30,
    shadow_mult: float = 3.0,
    trend_slope_window: int = 5,
    **params,
) -> pd.DataFrame:
    """生成 AlphaPulse-A 单针下三十策略信号（优化版v2）。

    Args:
        data: 日线OHLCV DataFrame，含 open/high/low/close/volume
        symbol: 股票代码
        all_stocks: 全市场股票数据dict（预留，用于跨标的B1历史交叉验证）
        b1_lookback: B1历史选中回溯天数（默认60）
        require_b1_history: 是否要求近60日内曾被B1_FORMULA选中（默认False，关闭以提升命中率）
        j_threshold: KDJ J值超卖阈值（默认20，放宽自13）
        volume_shrink_ratio: 缩量比例相对于20日均量（默认0.85，放宽自0.7）
        volume_ma_period: 均量计算周期
        fib_min: Fibonacci回调区间下限（默认0.20=20%，放宽自0.30）
        fib_max: Fibonacci回调区间上限（默认0.70=70%，放宽自0.62）
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
    # 前提条件 P1: 近60日内被B1_FORMULA选中（可选，默认关闭以提升命中率）
    # ========================================================================
    if require_b1_history:
        b1_signal = b1_formula.compute(data)
        b1_recent_60d = b1_signal.rolling(b1_lookback, min_periods=1).max().fillna(0).astype(bool)
    else:
        b1_recent_60d = pd.Series(True, index=idx)

    # ========================================================================
    # 前提条件 P2/P3: N型结构触发 + T1→T2回调阶段上下文
    # v5 因果版（2026-08-02）：旧版 _build_n_structure_context 用未来确认的
    # C/D 枢轴标记回调段 = 未来函数，命中率系统性虚高。compute_causal 把阶段
    # 按"确认时点"（枢轴日+min_leg_len）对齐，只有 ≤t 的信息可见。
    # ========================================================================
    ns_ctx = n_struct.compute_causal(data)
    n_phase = ns_ctx["phase"]
    a_price_ctx = ns_ctx["a_price"]
    b_price_ctx = ns_ctx["b_price"]
    in_pullback = n_phase == 2  # phase=2 即 B→C 回调段（C 确认后才可见）

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
    # 入场条件 C4: 回调20%-70%（Fibonacci区间放宽）
    #   优先使用N型上下文计算：retrace = (B_price - close) / (B_price - A_price)
    #   无N型上下文时退化为：近60日高点回落 > 10%（放宽，避免排除全部案例）
    # ========================================================================
    ab_range = b_price_ctx - a_price_ctx
    valid_ctx = in_pullback & ab_range.notna() & (ab_range > 0)

    # N型上下文中的精确斐波那契回撤
    fib_retrace_value = pd.Series(np.nan, index=idx, dtype=float)
    if valid_ctx.any():
        fib_retrace_value[valid_ctx] = (
            (b_price_ctx[valid_ctx] - close[valid_ctx]) / ab_range[valid_ctx]
        )
    fib_retrace_from_n = (
        (fib_retrace_value >= fib_min) & (fib_retrace_value <= fib_max)
    ).fillna(False).astype(bool)

    # 无N型退化为：从近60日最高点回落10%以上
    high_60d = high.rolling(position_lookback).max()
    fall_from_high = (high_60d - close) / high_60d.replace(0, np.nan)
    cond_fallback_pullback = fall_from_high > 0.10  # 回落至少10%

    # 优先用N型精确回调，退而用60日高位回落
    cond_fib_retrace = fib_retrace_from_n | (
        (~in_pullback) & cond_fallback_pullback
    )
    cond_fib_retrace = cond_fib_retrace.fillna(False).infer_objects(copy=False)

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
    prev_long_shadow = cond_long_shadow.shift(1, fill_value=False)
    # 确保 bool dtype
    if prev_long_shadow.dtype != bool:
        prev_long_shadow = prev_long_shadow.astype(bool)

    # ========================================================================
    # 综合信号：核心入场条件（AND逻辑）+ 可选前提 + 单针确认
    #
    # 硬条件（缺一不可）:
    #   C1: 长下影 + C1b: 非连续下影（单针确认）
    #   C2: J超卖
    #   C3: 缩量
    #   C4: 价格回调（N型Fib或60日高位回落）
    #   C5: 价格在低位区间
    #   C6: 趋势走平或回升
    #
    # 软条件（可选/可配置）:
    #   P1: B1历史选中（require_b1_history控制）
    #   P2/P3: N型结构 + 回调阶段（已融入C4的退化逻辑）
    # ========================================================================
    signal_mask = (
        b1_recent_60d  # 由require_b1_history控制，默认全部True
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
        c_b1 = float(b1_recent_60d[dt])
        c_shadow = float(cond_long_shadow[dt])
        c_j = float(cond_j_oversold[dt])
        c_vol = float(cond_volume_shrink[dt])
        c_fib = float(cond_fib_retrace[dt])
        c_pos = float(cond_low_position[dt])
        c_tr = float(cond_trend_flat_rising[dt])

        # 核心入场条件权重（6项均等 ~0.167，满分1.0）
        # B1历史可选前提不占权重（已通过b1_recent_60d参与AND但不计入confidence）
        confidence = (
            c_shadow * 0.20 + c_j * 0.15 + c_vol * 0.15
            + c_fib * 0.20 + c_pos * 0.15 + c_tr * 0.15
        )
        # 由于AND逻辑，全部满足时confidence=1.0

        # fib_retrace回退值：N型上下文中用fib_retrace_value，否则用60日高位回落比
        use_fib = pd.notna(fib_retrace_value[dt])
        fib_display = (
            round(float(fib_retrace_value[dt]), 3)
            if use_fib
            else round(float(fall_from_high[dt]), 3)
        )

        snapshot = {
            "shadow_mult": round(
                float(lower_shadow[dt] / max(body[dt], 1e-8)), 2
            ),
            "j_value": round(float(j[dt]), 2),
            "volume_ratio": round(float(volume[dt] / max(vol_ma[dt], 1)), 3),
            "fib_retrace": fib_display,
            "fib_from_n_struct": bool(use_fib),
            "price_position": round(float(price_pos[dt]), 3),
            "trend_slope": round(float(trend_slope[dt]), 4),
            "close": float(close[dt]),
            "volume": float(volume[dt]),
            "low": float(low[dt]),
            "b1_selected_recent": c_b1 == 1.0,
            "in_pullback": bool(in_pullback[dt]),
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
