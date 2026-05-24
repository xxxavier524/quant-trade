"""AlphaPulse-A 砖型图3子类型策略 -- 横盘检测增强版。

基于 brick_ultra.compute_brick_indicator 获取砖型值：
- 红砖: indicator > 0 (多方力量占优)
- 绿砖: indicator == 0 (多空平衡/空方)

核心改动：红砖买入信号之前必须有横盘(consolidation)迹象。

三个子类型信号：
1. BRICK_N_JUMP:     N型起跳 (红砖+横盘检测+力度+放量+黄线)
2. BRICK_CONTINUATION: 上涨中继 (趋势+回调+横盘不深+量柱放大)
3. BRICK_BREAKOUT:   横盘突破 (检测横盘+红砖突破+突破前高+放量)
"""

import pandas as pd
import numpy as np
from alphapulse.factors.brick_ultra import compute_brick_indicator
from alphapulse.factors.zhixing_trend import compute_bull_bear_line


# =========================================================================
# 横盘检测
# =========================================================================

def detect_consolidation(data, lookback=5, max_amplitude=15.0) -> pd.Series:
    """检测横盘。返回bool Series，横盘期为True。

    横盘定义：
    - 时间段：lookback个交易日 (建议3-8)
    - 振幅：期间(最高-最低)/最低 ≤ max_amplitude%
    - 量能：期间均量 < 之前20日均量的1.2倍（缩量或温和）
    - 当前价格在横盘区间上沿附近（收盘价 >= 区间最高价 × 0.95）

    Args:
        data: 日线OHLCV DataFrame
        lookback: 横盘回看天数，默认5
        max_amplitude: 最大振幅百分比，默认15.0 (即15%)

    Returns:
        pd.Series[bool]: 当天处于横盘末端则为True
    """
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    volume = data["volume"].astype(float)

    # 振幅: (rolling_max - rolling_min) / rolling_min
    roll_high = high.rolling(lookback).max()
    roll_low = low.rolling(lookback).min()
    amplitude = (roll_high - roll_low) / roll_low

    # 量能: 期间均量 < 20日均量 × 1.2
    roll_vol = volume.rolling(lookback).mean()
    ma20_vol = volume.rolling(20).mean()
    vol_mild = roll_vol < ma20_vol * 1.2

    # 价格在区间上沿附近: 收盘价 >= 区间最高价 × 0.95
    near_upper = close >= roll_high * 0.95

    consolidation = (
        (amplitude <= max_amplitude / 100.0) & vol_mild & near_upper
    )

    return consolidation.fillna(False)


# =========================================================================
# 辅助函数
# =========================================================================

def _find_green_to_red_transition(
    is_green: pd.Series, is_red: pd.Series, end: int, lookback: int = 5
) -> int:
    """在前 lookback 日内寻找最近的绿→红转换点。

    Args:
        is_green: indicator==0 序列
        is_red: indicator>0 序列
        end: 搜索终点索引（不含，即检查 end-1 之前的转换）
        lookback: 回看天数

    Returns:
        绿→红转换日的索引，未找到返回 -1
    """
    start = max(0, end - lookback)
    for j in range(end - 1, start, -1):
        if is_green.iloc[j - 1] and is_red.iloc[j]:
            return j
    return -1


def _recent_consolidation(
    consolidation: pd.Series, end: int, lookback: int
) -> bool:
    """检查 [end-lookback, end) 窗口内是否存在横盘。

    Args:
        consolidation: detect_consolidation 的输出 Series
        end: 窗口终点索引（不含）
        lookback: 回看天数

    Returns:
        bool: 窗口内至少一天为横盘
    """
    start = max(0, end - lookback)
    if end - start < 2:
        return False
    return bool(consolidation.iloc[start:end].any())


# =========================================================================
# Type 1: N型起跳 (BRICK_N_JUMP)
# =========================================================================

def _check_n_jump(
    data: pd.DataFrame,
    brick: pd.Series,
    is_red: pd.Series,
    is_green: pd.Series,
    volume: pd.Series,
    ma20_vol: pd.Series,
    bull_bear_line: pd.Series,
    close: pd.Series,
    consolidation: pd.Series,
    i: int,
    tolerance: float,
    vol_mult: float,
    consol_lookback: int,
    require_consolidation: bool,
) -> tuple:
    """检查 Type 1: N型起跳 (BRICK_N_JUMP)。

    条件：
    1. [NEW] 前N日有横盘迹象 (consolidation)
    2. 前5日有绿→红转换
    3. 红砖值 > 前绿砖绝对值 × 2/3 (indicator>0 自然满足)
    4. 成交量 > 20日均量 × vol_mult
    5. 收盘价在黄线±tolerance

    Returns:
        (confidence: float, consolidation_detected: bool)
    """
    if not is_red.iloc[i]:
        return (0.0, False)

    # ---- 条件1 [NEW]: 横盘检测 ----
    consol_detected = False
    if require_consolidation:
        consol_detected = _recent_consolidation(consolidation, i, consol_lookback)
        if not consol_detected:
            return (0.0, False)
    else:
        # 即使不强制也记录横盘状态
        consol_detected = _recent_consolidation(consolidation, i, consol_lookback)

    # ---- 条件2: 前5日有绿→红转换 ----
    transition_idx = _find_green_to_red_transition(is_green, is_red, i, lookback=5)
    if transition_idx < 0:
        return (0.0, consol_detected)

    # ---- 条件3: 红砖值 > 前红砖 × 2/3 (N型两腿力度比) ----
    prev_red_val = 0.0
    for j in range(transition_idx - 1, max(0, transition_idx - 20), -1):
        if is_red.iloc[j]:
            prev_red_val = brick.iloc[j]
            break
    if prev_red_val > 0 and brick.iloc[i] <= prev_red_val * 2 / 3:
        return (0.0, consol_detected)

    # ---- 条件4: 成交量 > 20日均量 × vol_mult ----
    vol_ma = ma20_vol.iloc[i]
    if pd.isna(vol_ma) or volume.iloc[i] <= vol_ma * vol_mult:
        return (0.0, consol_detected)

    # ---- 条件5: 收盘价在黄线±tolerance ----
    bb = bull_bear_line.iloc[i]
    if pd.isna(bb) or bb <= 0:
        return (0.0, consol_detected)
    if abs(close.iloc[i] - bb) / bb > tolerance:
        return (0.0, consol_detected)

    # ---- 置信度计算 ----
    confidence = 0.60
    # 有横盘加分
    if consol_detected:
        confidence += 0.05

    if prev_red_val > 0:
        ratio = brick.iloc[i] / prev_red_val
        if ratio > 1.0:
            confidence += 0.20
        elif ratio > 0.8:
            confidence += 0.10
    vol_ratio = volume.iloc[i] / vol_ma
    if vol_ratio > 2.0:
        confidence += 0.20
    elif vol_ratio > 1.5:
        confidence += 0.10

    return (min(1.0, confidence), consol_detected)


# =========================================================================
# Type 2: 上涨中继 (BRICK_CONTINUATION)
# =========================================================================

def _check_continuation(
    data: pd.DataFrame,
    brick: pd.Series,
    is_red: pd.Series,
    is_green: pd.Series,
    volume: pd.Series,
    close: pd.Series,
    low: pd.Series,
    high: pd.Series,
    high_vol_bullish: pd.Series,
    consolidation: pd.Series,
    i: int,
    cont_lookback: tuple,
    pullback_days: tuple,
    vol_expand_mult: float,
    pullback_depth_max: float,
) -> tuple:
    """检查 Type 2: 上涨中继 (BRICK_CONTINUATION)。

    条件：
    1. 前5-10日有红砖序列（上涨趋势）
    2. 前1-2日为绿砖（短暂回调）
    3. 当日为红砖（恢复上涨）
    4. 回调最低价 > 最近放量阳线收盘价（不破位）
    5. [NEW] 横盘不深: 回调深度 ≤ pullback_depth_max
    6. 量柱放大 > 前日 vol_expand_mult 倍

    Returns:
        (confidence: float, consolidation_detected: bool)
        其中 consolidation_detected 表示横盘不深(回调浅)
    """
    if not is_red.iloc[i]:
        return (0.0, False)

    cont_lo, cont_hi = cont_lookback
    pd_lo, pd_hi = pullback_days

    # ---- 条件2+3: 前 pd_len 日为绿砖（回调），当日为红砖（恢复） ----
    pullback_len = None
    for pd_len in range(pd_lo, pd_hi + 1):
        if i - pd_len < 0:
            continue
        if is_green.iloc[i - pd_len:i].all() and is_red.iloc[i]:
            pullback_len = pd_len
            break
    if pullback_len is None:
        return (0.0, False)

    # ---- 条件1: 回调前 5-10 日有红砖序列（上涨趋势） ----
    trend_start = max(0, i - pullback_len - cont_hi)
    trend_end = i - pullback_len  # exclusive
    window_len = trend_end - trend_start
    if window_len < cont_lo:
        return (0.0, False)

    red_count = is_red.iloc[trend_start:trend_end].sum()
    if red_count < max(2, window_len * 0.35):
        return (0.0, False)
    # 趋势末端（最后3个）至少1个红砖
    tail_start = max(trend_start, trend_end - 3)
    if is_red.iloc[tail_start:trend_end].sum() < 1:
        return (0.0, False)

    # ---- 条件4: 回调最低价 > 最近放量阳线收盘价（不破位） ----
    last_hvb_close = None
    for j in range(trend_end - 1, max(0, trend_start - 5), -1):
        if high_vol_bullish.iloc[j]:
            last_hvb_close = close.iloc[j]
            break

    if last_hvb_close is not None and last_hvb_close > 0:
        pullback_low = low.iloc[i - pullback_len:i].min()
        if pullback_low <= last_hvb_close:
            return (0.0, False)

    # ---- 条件5 [NEW]: 横盘不深 ----
    # 回调深度 = (趋势高点 - 回调最低) / 趋势高点
    trend_high = high.iloc[trend_start:trend_end].max()
    pullback_low_val = low.iloc[i - pullback_len:i].min()
    if trend_high > 0:
        depth = (trend_high - pullback_low_val) / trend_high
        pullback_shallow = depth <= pullback_depth_max
    else:
        pullback_shallow = False

    # 同时检查回调区是否有横盘特征（缩量窄幅）
    consol_in_pullback = False
    if i - pullback_len >= 0:
        consol_in_pullback = bool(
            consolidation.iloc[max(0, i - pullback_len):i].any()
        )

    # 横盘不深 = 回调浅 OR 回调区出现横盘
    consol_detected = pullback_shallow or consol_in_pullback
    if not consol_detected:
        return (0.0, False)

    # ---- 条件6: 量柱放大 > 前日 vol_expand_mult 倍 ----
    if volume.iloc[i] <= volume.iloc[i - 1] * vol_expand_mult:
        return (0.0, False)

    # ---- 置信度计算 ----
    confidence = 0.55

    red_ratio = red_count / window_len if window_len > 0 else 0
    if red_ratio > 0.60:
        confidence += 0.20
    elif red_ratio > 0.45:
        confidence += 0.10

    # pullback 越短越强
    if pullback_len == 1:
        confidence += 0.10

    # 回调越浅越加分
    if pullback_shallow:
        if depth < 0.04:
            confidence += 0.10
        elif depth < 0.06:
            confidence += 0.05

    vol_exp = volume.iloc[i] / max(volume.iloc[i - 1], 1)
    if vol_exp > 2.0:
        confidence += 0.15
    elif vol_exp > 1.5:
        confidence += 0.10

    return (min(1.0, confidence), consol_detected)


# =========================================================================
# Type 3: 横盘突破 (BRICK_BREAKOUT)
# =========================================================================

def _check_breakout(
    data: pd.DataFrame,
    brick: pd.Series,
    is_red: pd.Series,
    is_green: pd.Series,
    volume: pd.Series,
    ma20_vol: pd.Series,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    consolidation: pd.Series,
    i: int,
    consol_lookback: int,
    consol_amp_max: float,
    vol_mult: float,
) -> tuple:
    """检查 Type 3: 横盘突破 (BRICK_BREAKOUT)。

    条件：
    1. [NEW] detect_consolidation 确认横盘存在
    2. 当日红砖
    3. 突破横盘区间上沿 + 突破前高
    4. 成交量 > 20日均量 × vol_mult
    5. 横盘期间红砖数量 >= 绿砖数量（偏多）

    Returns:
        (confidence: float, consolidation_detected: bool)
    """
    if not is_red.iloc[i]:
        return (0.0, False)

    # ---- 条件1 [NEW]: 检测横盘 ----
    consol_detected = _recent_consolidation(consolidation, i, consol_lookback)
    if not consol_detected:
        return (0.0, False)

    # 横盘区间: [i - consol_lookback, i)
    cons_start = max(0, i - consol_lookback)

    # ---- 条件1b: 振幅验证 ----
    cons_high = high.iloc[cons_start:i].max()
    cons_low = low.iloc[cons_start:i].min()
    if cons_low <= 0:
        return (0.0, True)

    amplitude = (cons_high - cons_low) / cons_low
    if amplitude > consol_amp_max / 100.0:
        return (0.0, True)

    # ---- 条件2+3: 当日红砖突破横盘上沿 ----
    if close.iloc[i] <= cons_high:
        return (0.0, True)

    # 突破前高（横盘前20日）
    pre_cons_start = max(0, cons_start - 20)
    pre_high = high.iloc[pre_cons_start:cons_start].max()
    if pre_high > 0 and close.iloc[i] <= pre_high:
        return (0.0, True)

    # ---- 条件4: 成交量 > 20日均量 × vol_mult ----
    vol_ma = ma20_vol.iloc[i]
    if pd.isna(vol_ma) or volume.iloc[i] <= vol_ma * vol_mult:
        return (0.0, True)

    # ---- 条件5: 横盘期间红砖 >= 绿砖 ----
    red_count = is_red.iloc[cons_start:i].sum()
    green_count = is_green.iloc[cons_start:i].sum()
    if red_count < green_count:
        return (0.0, True)

    # ---- 置信度计算 ----
    confidence = 0.55

    # 振幅越小越好
    if amplitude < 0.08:
        confidence += 0.20
    elif amplitude < 0.12:
        confidence += 0.10

    # 红砖占比越高越好
    total = red_count + green_count
    if total > 0:
        red_pct = red_count / total
        if red_pct >= 0.60:
            confidence += 0.20
        elif red_pct >= 0.50:
            confidence += 0.10

    # 突破力度
    breakout_pct = (close.iloc[i] - cons_high) / cons_high
    if breakout_pct > 0.03:
        confidence += 0.05

    # 有横盘加分
    confidence += 0.05

    return (min(1.0, confidence), consol_detected)


# =========================================================================
# 主信号生成
# =========================================================================

def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    **params,
) -> pd.DataFrame:
    """生成砖型图3子类型策略信号（横盘检测增强版）。

    基于 brick_ultra.compute_brick_indicator 获取砖型值：
    - 红砖: indicator > 0 (多方)
    - 绿砖: indicator == 0 (空方/平衡)

    Args:
        data: 日线OHLCV DataFrame，需包含 open/high/low/close/volume
        symbol: 股票代码
        **params: 可覆盖参数
            - vol_mult_n_jump:        Type1成交量倍数，默认1.5
            - vol_mult_breakout:      Type3成交量倍数，默认1.3
            - bull_bear_tolerance:    黄线容差，默认0.03
            - consol_lookback:        横盘回看天数，默认5 (范围3-8)
            - consol_max_amplitude:   横盘最大振幅%，默认15.0
            - require_consolidation:  是否强制要求横盘检测，默认True
            - continuation_lookback:  上涨中继回看(low, high)，默认(5,10)
            - pullback_days:          回调天数(low, high)，默认(1,2)
            - vol_expand_mult:        量柱放大倍数，默认1.3
            - pullback_depth_max:     回调最大深度%，默认0.08 (横盘不深)

    Returns:
        DataFrame: columns=[symbol, date, signal, strategy, brick_type,
                            brick_value, consolidation_detected, confidence,
                            factor_snapshot]
        其中信号日 date 作为 index
    """
    if len(data) < 30:
        return pd.DataFrame(columns=[
            "symbol", "date", "signal", "strategy", "brick_type",
            "brick_value", "consolidation_detected", "confidence",
            "factor_snapshot",
        ])

    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)

    # ---- 参数提取 ----
    vol_mult_n_jump = params.get("vol_mult_n_jump", 1.5)
    vol_mult_breakout = params.get("vol_mult_breakout", 1.3)
    bull_bear_tolerance = params.get("bull_bear_tolerance", 0.03)
    consol_lookback = params.get("consol_lookback", 5)
    consol_max_amp = params.get("consol_max_amplitude", 15.0)
    require_consolidation = params.get("require_consolidation", True)
    cont_lookback = params.get("continuation_lookback", (5, 10))
    pullback_days = params.get("pullback_days", (1, 2))
    vol_expand_mult = params.get("vol_expand_mult", 1.3)
    pullback_depth_max = params.get("pullback_depth_max", 0.08)

    # ---- 核心指标 ----
    brick = compute_brick_indicator(data)
    ma20_vol = volume.rolling(20).mean()
    bull_bear_line = compute_bull_bear_line(close)

    # ---- [NEW] 横盘检测 ----
    consolidation = detect_consolidation(
        data, lookback=consol_lookback, max_amplitude=consol_max_amp,
    )

    # ---- 红/绿砖定义 ----
    is_red = brick > 0
    is_green = brick == 0

    # ---- 辅助: 放量阳线 ----
    is_bullish = close > open_
    is_high_vol = volume > ma20_vol * 1.5
    high_vol_bullish = is_bullish & is_high_vol

    # ---- 逐日扫描信号 ----
    results = []
    n = len(data)
    min_idx = max(30, cont_lookback[1] + pullback_days[1] + consol_lookback + 5)

    for i in range(min_idx, n):
        brick_val_i = brick.iloc[i]
        if brick_val_i <= 0:
            continue  # 信号日必须为红砖

        signals_today = []  # list of (brick_type, confidence, consol_detected)

        # -- Type 1: N型起跳 --
        c1, cd1 = _check_n_jump(
            data, brick, is_red, is_green, volume, ma20_vol,
            bull_bear_line, close, consolidation, i,
            bull_bear_tolerance, vol_mult_n_jump,
            consol_lookback, require_consolidation,
        )
        if c1 > 0:
            signals_today.append(("BRICK_N_JUMP", c1, cd1))

        # -- Type 2: 上涨中继 --
        c2, cd2 = _check_continuation(
            data, brick, is_red, is_green, volume, close, low, high,
            high_vol_bullish, consolidation, i,
            cont_lookback, pullback_days, vol_expand_mult,
            pullback_depth_max,
        )
        if c2 > 0:
            signals_today.append(("BRICK_CONTINUATION", c2, cd2))

        # -- Type 3: 横盘突破 --
        c3, cd3 = _check_breakout(
            data, brick, is_red, is_green, volume, ma20_vol,
            close, high, low, consolidation, i,
            consol_lookback, consol_max_amp, vol_mult_breakout,
        )
        if c3 > 0:
            signals_today.append(("BRICK_BREAKOUT", c3, cd3))

        # B2 增强: N_JUMP 与 CONTINUATION 同时触发时，N_JUMP 置信度提升
        has_n_jump = any(bt == "BRICK_N_JUMP" for bt, _, _ in signals_today)
        has_cont = any(bt == "BRICK_CONTINUATION" for bt, _, _ in signals_today)
        if has_n_jump and has_cont:
            signals_today = [
                (bt, min(1.0, conf * 1.2), cd)
                if bt == "BRICK_N_JUMP" else (bt, conf, cd)
                for bt, conf, cd in signals_today
            ]

        # ---- 记录信号 ----
        for brick_type, confidence, consol_detected in signals_today:
            results.append({
                "symbol": symbol,
                "date": data.index[i],
                "signal": 1,
                "strategy": "BRICK_THREE_TYPES",
                "brick_type": brick_type,
                "brick_value": round(float(brick_val_i), 2),
                "consolidation_detected": bool(consol_detected),
                "confidence": round(confidence, 2),
                "factor_snapshot": {
                    "brick_type": brick_type,
                    "brick_value": round(float(brick_val_i), 2),
                    "confidence": round(confidence, 2),
                    "consolidation_detected": bool(consol_detected),
                    "close": round(float(close.iloc[i]), 2),
                    "volume": float(volume.iloc[i]),
                    "vol_ma20": (
                        round(float(ma20_vol.iloc[i]), 0)
                        if pd.notna(ma20_vol.iloc[i]) else None
                    ),
                    "bull_bear": (
                        round(float(bull_bear_line.iloc[i]), 2)
                        if pd.notna(bull_bear_line.iloc[i]) else None
                    ),
                },
            })

    if not results:
        return pd.DataFrame(columns=[
            "symbol", "date", "signal", "strategy", "brick_type",
            "brick_value", "consolidation_detected", "confidence",
            "factor_snapshot",
        ])

    return pd.DataFrame(results).set_index("date").sort_index()
