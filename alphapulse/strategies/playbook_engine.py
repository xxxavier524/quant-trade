"""三大战法状态机引擎 — 按 docs/trading_system.md §2/§4 权威定义实现。

与"信号生成器"不同，本引擎模拟完整交易生命周期：
入场 → 等确认/换股 → 持有（依据持有规则）→ 卖出（空头信号体系），
输出逐笔交易（entry/exit/原因/收益），用于验证用户经验的整体绩效。

三战法：
  simulate_b1b2b3   战法一 B1→B2→B3 底部挖掘
  simulate_needle30 战法二 单针下三十（B1 前提 + 洗盘短线单针回收）
  simulate_brick    战法三 砖型图（N型起跳/上涨中继/横盘突破 三类型）

共享卖出体系（§4，全部向量化预计算）：
  止损（买入日最低-N价位）/ S1 / DD增强 / 破白线次日不收回 / 白线死叉黄线 / 放飞减仓点
模糊量参数化：price_ticks=3, b2_wait=5, escape_cost=3% 等，网格可扫。
"""

import numpy as np
import pandas as pd

from alphapulse.config.settings import SLIPPAGE_BUY, SLIPPAGE_SELL, COMMISSION_RATE
from alphapulse.factors import (
    b1_formula,
    volume_b1,
    brick_ultra,
    s1_sell_signal,
    dd_sell_signal,
)
from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line
from alphapulse.factors.zhixing_washout import compute_lines
from alphapulse.factors.four_brick_cycle import compute_brick_position

ROUND_TRIP_COST = SLIPPAGE_BUY + SLIPPAGE_SELL + 2 * COMMISSION_RATE


# ──────────────────────────── 共享预计算 ────────────────────────────

def _precompute(df: pd.DataFrame) -> dict:
    """所有战法共用的向量化指标。"""
    close = df["close"].astype(float)
    open_ = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    white = compute_short_trend(close)
    yellow = compute_bull_bear_line(close)
    dates = df["date"].astype(str).values if "date" in df.columns else df.index.astype(str).values

    try:
        s1 = s1_sell_signal.compute(df).fillna(False).astype(bool).values
    except Exception:
        s1 = np.zeros(len(df), bool)
    try:
        dd = dd_sell_signal.compute(df).fillna(False).astype(bool).values
    except Exception:
        dd = np.zeros(len(df), bool)
    dd2 = dd & np.roll(dd, 1)  # 连续两天DD=DD增强
    dd2[0] = False

    death_cross = ((white.shift(1) >= yellow.shift(1)) & (white < yellow)).fillna(False).values
    below_white = (close < white).fillna(False).values

    return {
        "close": close.values, "open": open_.values, "high": high.values,
        "low": low.values, "volume": volume.values,
        "white": white.values, "yellow": yellow.values, "dates": dates,
        "s1": s1, "dd2": dd2, "death_cross": death_cross,
        "below_white": below_white, "n": len(df),
    }


def _sell_engine(ctx: dict, entry_i: int, entry_price: float, stop_price: float,
                 max_hold: int = 60) -> tuple[int, str]:
    """共享卖出状态机：从 entry_i+1 起逐日检查空头信号体系。

    Returns:
        (exit_index, exit_reason)
    """
    n = ctx["n"]
    below_white_days = 0
    for i in range(entry_i + 1, min(entry_i + max_hold + 1, n)):
        # 1. 止损：跌破止损价（买入日最低-N价位）
        if ctx["low"][i] <= stop_price:
            return i, "stop_loss"
        # 2. S1 最强卖出
        if ctx["s1"][i]:
            return i, "S1"
        # 3. DD增强（连续两日DD）
        if ctx["dd2"][i]:
            return i, "DD2"
        # 4. 死叉（白下穿黄）
        if ctx["death_cross"][i]:
            return i, "death_cross"
        # 5. 跌破白线可等一天，次日收盘必须站回
        if ctx["below_white"][i]:
            below_white_days += 1
            if below_white_days >= 2:
                return i, "break_white"
        else:
            below_white_days = 0
    return min(entry_i + max_hold, n - 1), "max_hold"


def _make_trade(ctx: dict, symbol: str, playbook: str, sig_type: str,
                entry_i: int, exit_i: int, reason: str, stop_price: float) -> dict:
    entry_p = ctx["close"][entry_i]
    exit_p = ctx["close"][exit_i]
    gross = exit_p / entry_p - 1
    return {
        "symbol": symbol, "playbook": playbook, "signal_type": sig_type,
        "entry_date": ctx["dates"][entry_i], "exit_date": ctx["dates"][exit_i],
        "hold_days": int(exit_i - entry_i),
        "entry_price": round(float(entry_p), 3), "exit_price": round(float(exit_p), 3),
        "stop_price": round(float(stop_price), 3),
        "gross_return": round(float(gross), 4),
        "net_return": round(float(gross - ROUND_TRIP_COST), 4),
        "exit_reason": reason,
    }


def _stop_from_entry(ctx: dict, entry_i: int, price_ticks: int = 3) -> float:
    """止损价 = 买入日最低价 - N 个价位（A股价位=0.01元）。"""
    return ctx["low"][entry_i] - price_ticks * 0.01


# ──────────────────────────── 战法一 B1B2B3 ────────────────────────────

def simulate_b1b2b3(df: pd.DataFrame, symbol: str = "", b2_wait: int = 5,
                    b2_vol_mult: float = 1.85, price_ticks: int = 3,
                    max_hold: int = 60, **params) -> list[dict]:
    """B1买入→等B2（放量阳，b2_wait日内没来换股）→持有→空头体系卖出。

    B3（B2后缩量阳不破位）记录在交易标记中（确定性更高），不改变仓位。
    """
    if len(df) < 120:
        return []
    ctx = _precompute(df)

    b1 = b1_formula.compute(df, **{k: v for k, v in params.items()
                                   if k in {"pct_change_range", "amplitude_max",
                                            "j_threshold", "dif_threshold"}})
    try:
        vb1 = volume_b1.compute(df)
        b1 = (b1 | vb1).fillna(False)
    except Exception:
        b1 = b1.fillna(False)
    b1_idx = np.flatnonzero(b1.values)

    close, open_, vol = ctx["close"], ctx["open"], ctx["volume"]
    trades = []
    busy_until = -1
    for i in b1_idx:
        if i <= busy_until or i >= ctx["n"] - 2:
            continue
        stop = _stop_from_entry(ctx, i, price_ticks)
        # 等待B2：b2_wait日内的放量阳线（量>前日1.85倍且阳线）
        b2_i = None
        for j in range(i + 1, min(i + 1 + b2_wait, ctx["n"])):
            if ctx["low"][j] <= stop:           # 等待期触止损也退出
                trades.append(_make_trade(ctx, symbol, "B1B2B3", "B1_stop",
                                          i, j, "stop_loss_waiting_b2", stop))
                busy_until = j
                break
            if close[j] > open_[j] and vol[j] > b2_vol_mult * vol[j - 1]:
                b2_i = j
                break
        else:
            # 没等到B2 → 换股（以等待期末价退出）
            j = min(i + b2_wait, ctx["n"] - 1)
            trades.append(_make_trade(ctx, symbol, "B1B2B3", "B1_no_b2",
                                      i, j, "no_b2_rotate", stop))
            busy_until = j
            continue
        if b2_i is None:
            continue
        # B2确认后进入持有状态机；B3标记：B2后3日内缩量阳且低不破B2收盘
        has_b3 = False
        for k in range(b2_i + 1, min(b2_i + 4, ctx["n"])):
            if (close[k] > open_[k] and vol[k] < 0.7 * vol[k - 1]
                    and ctx["low"][k] >= close[b2_i]):
                has_b3 = True
                break
        exit_i, reason = _sell_engine(ctx, b2_i, close[b2_i], stop, max_hold)
        t = _make_trade(ctx, symbol, "B1B2B3", "B1B2B3" if has_b3 else "B1B2",
                        i, exit_i, reason, stop)
        trades.append(t)
        busy_until = exit_i
    return trades


# ──────────────────────────── 战法二 单针下三十 ────────────────────────────

def simulate_needle30(df: pd.DataFrame, symbol: str = "", b1_lookback: int = 60,
                      low_th: float = 30.0, high_th: float = 80.0,
                      price_ticks: int = 3, max_hold: int = 40, **params) -> list[dict]:
    """前提：b1_lookback 日内出现过B1（前期完美图形近似）；
    信号：洗盘短线短期线昨日下插≤30、今日回收≥80、当日阳线。"""
    if len(df) < 120:
        return []
    ctx = _precompute(df)

    b1 = b1_formula.compute(df).fillna(False)
    had_b1 = b1.rolling(b1_lookback, min_periods=1).max().astype(bool)

    short = compute_lines(df)["short"]
    needle = ((short.shift(1) <= low_th) & (short >= high_th)).fillna(False)
    yang = pd.Series(ctx["close"] > ctx["open"], index=df.index)

    sig = (needle & yang & had_b1).values
    trades = []
    busy_until = -1
    for i in np.flatnonzero(sig):
        if i <= busy_until or i >= ctx["n"] - 2:
            continue
        stop = _stop_from_entry(ctx, i, price_ticks)
        exit_i, reason = _sell_engine(ctx, i, ctx["close"][i], stop, max_hold)
        trades.append(_make_trade(ctx, symbol, "NEEDLE30", "needle30",
                                  i, exit_i, reason, stop))
        busy_until = exit_i
    return trades


# ──────────────────────────── 战法三 砖型图 ────────────────────────────

def simulate_brick(df: pd.DataFrame, symbol: str = "", near_yellow_pct: float = 0.05,
                   flat_days: int = 5, flat_amp: float = 0.15,
                   price_ticks: int = 3, max_hold: int = 30, **params) -> list[dict]:
    """三类型入场（§2 战法三）：
    1 N型起跳：砖型图超短信号（昨绿今红,红≥2/3绿）+放量阳+价格在黄线附近
    2 上涨中继：砖红、前1-2日绿砖，回调阴线未破前放量阳柱中位
    3 横盘突破：≥flat_days日横盘(振幅≤flat_amp) 当日放量突破前高
    卖出共享空头体系 + 第4砖减仓（此处第4砖直接离场，保守口径）。"""
    if len(df) < 120:
        return []
    ctx = _precompute(df)
    close, open_, high, low, vol = (ctx["close"], ctx["open"], ctx["high"],
                                    ctx["low"], ctx["volume"])

    brick_sig = brick_ultra.compute(df).fillna(False).values
    brick_pos = compute_brick_position(df).values
    yellow = ctx["yellow"]
    vol_ma5 = pd.Series(vol).rolling(5).mean().values

    yang = close > open_
    heavy = vol > vol_ma5

    # 类型1 N型起跳：砖型图信号+放量阳+黄线附近(±near_yellow_pct)
    near_yellow = np.abs(close / np.where(yellow > 0, yellow, np.nan) - 1) <= near_yellow_pct
    t1 = brick_sig & yang & heavy & np.nan_to_num(near_yellow, nan=False).astype(bool)

    # 类型2 上涨中继：今日红砖，前1-2日绿砖，且这1-2日阴线最低未破
    # 之前最近一根放量阳线柱的中位价
    s_close = pd.Series(close)
    red_today = brick_pos >= 1
    green_prev = (np.roll(brick_pos, 1) == 0) | (np.roll(brick_pos, 2) == 0)
    heavy_yang = yang & heavy
    hy_mid = np.where(heavy_yang, (open_ + close) / 2, np.nan)
    hy_mid = pd.Series(hy_mid).shift(1).ffill().values  # 最近放量阳柱中位
    pullback_ok = pd.Series(low).rolling(2).min().values >= np.nan_to_num(hy_mid, nan=0)
    t2 = red_today & green_prev & yang & pullback_ok & ~t1

    # 类型3 横盘突破：近flat_days日(不含今日)振幅≤flat_amp 且今日放量创新高
    hh = pd.Series(high).shift(1).rolling(flat_days).max().values
    ll = pd.Series(low).shift(1).rolling(flat_days).min().values
    flat = (hh / np.where(ll > 0, ll, np.nan) - 1) <= flat_amp
    breakout = (close > hh) & heavy & yang
    t3 = np.nan_to_num(flat, nan=False).astype(bool) & breakout & ~t1 & ~t2

    trades = []
    busy_until = -1
    for i in range(ctx["n"]):
        if not (t1[i] or t2[i] or t3[i]) or i <= busy_until or i >= ctx["n"] - 2:
            continue
        sig_type = "n_jump" if t1[i] else ("relay" if t2[i] else "flat_break")
        stop = _stop_from_entry(ctx, i, price_ticks)
        # 砖型图额外卖出：第4砖（先于共享引擎检查）
        exit_i, reason = _sell_engine(ctx, i, close[i], stop, max_hold)
        for j in range(i + 1, exit_i):
            if brick_pos[j] >= 4:
                exit_i, reason = j, "fourth_brick"
                break
        trades.append(_make_trade(ctx, symbol, "BRICK3", sig_type, i, exit_i, reason, stop))
        busy_until = exit_i
    return trades


# ──────────────────────────── 汇总统计 ────────────────────────────

PLAYBOOKS = {
    "B1B2B3": simulate_b1b2b3,
    "NEEDLE30": simulate_needle30,
    "BRICK3": simulate_brick,
}


def summarize_trades(trades: list[dict]) -> dict:
    """逐笔交易 → 绩效摘要（含按退出原因/信号类型拆分）。"""
    if not trades:
        return {"n_trades": 0}
    t = pd.DataFrame(trades)
    net = t["net_return"]
    wins = net[net > 0]
    losses = net[net <= 0]
    out = {
        "n_trades": int(len(t)),
        "n_symbols": int(t["symbol"].nunique()),
        "win_rate": round(float((net > 0).mean()), 4),
        "mean_net": round(float(net.mean()), 4),
        "median_net": round(float(net.median()), 4),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if len(losses) and losses.sum() != 0 else None,
        "avg_hold_days": round(float(t["hold_days"].mean()), 1),
        "by_exit_reason": {},
        "by_signal_type": {},
    }
    for reason, g in t.groupby("exit_reason"):
        out["by_exit_reason"][reason] = {
            "n": int(len(g)), "win_rate": round(float((g["net_return"] > 0).mean()), 3),
            "mean_net": round(float(g["net_return"].mean()), 4)}
    for st, g in t.groupby("signal_type"):
        out["by_signal_type"][st] = {
            "n": int(len(g)), "win_rate": round(float((g["net_return"] > 0).mean()), 3),
            "mean_net": round(float(g["net_return"].mean()), 4)}
    return out
