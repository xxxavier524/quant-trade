"""战法序列状态（向量化，agent 与回测共源）。

回测发现（reports/agent_team_backtest.md 2026-07-02）：B1 信号日直接买入无边际优势
（3日>5% 命中 12.7% vs 基线 11.8%），与 Phase 3 结论一致——优势在 B2 放量确认。
⚠️ v5（2026-08-02）：原"B1→B2 72.4% / B1→B2→B3 94.7%"是 playbook 交易模拟的
**条件胜率**（只统计走完序列的交易，天然已先涨），与实盘追踪库 19.7% 不可比，
已随交易引擎一并下线；当前唯一主口径 = alphapulse.screening 的选股机会命中率。

因此 pattern 角色按序列状态定强弱：
- B2确认：B1 后 b2_wait 日内出现放量阳（vol > 1.85×前日 且 收>开），且未破 B1 日低点 → 强多
- B1候B2：B1 触发但 B2 未现 → 中性（无统计优势，等确认）
- 单针探底：近 recent 日内单针信号 → 弱多
- 无明确战法态
"""

from __future__ import annotations

import numpy as np
import pandas as pd

B2_VOL_MULT = 1.85     # B2 放量倍数（序列定义与 b1_b2_b3_strategy 一致）
B2_WAIT = 8            # 2026-07-04 网格调优：每持有日收益 w=8 见顶（best_params 同步）
NEEDLE_RECENT = 6

STATE_NONE = 0
STATE_B1_WAIT = 1      # B1候B2
STATE_NEEDLE = 2       # 单针探底
STATE_B2_CONFIRM = 3   # B2确认（统计优势所在）

STATE_CN = {STATE_NONE: "无明确战法态", STATE_B1_WAIT: "B1候B2",
            STATE_NEEDLE: "单针探底", STATE_B2_CONFIRM: "B2确认"}


def pattern_state_series(df: pd.DataFrame, b2_wait: int = B2_WAIT,
                         b2_vol_mult: float = B2_VOL_MULT,
                         needle_recent: int = NEEDLE_RECENT) -> np.ndarray:
    """全历史逐日战法状态（int 数组，映射见 STATE_CN）。全因果算子，无未来函数。"""
    from alphapulse.factors import b1_formula, volume_b1
    from alphapulse.strategies import needle

    n = len(df)
    close = df["close"].astype(float).values
    open_ = df["open"].astype(float).values
    vol = df["volume"].astype(float).values
    low = df["low"].astype(float).values

    def _safe(fn):
        try:
            return fn(df).fillna(False).values
        except Exception:
            return np.zeros(n, dtype=bool)

    buy = _safe(b1_formula.compute) | _safe(volume_b1.compute)
    nd = _safe(needle.compute)

    idx = np.arange(n, dtype=float)
    last_buy = pd.Series(np.where(buy, idx, np.nan)).ffill().values
    bars_since_buy = idx - last_buy                          # NaN = 从未有买点

    # B2 放量阳：收>开 且 量>mult×前日量
    b2_day = np.zeros(n, dtype=bool)
    b2_day[1:] = (close[1:] > open_[1:]) & (vol[1:] > b2_vol_mult * vol[:-1])

    # B1 日低点（作 B2 有效性下界：不破 B1 低才算确认）
    b1_low = pd.Series(np.where(buy, low, np.nan)).ffill().values

    # B2确认日 = B2放量阳 且 距最近B1 1..b2_wait 日内 且 收盘 ≥ B1日低
    b2_confirm_day = b2_day & (bars_since_buy >= 1) & (bars_since_buy <= b2_wait) \
        & (close >= b1_low)
    # 确认后的持续期：确认日起 b2_wait 日内保持"B2确认"态（持有窗口）
    last_b2 = pd.Series(np.where(b2_confirm_day, idx, np.nan)).ffill().values
    in_b2 = (idx - last_b2) <= b2_wait

    nd_recent = pd.Series(nd).rolling(needle_recent, min_periods=1).max().fillna(0).values > 0
    in_b1_wait = (bars_since_buy >= 0) & (bars_since_buy <= b2_wait)

    state = np.zeros(n, dtype=int)
    state[nd_recent] = STATE_NEEDLE
    state[in_b1_wait] = STATE_B1_WAIT
    state[in_b2] = STATE_B2_CONFIRM       # 优先级最高
    return state


def pattern_conf_signed(state: np.ndarray, ml: np.ndarray | None
                        ) -> tuple[np.ndarray, np.ndarray]:
    """状态 + GBDT → (confidence 0-100, signed贡献)。agent 取末元素，回测用全序列。

    规则（以回测结论为纲）：
    - B2确认 → 多头：conf=65 基准，GBDT≥0.45 加 10 / <0.30 减 15；conf≥50 才计多头贡献
    - 单针探底 → GBDT≥0.40 才算弱多（55），否则中性
    - B1候B2 → 中性（信号日无统计优势，等确认）
    - 无态 → 中性；GBDT<0.30 记空头贡献（ML否决）
    """
    n = len(state)
    mlv = ml if ml is not None else np.full(n, np.nan)

    conf = np.full(n, 50.0)
    conf[state == STATE_NONE] = 40.0
    b2 = state == STATE_B2_CONFIRM
    conf[b2] = 65.0
    conf[b2 & (mlv >= 0.45)] = 75.0
    conf[b2 & (mlv < 0.30)] = 50.0
    ndl = state == STATE_NEEDLE
    conf[ndl & (mlv >= 0.40)] = 55.0

    signed = np.zeros(n)
    bull_b2 = b2 & (conf >= 50.0)
    signed[bull_b2] = conf[bull_b2]
    bull_nd = ndl & (mlv >= 0.40)
    signed[bull_nd] = conf[bull_nd]
    bear = (state == STATE_NONE) & (mlv < 0.30)
    signed[bear] = -(mlv[bear] * 100.0)
    return conf, signed
