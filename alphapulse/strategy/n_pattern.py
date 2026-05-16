"""N型结构上涨识别引擎 — 按照Zetteranc体系精确量化。

完整的N型结构 = 第一波上涨 → 回调 → 企稳 → 启动。

数学定义（规格书3.1节）：
- 第一波上涨 [T0, T1]: P(T1)/P(T0)-1 ∈ [5%, 30%]
- 回调 [T1, T2]: (P(T1)-P(T2))/(P(T1)-P(T0)) ∈ [30%, 62%]
- 企稳 [T2, T3]: 连续≥3日波动<2% + 缩量 + 阳线≥50% + 不创新低
- 启动 T3: 涨幅≥2% + 量≥5日均量×1.5 + 收盘>企稳最高价 + 收盘>前高×0.95
"""

import numpy as np
import pandas as pd
from typing import Optional


def _calc_kdj(high, low, close, n=9):
    """计算KDJ指标。"""
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = ((close - low_n) / (high_n - low_n).replace(0, np.nan)) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def check_red_green_volume(df_segment, ratio=1.2):
    """检查红柱（阳线）均量 >= 绿柱（阴线）均量 × ratio。规格书3.2.1"""
    red = df_segment[df_segment["close"] >= df_segment["open"]]
    green = df_segment[df_segment["close"] < df_segment["open"]]
    if len(green) == 0:
        return True
    if len(red) == 0:
        return False
    return red["volume"].mean() >= green["volume"].mean() * ratio


def check_volume_surge(df_before, ma_period=20, surge_ratio=1.8):
    """前期放量异动：前5日至少1日量>MA20×1.8。规格书3.2.2"""
    if len(df_before) < ma_period:
        return False
    vol_ma = df_before["volume"].rolling(ma_period).mean()
    ratios = df_before["volume"] / vol_ma
    return (ratios >= surge_ratio).any()


def check_volume_shrink(df_tail, ma_period=20, shrink_ratio=0.6):
    """缩量判断：最后3日至少有2日量<MA20×0.6。规格书3.2.3"""
    if len(df_tail) < 3:
        return False
    tail = df_tail.tail(3)
    vol_ma = tail["volume"].rolling(ma_period).mean() if len(tail) >= ma_period else pd.Series(tail["volume"].mean(), index=tail.index)
    if len(tail) < ma_period:
        vol_ma = pd.Series([df_tail["volume"].mean()] * len(tail), index=tail.index)
    else:
        vol_ma = df_tail["volume"].rolling(ma_period).mean().iloc[-3:]
        vol_ma.index = tail.index
    shrink_days = (tail["volume"] < vol_ma * shrink_ratio).sum()
    return shrink_days >= 2


def check_consolidation(df_consol, df_pullback, params):
    """企稳信号检查。规格书3.1.3"""
    n = params.get("consolidation_days", 3)
    if len(df_consol) < n:
        return False
    consol = df_consol.iloc[:n]

    # 连续N日收盘价波动<2%
    pct_range = (consol["close"].max() - consol["close"].min()) / consol["close"].mean()
    if pct_range > 0.02:
        return False

    # 缩量企稳：日均量 <= 企稳前5日均量 × 0.7
    if len(df_pullback) >= 5:
        pre_vol = df_pullback["volume"].tail(5).mean()
        consol_vol = consol["volume"].mean()
        if consol_vol > pre_vol * params.get("consolidation_vol_ratio", 0.7):
            return False

    # 阳线占比 >= 50%
    yang_ratio = (consol["close"] >= consol["open"]).mean()
    if yang_ratio < 0.5:
        return False

    # 不创新低
    pullback_low = df_pullback["low"].min()
    consol_low = consol["low"].min()
    if consol_low < pullback_low:
        return False

    return True


def check_breakout(breakout_day, df_consol, df_rise, params):
    """启动信号检查。规格书3.1.4"""
    if breakout_day is None:
        return False

    close = breakout_day["close"]
    open_p = breakout_day.get("open", close)
    volume = breakout_day["volume"]

    # 涨幅 >= 2%
    if hasattr(breakout_day, "name"):
        pass
    rise_pct = (close / open_p - 1) * 100
    if rise_pct < params.get("breakout_rise_pct", 2.0):
        return False

    # 量 >= 前5日均量 × 1.5
    if len(df_consol) >= 5:
        pre_vol = pd.concat([df_consol])["volume"].tail(5).mean()
        if volume < pre_vol * params.get("breakout_vol_ratio", 1.5):
            return False

    # 收盘 > 企稳期最高价
    if len(df_consol) > 0 and close <= df_consol["high"].max():
        return False

    # 收盘 > 第一波高点 × 0.95
    if close <= df_rise["high"].max() * 0.95:
        return False

    return True


def check_kdj_enhanced(df_daily, df_weekly=None, params=None):
    """KDJ复合条件。规格书3.3节"""
    if params is None:
        params = {}
    high, low, close = df_daily["high"], df_daily["low"], df_daily["close"]
    k, d, j = _calc_kdj(high, low, close)

    cur_k, cur_d, cur_j = float(k.iloc[-1]), float(d.iloc[-1]), float(j.iloc[-1])

    result = {
        "j_below": cur_j < params.get("j_threshold", 13),
        "k_below": cur_k < params.get("k_threshold", 30),
        "d_below": cur_d < params.get("d_threshold", 30),
        "j_value": round(cur_j, 2),
        "k_value": round(cur_k, 2),
        "d_value": round(cur_d, 2),
        "bullish_divergence": False,
        "weekly_resonance": False,
    }

    # 底背离：20日价格新低 但 J值未新低
    if params.get("enable_divergence", True):
        lookback = 20
        if len(df_daily) >= lookback:
            price_20_low = low.iloc[-lookback:].min()
            j_20_low = j.iloc[-lookback:].min()
            price_new_low = low.iloc[-1] <= price_20_low
            j_not_new_low = j.iloc[-1] > j_20_low
            result["bullish_divergence"] = bool(price_new_low and j_not_new_low)

    # 周线共振：周线J值 < 50
    if params.get("enable_multi_period", True) and df_weekly is not None and len(df_weekly) >= 9:
        wk, wd, wj = _calc_kdj(df_weekly["high"], df_weekly["low"], df_weekly["close"])
        result["weekly_resonance"] = bool(wj.iloc[-1] < 50)
        result["weekly_j"] = round(float(wj.iloc[-1]), 2)

    # 综合判断
    must_pass = result["j_below"] and result["k_below"] and result["d_below"]
    result["kdj_pass"] = must_pass
    result["kdj_score"] = (must_pass + result["bullish_divergence"] + result["weekly_resonance"]) / 3

    return result


def identify_n_pattern(df: pd.DataFrame, params: dict, df_weekly: Optional[pd.DataFrame] = None) -> list[dict]:
    """N型结构识别主函数。规格书3.4节完整算法。

    Args:
        df: 日线DataFrame（含date,open,high,low,close,volume，按日期升序）
        params: n_pattern参数字典
        df_weekly: 周线数据（可选，用于KDJ周期共振）

    Returns:
        list[dict]: 已识别的N型信号列表
    """
    pullback_max = params.get("pullback_max_days", 15)
    lookback = pullback_max + 30
    signals = []

    if len(df) < lookback:
        return signals

    # 确保索引为整数序
    df = df.reset_index(drop=True)

    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback : i + 1].copy()
        window = window.reset_index(drop=True)

        # ---- Step 1: 寻找第一波上涨 [T0, T1] ----
        found_rise = False
        for t1_pos in range(5, len(window) // 2):
            segment = window.iloc[: t1_pos + 1]
            rise_pct = (segment["close"].iloc[-1] / segment["close"].iloc[0] - 1) * 100

            if rise_pct < params.get("rise_min_pct", 5.0):
                continue
            if rise_pct > params.get("rise_max_pct", 30.0):
                break

            # Step 2: 红柱 > 绿柱
            if not check_red_green_volume(segment):
                continue

            found_rise = True
            t0_val, t1_val = segment["close"].iloc[0], segment["close"].iloc[-1]

            # ---- Step 3: 寻找回调终点 T2 ----
            remaining = window.iloc[t1_pos + 1 :]
            if len(remaining) < params.get("pullback_min_days", 3):
                break

            found_t2 = False
            for t2_pos in range(
                params.get("pullback_min_days", 3) - 1,
                min(params.get("pullback_max_days", 15), len(remaining)),
            ):
                pullback_seg = remaining.iloc[: t2_pos + 1]
                rise_abs = t1_val - t0_val
                if rise_abs <= 0:
                    break
                pullback_pct = ((t1_val - pullback_seg["close"].iloc[-1]) / rise_abs) * 100

                if not (params.get("pullback_min_pct", 30.0) <= pullback_pct <= params.get("pullback_max_pct", 62.0)):
                    continue

                found_t2 = True
                t2_val = pullback_seg["close"].iloc[-1]

                # Step 4: 缩量检查
                if not check_volume_shrink(pullback_seg):
                    continue

                # ---- Step 5: 企稳检查 ----
                post_pullback = remaining.iloc[t2_pos + 1 :]
                consol_days = params.get("consolidation_days", 3)
                if len(post_pullback) < consol_days + 1:
                    continue

                consol_seg = post_pullback.iloc[:consol_days]
                if not check_consolidation(consol_seg, pullback_seg, params):
                    continue

                # ---- Step 6: 启动信号 ----
                if len(post_pullback) <= consol_days:
                    continue
                breakout = post_pullback.iloc[consol_days]
                if not check_breakout(breakout, consol_seg, segment, params):
                    continue

                # ---- Step 7: KDJ复合条件 ----
                kdj_params = params.get("kdj", {})
                hist_up_to_breakout = df.iloc[: window.index[0] + t1_pos + 1 + t2_pos + 1 + consol_days + 1].copy()
                kdj_result = check_kdj_enhanced(hist_up_to_breakout, df_weekly, kdj_params)
                if not kdj_result["kdj_pass"]:
                    continue

                # ---- 全部通过，记录信号 ----
                signal_idx = window.index[0] + t1_pos + 1 + t2_pos + 1 + consol_days
                orig_date = df.iloc[signal_idx]["date"] if "date" in df.columns else pd.NaT

                signals.append({
                    "symbol": params.get("symbol", ""),
                    "date": orig_date,
                    "t0_date": segment.index[0],
                    "t1_date": segment.index[-1],
                    "t2_date": pullback_seg.index[-1],
                    "rise_pct": round(rise_pct, 2),
                    "pullback_pct": round(pullback_pct, 2),
                    "kdj_j": kdj_result["j_value"],
                    "kdj_score": round(kdj_result["kdj_score"], 3),
                    "bullish_divergence": kdj_result["bullish_divergence"],
                    "signal_type": "N_PATTERN",
                })
                break  # T2 found, stop inner loop

            if found_t2:
                break  # T1 processed, move to next i

    return signals
