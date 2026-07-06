"""Z哥 B1 + 砖型图 融合选股策略（独立，不改动现有 B1）。

设计依据：女娲蒸馏的 zettaranc-perspective 体系（少妇战法 SOP），把 Z哥的完整
交易纪律串成一个自包含的选股器：

    进场（B1）  →  砖型图周期确认  →  纪律卡（止损 / 止盈 / 离场）

- 进场：复用用户已实现的 B1 选股公式 `b1_formula.compute`
  （涨幅±3% + 振幅<9% + J<13 + 白线>黄线 + DIF>-0.1 + 市值>10亿）
  = 体系里的「B1 买点·顺大势逆小势」。
- 砖型图确认：复用 `four_brick_cycle`，只在**周期早段（第1~2块红砖）**放行，
  尾段（第4块砖起）直接否决 = 体系「绿砖不抄底 / 4块红砖减仓」的进场侧。
- 纪律卡（不进入布尔信号，作为附带输出，供下单/风控使用）：
  · 止损线：`dynamic_stop_loss`（入场日最低价-3价位）= 体系「只输一根K线」
  · 离场提示：`s1_sell_signal` / 砖型图尾段 = 体系「卤煮止盈 / 4砖减仓」

刻意保持**独立**：新 registry 键 `ZG_B1_BRICK`，新脚本 `scripts/zg_screener.py`，
现有 B1 / daily_screener 一律不动。跑一段时间效果好，再考虑并入主选股。

返回结构对齐现有 selection 约定（symbol/date/signal/strategy/factor_snapshot），
另加 Z哥纪律字段：brick_position / stop_loss / exit_hint。
"""

from __future__ import annotations

import pandas as pd

from alphapulse.factors import b1_formula, four_brick_cycle, dynamic_stop_loss, s1_sell_signal

STRATEGY_NAME = "ZG_B1_BRICK"

_OUT_COLS = [
    "symbol", "date", "signal", "strategy",
    "brick_position", "stop_loss", "exit_hint", "confidence", "factor_snapshot",
]


def compute(
    data: pd.DataFrame,
    early_max: int = 2,
    late_from: int = 4,
    require_brick_early: bool = True,
    **b1_params,
) -> pd.Series:
    """布尔信号序列：B1 买点 AND 砖型图周期早段（可关）AND 非尾段。

    Args:
        data: 日线 OHLCV（可含 market_cap / pct_change / amplitude，交由 b1_formula 使用）
        early_max: 砖型图「早段」的红砖上限（默认第1~2块红砖）
        late_from: 砖型图「尾段」起始红砖数（默认第4块，尾段一律否决）
        require_brick_early: True=必须处于早段；False=只否决尾段（更宽松）
        **b1_params: 透传给 b1_formula.compute（j_threshold / m1..m4 等）

    Returns:
        pd.Series[bool]
    """
    b1 = b1_formula.compute(data, **b1_params)

    early = four_brick_cycle.compute(data, early_max=early_max)   # 第1~early_max红砖
    late = four_brick_cycle.compute_late(data, late_from=late_from)  # 第late_from砖起

    if require_brick_early:
        sig = b1 & early & ~late
    else:
        sig = b1 & ~late

    return sig.reindex(data.index, fill_value=False).fillna(False).astype(bool)


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    early_max: int = 2,
    late_from: int = 4,
    require_brick_early: bool = True,
    **b1_params,
) -> pd.DataFrame:
    """生成 Z哥融合策略信号（含纪律卡）。

    Returns:
        DataFrame（index=信号日），列见 `_OUT_COLS`：
        - signal=1 买入
        - brick_position: 当日连续红砖数（周期位置）
        - stop_loss: Z哥式止损线（入场日最低价-3价位）
        - exit_hint: 离场提示（"S1卖出" / "四砖尾段减仓" / ""）
        - confidence: 0-1，早段第1块红砖最高，越接近尾段越低
        - factor_snapshot: 关键因子当前值
    """
    if len(data) < 120:
        return pd.DataFrame(columns=_OUT_COLS)

    sig = compute(
        data, early_max=early_max, late_from=late_from,
        require_brick_early=require_brick_early, **b1_params,
    )
    if not sig.any():
        return pd.DataFrame(columns=_OUT_COLS)

    brick_pos = four_brick_cycle.compute_brick_position(data)
    s1 = s1_sell_signal.compute(data)
    b1_detail = b1_formula.compute_detail(data, **b1_params)

    rows = []
    for dt in data.index[sig]:
        pos = int(brick_pos.loc[dt])
        # 置信度：早段红砖越靠前越高（第1块=1.0，第2块=0.8…），封顶/兜底 0.5
        conf = round(max(0.5, 1.0 - 0.2 * max(0, pos - 1)), 2)

        exit_hint = ""
        if int(s1.loc[dt]) > 0:
            exit_hint = "S1卖出"
        elif pos >= late_from:
            exit_hint = "四砖尾段减仓"

        # Z哥式止损：以该信号日为入场日
        try:
            stop = dynamic_stop_loss.compute(data.loc[:dt], entry_date=dt)
        except Exception:
            stop = round(float(data.loc[dt, "low"]) - 0.03, 2)

        snap = {}
        if dt in b1_detail.index:
            r = b1_detail.loc[dt]
            snap = {
                "kdj_j": float(r.get("kdj_j", float("nan"))),
                "white_line": float(r.get("white_line", float("nan"))),
                "yellow_line": float(r.get("yellow_line", float("nan"))),
                "macd_dif": float(r.get("macd_dif", float("nan"))),
            }
        snap["close"] = float(data.loc[dt, "close"])
        snap["brick_position"] = pos

        rows.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": STRATEGY_NAME,
            "brick_position": pos,
            "stop_loss": stop,
            "exit_hint": exit_hint,
            "confidence": conf,
            "factor_snapshot": snap,
        })

    return pd.DataFrame(rows).set_index("date").sort_index()
