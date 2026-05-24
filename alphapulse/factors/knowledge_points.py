"""AlphaPulse-A 7大交易知识点因子模块。

每个因子独立函数，compute(data) -> 各自输出类型。
所有因子注册到 factor_registry.py（type="core"）。

知识点列表：
  1. 牵牛绳 (pull_rope)        — B1入场后未出S1+持续白线以上→继续持有
  2. 掉进碗里 (in_the_bowl)    — 股价白线以下黄线以上+B1信号增强
  3. 黄线交易价值 (yellow_line_value) — 首次回踩黄线不破+无S1+B1买点
  4. 击穿对手盘 (pierce_counterpart)  — 缩量跌破黄线+次日站稳检测
  5. 关键支撑价位 (key_support)       — N型低点/横盘下沿/SB1下沿
  6. 主力资金判断 (main_capital)      — 跌破黄线次数判断主力行为
  7. 5种出货方式 (distribution_patterns) — S1/放量长阴/阶梯下跌/双头/阴量>阳量
"""

import pandas as pd
import numpy as np

from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line
from alphapulse.factors.b1_formula import compute as b1_compute
from alphapulse.factors.s1_sell_signal import compute as s1_compute
from alphapulse.factors.n_struct import compute as n_struct_compute
from alphapulse.factors.key_k_abc import compute as key_k_abc_compute


# ============================================================================
# 辅助函数
# ============================================================================

def _rolling_count(condition: pd.Series, window: int) -> pd.Series:
    """向量化计算滚动窗口内True的次数。"""
    return condition.astype(int).rolling(window, min_periods=1).sum()


def _consecutive_count(condition: pd.Series) -> pd.Series:
    """向量化计算连续满足条件的天数。"""
    shifted = condition.shift(1)
    shifted.iloc[0] = shifted.iloc[0] if pd.notna(shifted.iloc[0]) else False
    shifted = shifted.infer_objects(copy=False)
    group = (condition != shifted).cumsum()
    consecutive = condition.astype(int).groupby(group).cumsum()
    return consecutive.where(condition, 0)


# ============================================================================
# 知识点1: 牵牛绳 (pull_rope)
# ============================================================================

def compute_pull_rope(data: pd.DataFrame) -> pd.Series:
    """牵牛绳：B1入场后未出现S1 + 持续在白线以上 → 继续持有。

    B1入场作为起点，只要之后没有出现S1卖出信号
    且收盘价持续在知行短期趋势线（白线）以上，就认为主力仍在，
    可以继续持有。适合在B1→B2过渡期中辅助判断。

    Args:
        data: OHLCV DataFrame，含 open/high/low/close/volume

    Returns:
        pd.Series[bool]: True=可持有（牛还在牵绳范围内），False=不可持有
    """
    close = data["close"]
    n = len(data)
    result = pd.Series(False, index=data.index)

    if n < 10:
        return result

    # 白线 (知行短期趋势线)
    white_line = compute_short_trend(close)

    # B1信号（入场起点）
    b1_signal = b1_compute(data)

    # S1卖出信号（出场判断）
    s1_signal = s1_compute(data)  # 0/1/2, >0表示有S1

    # 找到所有B1信号日
    b1_dates = data.index[b1_signal.fillna(False).astype(bool)]

    if len(b1_dates) == 0:
        return result

    # 对每个B1之后逐段标记
    for b1_dt in b1_dates:
        b1_pos = data.index.get_loc(b1_dt)
        # 从B1次日开始扫描
        for i in range(b1_pos + 1, n):
            # 如果出现了S1，停止
            if s1_signal.iloc[i] > 0:
                break
            # 如果跌破白线，也不可持有
            if close.iloc[i] < white_line.iloc[i]:
                result.iloc[i] = False
                continue
            # 在白线以上且无S1 → 可持有
            result.iloc[i] = True

    return result


# ============================================================================
# 知识点2: 掉进碗里 (in_the_bowl)
# ============================================================================

def compute_in_the_bowl(data: pd.DataFrame) -> pd.Series:
    """掉进碗里：股价在白线以下、黄线以上区间 + 出现B1信号 → 增强买点。

    碗底区域 = 白线(EMA(EMA(C,10),10))以下、黄线(4MA均值)以上。
    此时出现B1信号说明在回调到位后主力开始介入。
    这是一个位置优势增强因子。

    Args:
        data: OHLCV DataFrame，含 open/high/low/close/volume

    Returns:
        pd.Series[bool]: True=碗底B1信号（增强买点）
    """
    close = data["close"]
    n = len(data)
    result = pd.Series(False, index=data.index)

    if n < 120:
        return result

    # 白线 (短期趋势线)
    white_line = compute_short_trend(close)

    # 黄线 (多空线 = 4MA均值)
    yellow_line = compute_bull_bear_line(close)

    # B1信号
    b1_signal = b1_compute(data).fillna(False).astype(bool)

    # 碗底区域：白线以下、黄线以上
    in_bowl_zone = (close < white_line) & (close > yellow_line)

    # 碗底 + B1 = 掉进碗里
    result = in_bowl_zone & b1_signal

    return result.fillna(False).astype(bool)


# ============================================================================
# 知识点3: 黄线交易价值 (yellow_line_value)
# ============================================================================

def compute_yellow_line_value(data: pd.DataFrame) -> pd.Series:
    """黄线交易价值：首次回踩黄线不破 + 无S1信号 + 出现B1买点。

    回踩黄线是主力护盘的核心信号：
    - 价格接近黄线（close/黄线在0.97-1.03区间）
    - 前一日收盘低于黄线（回踩动作）
    - 当日收盘回到黄线以上（不破确认）
    - 无S1信号
    - 出现B1买点
    综合输出0-1的连续分数。

    Args:
        data: OHLCV DataFrame，含 open/high/low/close/volume

    Returns:
        pd.Series[float]: 0-1连续分数（越高=黄线支撑越有效）
    """
    close = data["close"]
    n = len(data)
    result = pd.Series(0.0, index=data.index)

    if n < 120:
        return result

    # 黄线 (多空线)
    yellow_line = compute_bull_bear_line(close)

    # S1信号
    s1_signal = s1_compute(data)
    no_s1 = s1_signal == 0

    # B1信号
    b1_signal = b1_compute(data).fillna(False).astype(bool)

    # 条件1: 价格接近黄线（±3%范围内）
    dist_to_yellow = (close - yellow_line) / yellow_line.replace(0, np.nan)
    near_yellow = dist_to_yellow.abs() < 0.03

    # 条件2: 前一日收盘低于黄线（回踩）
    prev_below = close.shift(1) < yellow_line.shift(1)

    # 条件3: 当日收盘回到黄线以上（不破确认）
    back_above = close > yellow_line

    # 条件4: 首次回踩（前5日未出现回踩不破信号）
    prior_bounce_in_5d = (
        (prev_below & back_above & near_yellow)
        .shift(1).rolling(5, min_periods=1).sum().fillna(0)
    ) == 0

    # 综合评分
    score = 0.0
    score += 0.3 * near_yellow.astype(float)
    score += 0.2 * (prev_below & back_above).astype(float)
    score += 0.2 * no_s1.astype(float)
    score += 0.2 * b1_signal.astype(float)
    score += 0.1 * prior_bounce_in_5d.astype(float)

    # 只在有明显回踩信号时输出
    has_bounce_signal = near_yellow & prev_below & back_above & no_s1
    result = score.where(has_bounce_signal, 0.0)

    return result.round(2)


# ============================================================================
# 知识点4: 击穿对手盘 (pierce_counterpart)
# ============================================================================

def compute_pierce_counterpart(data: pd.DataFrame) -> pd.Series:
    """击穿对手盘：缩量跌破黄线 → 观察次日是否站稳。

    状态编码：
      0 = 无事件
      1 = 击穿（缩量跌破黄线）
      2 = 击穿+次日恢复（站稳黄线以上）

    击穿条件：当日收盘 < 黄线 AND 成交量 < 20日均量×0.8（缩量跌破）
    恢复条件：击穿次日收盘 > 黄线（站稳）

    Args:
        data: OHLCV DataFrame，含 open/high/low/close/volume

    Returns:
        pd.Series[int]: 0=无事件, 1=击穿, 2=击穿+恢复
    """
    close = data["close"]
    volume = data["volume"]
    n = len(data)
    result = pd.Series(0, index=data.index, dtype=int)

    if n < 120:
        return result

    # 黄线 (多空线)
    yellow_line = compute_bull_bear_line(close)

    # 20日均量
    vol_ma20 = volume.rolling(20).mean()

    # 击穿条件：收盘 < 黄线 AND 缩量 (vol < 20ma * 0.8)
    below_yellow = close < yellow_line
    vol_shrink = volume < (vol_ma20 * 0.8)
    pierce = below_yellow & vol_shrink

    # 标记击穿日
    result[pierce] = 1

    # 检测恢复：击穿次日收盘 > 黄线
    next_close = close.shift(-1)
    next_yellow = yellow_line.shift(-1)
    pierce_next = pierce.shift(-1)  # 前一日是击穿日
    pierce_next_nona = pierce_next.copy()
    pierce_next_nona[pierce_next_nona.isna()] = False
    pierce_next_nona = pierce_next_nona.infer_objects(copy=False)
    recovered_yesterday = pierce_next_nona & (close > yellow_line)
    result[recovered_yesterday] = 2

    return result


# ============================================================================
# 知识点5: 关键支撑价位 (key_support)
# ============================================================================

def compute_key_support(data: pd.DataFrame) -> pd.DataFrame:
    """关键支撑价位：前N型低点-3价位、横盘区间下沿、SB1下沿。

    三个支撑位：
      n_pattern_support: 最近N型结构A点低点 - 3个价位(0.03)
      range_support: 近20日横盘区间下沿（min(low)）
      sb1_support: 最近key_k_abc的B节点 - 3个价位(0.03)

    Args:
        data: OHLCV DataFrame，含 open/high/low/close

    Returns:
        pd.DataFrame: [n_pattern_support, range_support, sb1_support]
                      每列float，无支撑时为NaN
    """
    close = data["close"]
    low = data["low"]
    high = data["high"]
    n = len(data)
    idx = data.index

    result = pd.DataFrame({
        "n_pattern_support": np.nan,
        "range_support": np.nan,
        "sb1_support": np.nan,
    }, index=idx, dtype=float)

    if n < 20:
        return result

    # --- 支撑1: N型结构A点低点 - 3价位 ---
    ns_labels = n_struct_compute(data)
    # 找到所有A点位置
    a_mask = ns_labels == "A"
    if a_mask.any():
        a_prices = low.where(a_mask, np.nan)
        # 前向填充：每根bar知道最近一个A点的价格
        last_a_price = a_prices.ffill()
        result["n_pattern_support"] = (last_a_price - 0.03).round(2)

    # --- 支撑2: 近20日横盘区间下沿 ---
    range_low_20 = low.rolling(20).min()
    result["range_support"] = range_low_20.round(2)

    # --- 支撑3: SB1下沿 (key_k_abc B节点 - 3价位) ---
    abc_labels = key_k_abc_compute(data)
    # key_k_abc 输出: 0=无, 1=A, 2=B, 3=C
    b_mask = abc_labels == 2
    if b_mask.any():
        b_low = low.where(b_mask, np.nan)
        last_b = b_low.ffill()
        result["sb1_support"] = (last_b - 0.03).round(2)

    return result


# ============================================================================
# 知识点6: 主力资金判断 (main_capital)
# ============================================================================

def compute_main_capital(data: pd.DataFrame) -> pd.Series:
    """主力资金判断：通过跌破黄线的频率和方式判断主力行为。

    判断逻辑：
      - 强(2): 近60日内持续回踩黄线不破（破<2次 且 每次破后3日内收回）
      - 不在(1): 放量加速跌破黄线（近20日有放量跌穿+量>20日均量×1.5）
      - 弱(0): 近60日跌破黄线次数≥3次

    Args:
        data: OHLCV DataFrame，含 open/high/low/close/volume

    Returns:
        pd.Series[int]: 0=弱(主力不在), 1=主力不在(放量跌破), 2=强(主力仍在护盘)
    """
    close = data["close"]
    volume = data["volume"]
    n = len(data)
    result = pd.Series(0, index=data.index, dtype=int)

    if n < 60:
        return result

    # 黄线 (多空线)
    yellow_line = compute_bull_bear_line(close)

    # 跌破黄线事件
    break_below = close < yellow_line

    # 收回黄线事件 (从跌破到收回)
    # 找到每次跌破后3日内是否收回
    recovered_after_break = pd.Series(False, index=data.index)
    for i in range(1, n):
        if break_below.iloc[i - 1] and not break_below.iloc[i]:
            # 前一日跌破，当日收回
            recovered_after_break.iloc[i] = True

    # 近60日跌破次数
    break_count_60 = _rolling_count(break_below, 60)

    # 近60日收回次数
    recover_count_60 = _rolling_count(recovered_after_break, 60)

    # 持续回踩不破：破<2次 且 破后3日内基本收回(收回>=破*0.8)
    strong_mask = (break_count_60 < 2) | (
        (break_count_60 >= 2) & (recover_count_60 >= break_count_60 * 0.8)
    )
    result[strong_mask] = 2

    # 放量加速跌破：近20日有放量跌穿(量>20日均量×1.5)
    vol_ma20 = volume.rolling(20).mean()
    heavy_break = break_below & (volume > vol_ma20 * 1.5)
    heavy_break_20 = heavy_break.rolling(20, min_periods=1).sum() > 0

    absent_mask = heavy_break_20 & ~strong_mask
    # 不在: 覆盖弱(0)但保留强(2)
    result = result.where(strong_mask, 1)
    result = result.where(~absent_mask, 1)  # absent & strong already handled

    # 重新整理：强(2) > 不在(1) > 弱(0)
    # 不在优先但不强于强
    result[absent_mask] = 1
    result[strong_mask] = 2

    # 默认弱(0)保持不变（break_count_60 >= 3 and not strong and not heavy_break）

    return result


# ============================================================================
# 知识点7: 5种出货方式 (distribution_patterns)
# ============================================================================

def compute_distribution_patterns(data: pd.DataFrame) -> pd.DataFrame:
    """5种出货方式：识别主力高位出货的5种经典形态。

    方式1 (type1): S1卖出信号（复用s1_sell_signal）
    方式2 (type2): 加速上涨后次高点放量长阴
    方式3 (type3): 新高后阶梯放量下跌
    方式4 (type4): 双头（二次不破前高+顶部放量）
    方式5 (type5): 顶部阴量>阳量（大盘股特征）

    Args:
        data: OHLCV DataFrame，含 open/high/low/close/volume

    Returns:
        pd.DataFrame: [type1~type5] 5列布尔值
    """
    close = data["close"]
    open_ = data["open"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]
    n = len(data)
    idx = data.index

    result = pd.DataFrame({
        "type1": False,
        "type2": False,
        "type3": False,
        "type4": False,
        "type5": False,
    }, index=idx)

    if n < 60:
        return result

    # ================================================================
    # 方式1: S1卖出信号
    # ================================================================
    s1 = s1_compute(data)
    result["type1"] = s1 > 0

    # ================================================================
    # 方式2: 加速上涨后次高点放量长阴
    #   条件：前5日涨幅>15%（加速上涨）→ 当日阴线实体>3% + 放量>20日均量×1.5
    # ================================================================
    ret_5d = close.pct_change(5)
    accelerated = ret_5d > 0.15

    is_yinxian = close < open_
    body_pct = (open_ - close) / open_.replace(0, np.nan)  # 阴线实体%
    long_yin = is_yinxian & (body_pct > 0.03)

    vol_ma20 = volume.rolling(20).mean()
    heavy_vol = volume > vol_ma20 * 1.5

    result["type2"] = accelerated & long_yin & heavy_vol

    # ================================================================
    # 方式3: 新高后阶梯放量下跌
    #   条件：前10日创60日新高 → 此后3日连续放量(量递增)+下跌 → 阶梯出货
    # ================================================================
    high_60d = high.rolling(60).max()
    new_high_10d = (high == high_60d) & (high > high_60d.shift(1))
    had_new_high = new_high_10d.rolling(10, min_periods=1).max().fillna(0).astype(bool)

    # 放量下跌日：阴线 + 量>前日vol
    vol_up_day = close < open_
    vol_increasing = volume > volume.shift(1)
    heavy_down = vol_up_day & vol_increasing

    # 连续3日递增放量下跌
    consecutive_heavy = _consecutive_count(heavy_down) >= 3

    result["type3"] = had_new_high & consecutive_heavy

    # ================================================================
    # 方式4: 双头（二次不破前高+顶部放量）
    #   条件：前20日有局部高点 → 此后反弹但未破该高点(差<3%) → 顶部放量(>20均量×1.3)
    # ================================================================
    high_20d_shift = high.shift(1).rolling(20).max()
    near_prev_high = (close / high_20d_shift.replace(0, np.nan) - 1).abs() < 0.03
    # 确认未突破前高
    not_break = close < high_20d_shift

    top_vol = volume > vol_ma20 * 1.3

    result["type4"] = near_prev_high & not_break & top_vol

    # ================================================================
    # 方式5: 顶部阴量>阳量（大盘股特征）
    #   条件：近10日阴线成交量均值 > 近10日阳线成交量均值 × 1.2
    #   且价格在近60日高位（top 20%区间）
    # ================================================================
    is_yang = close > open_

    yin_vol = volume.where(is_yinxian, 0.0)
    yang_vol = volume.where(is_yang, 0.0)

    yin_vol_avg_10 = yin_vol.rolling(10, min_periods=5).mean()
    yang_vol_avg_10 = yang_vol.rolling(10, min_periods=5).mean()

    yin_gt_yang = yin_vol_avg_10 > (yang_vol_avg_10 * 1.2)

    # 价格在高位：近60日top 20%
    range_high_60 = high.rolling(60).max()
    range_low_60 = low.rolling(60).min()
    price_position = (close - range_low_60) / (range_high_60 - range_low_60).replace(0, np.nan)
    in_high_zone = price_position > 0.80

    result["type5"] = yin_gt_yang & in_high_zone

    return result.fillna(False).astype(bool)


# ============================================================================
# 统一compute入口（兼容 factor_registry）
# ============================================================================

_COMPUTE_MAP = {
    "PULL_ROPE": compute_pull_rope,
    "IN_THE_BOWL": compute_in_the_bowl,
    "YELLOW_LINE_VALUE": compute_yellow_line_value,
    "PIERCE_COUNTERPART": compute_pierce_counterpart,
    "KEY_SUPPORT": compute_key_support,
    "MAIN_CAPITAL": compute_main_capital,
    "DISTRIBUTION_PATTERNS": compute_distribution_patterns,
}


def compute(data: pd.DataFrame, factor_name: str = "", **params) -> pd.Series | pd.DataFrame:
    """统一compute入口，通过factor_name路由到各知识点函数。

    Args:
        data: OHLCV DataFrame
        factor_name: 知识点名称（如 "PULL_ROPE"）
        **params: 预留参数传递

    Returns:
        各知识点对应的输出类型
    """
    if factor_name not in _COMPUTE_MAP:
        available = list(_COMPUTE_MAP.keys())
        raise ValueError(f"未知知识点: {factor_name}。可用: {available}")

    return _COMPUTE_MAP[factor_name](data)
