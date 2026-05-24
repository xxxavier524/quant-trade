"""AlphaPulse-A 砖型图3子类型策略。

基于 brick_ultra.compute_brick_indicator 获取砖型值：
- 红砖: indicator > 0 (多方力量占优)
- 绿砖: indicator == 0 (多空平衡/空方)

三个子类型信号：
1. BRICK_N_JUMP:     N型起跳
2. BRICK_CONTINUATION: 上涨中继
3. BRICK_BREAKOUT:   横盘突破
"""

import pandas as pd
import numpy as np
from alphapulse.factors.brick_ultra import compute_brick_indicator
from alphapulse.factors.zhixing_trend import compute_bull_bear_line


def _find_green_to_red_transition(is_green: pd.Series, is_red: pd.Series, end: int, lookback: int = 5) -> int:
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


def _check_n_jump(
    data: pd.DataFrame,
    brick: pd.Series,
    is_red: pd.Series,
    is_green: pd.Series,
    volume: pd.Series,
    ma20_vol: pd.Series,
    bull_bear_line: pd.Series,
    close: pd.Series,
    i: int,
    tolerance: float,
    vol_mult: float,
) -> float:
    """检查 Type 1: N型起跳 (BRICK_N_JUMP)。

    条件：
    1. 前5日有绿→红转换
    2. 红砖值 > 前绿砖绝对值 × 2/3 (indicator>0 自然满足)
    3. 成交量 > 20日均量 × 1.5
    4. 收盘价在黄线±3%

    Returns: confidence 0.0-1.0 (0=无信号)
    """
    if not is_red.iloc[i]:
        return 0.0

    # 条件1: 前5日有绿→红转换
    transition_idx = _find_green_to_red_transition(is_green, is_red, i, lookback=5)
    if transition_idx < 0:
        return 0.0

    # 条件2: 红砖值 > 前绿砖绝对值 × 2/3
    # 绿砖 indicator==0，故 abs(0)*2/3=0，红砖 indicator>0 恒成立
    # 额外附加：当前红砖值 > 转换前最后一个红砖值 × 2/3 (N型两腿力度比)
    prev_red_val = 0.0
    for j in range(transition_idx - 1, max(0, transition_idx - 20), -1):
        if is_red.iloc[j]:
            prev_red_val = brick.iloc[j]
            break
    if prev_red_val > 0 and brick.iloc[i] <= prev_red_val * 2 / 3:
        return 0.0

    # 条件3: 成交量 > 20日均量 × 1.5
    vol_ma = ma20_vol.iloc[i]
    if pd.isna(vol_ma) or volume.iloc[i] <= vol_ma * vol_mult:
        return 0.0

    # 条件4: 收盘价在黄线±3%
    bb = bull_bear_line.iloc[i]
    if pd.isna(bb) or bb <= 0:
        return 0.0
    if abs(close.iloc[i] - bb) / bb > tolerance:
        return 0.0

    # 置信度计算
    confidence = 0.60
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

    return min(1.0, confidence)


def _check_continuation(
    data: pd.DataFrame,
    brick: pd.Series,
    is_red: pd.Series,
    is_green: pd.Series,
    volume: pd.Series,
    close: pd.Series,
    low: pd.Series,
    high_vol_bullish: pd.Series,
    i: int,
    cont_lookback: tuple,
    pullback_days: tuple,
    vol_expand_mult: float,
) -> float:
    """检查 Type 2: 上涨中继 (BRICK_CONTINUATION)。

    条件：
    1. 前5-10日有红砖序列（上涨趋势）
    2. 前1-2日为绿砖（短暂回调）
    3. 当日为红砖（恢复上涨）
    4. 回调最低价 > 最近放量阳线收盘价
    5. 量柱放大 > 前日1.3倍

    Returns: confidence 0.0-1.0 (0=无信号)
    """
    if not is_red.iloc[i]:
        return 0.0

    cont_lo, cont_hi = cont_lookback
    pd_lo, pd_hi = pullback_days

    # 条件2+3: 前 pd_len 日为绿砖（回调），当日为红砖（恢复）
    pullback_len = None
    for pd_len in range(pd_lo, pd_hi + 1):
        if i - pd_len < 0:
            continue
        if is_green.iloc[i - pd_len:i].all() and is_red.iloc[i]:
            pullback_len = pd_len
            break
    if pullback_len is None:
        return 0.0

    # 条件1: 回调前 5-10 日有红砖序列（上涨趋势）
    # 即 [i-pd_len-hi, i-pd_len) 区间内红砖比例足够
    trend_start = max(0, i - pullback_len - cont_hi)
    trend_end = i - pullback_len  # exclusive
    window_len = trend_end - trend_start
    if window_len < cont_lo:
        return 0.0

    red_count = is_red.iloc[trend_start:trend_end].sum()
    # 至少有一定比例的红砖 + 最近一段为红砖（趋势延续）
    if red_count < max(2, window_len * 0.35):
        return 0.0
    # 趋势末端（最后3个）至少1个红砖
    tail_start = max(trend_start, trend_end - 3)
    if is_red.iloc[tail_start:trend_end].sum() < 1:
        return 0.0

    # 条件4: 回调最低价 > 最近放量阳线收盘价
    # 找回调前的最近放量阳线
    last_hvb_close = None
    for j in range(trend_end - 1, max(0, trend_start - 5), -1):
        if high_vol_bullish.iloc[j]:
            last_hvb_close = close.iloc[j]
            break

    if last_hvb_close is not None and last_hvb_close > 0:
        pullback_low = low.iloc[i - pullback_len:i].min()
        if pullback_low <= last_hvb_close:
            return 0.0

    # 条件5: 量柱放大 > 前日 1.3 倍
    if volume.iloc[i] <= volume.iloc[i - 1] * vol_expand_mult:
        return 0.0

    # 置信度计算
    confidence = 0.55

    red_ratio = red_count / window_len if window_len > 0 else 0
    if red_ratio > 0.60:
        confidence += 0.20
    elif red_ratio > 0.45:
        confidence += 0.10

    # pullback 越短越强
    if pullback_len == 1:
        confidence += 0.10

    vol_exp = volume.iloc[i] / max(volume.iloc[i - 1], 1)
    if vol_exp > 2.0:
        confidence += 0.15
    elif vol_exp > 1.5:
        confidence += 0.10

    return min(1.0, confidence)


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
    i: int,
    consol_days: tuple,
    consol_amp_max: float,
    vol_mult: float,
) -> float:
    """检查 Type 3: 横盘突破 (BRICK_BREAKOUT)。

    条件：
    1. 近3-5日横盘振幅<15%
    2. 当日红砖突破横盘上沿 + 突破前高
    3. 成交量 > 20日均量×1.3
    4. 横盘期间红砖数量 >= 绿砖数量（偏多）

    Returns: confidence 0.0-1.0 (0=无信号)
    """
    if not is_red.iloc[i]:
        return 0.0

    cl, ch = consol_days

    for cd_len in range(cl, ch + 1):
        if i - cd_len < 1:
            continue

        cons_start = i - cd_len
        cons_end = i  # 横盘区间 [cons_start, cons_end)，i 为突破日

        # 条件1: 横盘振幅 < consol_amp_max
        cons_high = high.iloc[cons_start:cons_end].max()
        cons_low = low.iloc[cons_start:cons_end].min()
        cons_close_avg = close.iloc[cons_start:cons_end].mean()

        if cons_close_avg <= 0:
            continue

        amplitude = (cons_high - cons_low) / cons_close_avg
        if amplitude > consol_amp_max:
            continue

        # 条件2: 突破横盘上沿 + 突破前高
        if close.iloc[i] <= cons_high:
            continue

        # 横盘前高点（回看20日）
        pre_cons_start = max(0, cons_start - 20)
        pre_high = high.iloc[pre_cons_start:cons_start].max()
        if pre_high > 0 and close.iloc[i] <= pre_high:
            continue

        # 条件3: 成交量 > 20日均量 × 1.3
        vol_ma = ma20_vol.iloc[i]
        if pd.isna(vol_ma) or volume.iloc[i] <= vol_ma * vol_mult:
            continue

        # 条件4: 横盘期间红砖数量 >= 绿砖数量
        red_count = is_red.iloc[cons_start:cons_end].sum()
        green_count = is_green.iloc[cons_start:cons_end].sum()
        if red_count < green_count:
            continue

        # 置信度计算
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

        return min(1.0, confidence)

    return 0.0


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    **params,
) -> pd.DataFrame:
    """生成砖型图3子类型策略信号。

    基于 brick_ultra.compute_brick_indicator 获取砖型值：
    - 红砖: indicator > 0 (多方)
    - 绿砖: indicator == 0 (空方/平衡)

    Args:
        data: 日线OHLCV DataFrame，需包含 open/high/low/close/volume
        symbol: 股票代码
        **params: 可覆盖参数
            - vol_mult_n_jump:      Type1成交量倍数，默认1.5
            - vol_mult_breakout:    Type3成交量倍数，默认1.3
            - bull_bear_tolerance:  黄线容差，默认0.03
            - consolidation_days:   横盘天数(low, high)，默认(3,5)
            - consolidation_amplitude: 振幅上限，默认0.15
            - continuation_lookback: 上涨中继回看(low, high)，默认(5,10)
            - pullback_days:         回调天数(low, high)，默认(1,2)
            - vol_expand_mult:       量柱放大倍数，默认1.3

    Returns:
        DataFrame: columns=[symbol, date, signal, strategy, brick_type,
                            brick_value, confidence, factor_snapshot]
        其中信号日 date 作为 index
    """
    if len(data) < 30:
        return pd.DataFrame(columns=[
            "symbol", "date", "signal", "strategy", "brick_type",
            "brick_value", "confidence", "factor_snapshot",
        ])

    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)

    # 参数提取
    vol_mult_n_jump = params.get("vol_mult_n_jump", 1.5)
    vol_mult_breakout = params.get("vol_mult_breakout", 1.3)
    bull_bear_tolerance = params.get("bull_bear_tolerance", 0.03)
    consol_days = params.get("consolidation_days", (3, 5))
    consol_amp_max = params.get("consolidation_amplitude", 0.15)
    cont_lookback = params.get("continuation_lookback", (5, 10))
    pullback_days = params.get("pullback_days", (1, 2))
    vol_expand_mult = params.get("vol_expand_mult", 1.3)

    # 核心指标
    brick = compute_brick_indicator(data)
    ma20_vol = volume.rolling(20).mean()
    bull_bear_line = compute_bull_bear_line(close)

    # 红/绿砖定义
    is_red = brick > 0
    is_green = brick == 0

    # 辅助: 放量阳线 (成交量 > 1.5×20日均量 且 收阳)
    is_bullish = close > open_
    is_high_vol = volume > ma20_vol * 1.5
    high_vol_bullish = is_bullish & is_high_vol

    results = []
    n = len(data)
    min_idx = max(25, cont_lookback[1] + pullback_days[1] + 5)

    for i in range(min_idx, n):
        brick_val_i = brick.iloc[i]
        if brick_val_i <= 0:
            continue  # 信号日必须为红砖

        signals_today = []

        # -- Type 1: N型起跳 --
        c1 = _check_n_jump(
            data, brick, is_red, is_green, volume, ma20_vol,
            bull_bear_line, close, i,
            bull_bear_tolerance, vol_mult_n_jump,
        )
        if c1 > 0:
            signals_today.append(("BRICK_N_JUMP", c1))

        # -- Type 2: 上涨中继 --
        c2 = _check_continuation(
            data, brick, is_red, is_green, volume, close, low,
            high_vol_bullish, i, cont_lookback, pullback_days, vol_expand_mult,
        )
        if c2 > 0:
            signals_today.append(("BRICK_CONTINUATION", c2))

        # -- Type 3: 横盘突破 --
        c3 = _check_breakout(
            data, brick, is_red, is_green, volume, ma20_vol,
            close, high, low, i, consol_days, consol_amp_max, vol_mult_breakout,
        )
        if c3 > 0:
            signals_today.append(("BRICK_BREAKOUT", c3))

        # B2 增强: N_JUMP 与 CONTINUATION 同时触发时，N_JUMP 置信度提升
        has_n_jump = any(bt == "BRICK_N_JUMP" for bt, _ in signals_today)
        has_cont = any(bt == "BRICK_CONTINUATION" for bt, _ in signals_today)
        if has_n_jump and has_cont:
            signals_today = [
                (bt, min(1.0, conf * 1.2)) if bt == "BRICK_N_JUMP" else (bt, conf)
                for bt, conf in signals_today
            ]

        for brick_type, confidence in signals_today:
            results.append({
                "symbol": symbol,
                "date": data.index[i],
                "signal": 1,
                "strategy": "BRICK_THREE_TYPES",
                "brick_type": brick_type,
                "brick_value": round(float(brick_val_i), 2),
                "confidence": round(confidence, 2),
                "factor_snapshot": {
                    "brick_type": brick_type,
                    "brick_value": round(float(brick_val_i), 2),
                    "confidence": round(confidence, 2),
                    "close": round(float(close.iloc[i]), 2),
                    "volume": float(volume.iloc[i]),
                    "vol_ma20": round(float(ma20_vol.iloc[i]), 0) if pd.notna(ma20_vol.iloc[i]) else None,
                    "bull_bear": round(float(bull_bear_line.iloc[i]), 2) if pd.notna(bull_bear_line.iloc[i]) else None,
                },
            })

    if not results:
        return pd.DataFrame(columns=[
            "symbol", "date", "signal", "strategy", "brick_type",
            "brick_value", "confidence", "factor_snapshot",
        ])

    return pd.DataFrame(results).set_index("date").sort_index()
