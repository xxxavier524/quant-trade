"""信号胜率验证器 — Phase 3 核心：验证经验、优化因子的统计工具。

对任意注册因子/公式，在全历史回放信号点，统计前向 N 日收益：
- 胜率（>0比例）、均值、中位数、分位分布、逐年拆分、样本数
- 毛收益与净收益（含滑点佣金）
- 截面 Rank IC（喂给 FactorWeighter 闭环调权）

全程向量化：signal 序列与 close.shift(-n) 对齐，无逐行循环。
前向收益仅用于统计验证（事后评估），不构成未来函数泄漏。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphapulse.config.settings import (
    SLIPPAGE_BUY,
    SLIPPAGE_SELL,
    COMMISSION_RATE,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 单边进出成本（买滑点+卖滑点+双边佣金），用于净收益
ROUND_TRIP_COST = SLIPPAGE_BUY + SLIPPAGE_SELL + 2 * COMMISSION_RATE


def forward_returns(close: pd.Series, days: list[int]) -> pd.DataFrame:
    """各前向窗口收益：fwd_n = close[t+n]/close[t] - 1。"""
    out = {}
    for n in days:
        out[f"fwd_{n}"] = close.shift(-n) / close - 1
    return pd.DataFrame(out, index=close.index)


def collect_signal_events(
    factor_name: str,
    stocks: dict[str, pd.DataFrame],
    params: dict | None = None,
    forward_days: list[int] | None = None,
    start: str = "2020-01-01",
    end: str = "9999-12-31",
) -> pd.DataFrame:
    """收集全历史信号事件及其前向收益。

    Returns:
        DataFrame[symbol, date, fwd_1, fwd_3, ...]，每行一个信号事件
    """
    from alphapulse.factors.factor_registry import FACTOR_REGISTRY

    forward_days = forward_days or [1, 3, 5, 10, 20]
    entry = FACTOR_REGISTRY.get(factor_name)
    if entry is None:
        raise KeyError(f"未注册因子: {factor_name}")
    module = entry["module"]
    p = dict(entry.get("default_params", {}))
    if params:
        p.update(params)

    events = []
    for sym, df in stocks.items():
        if len(df) < 120:
            continue
        try:
            sig = module.compute(df, **p)
        except TypeError:
            sig = module.compute(df)
        except Exception:
            continue
        if sig is None or not sig.any():
            continue
        sig = sig.fillna(False).astype(bool)
        close = df["close"].astype(float)
        fwd = forward_returns(close, forward_days)
        dates = df["date"] if "date" in df.columns else df.index.astype(str)
        mask = sig & (dates >= start) & (dates <= end)
        if not mask.any():
            continue
        ev = fwd[mask].copy()
        ev.insert(0, "date", pd.Series(dates)[mask].values)
        ev.insert(0, "symbol", sym)
        events.append(ev)

    if not events:
        return pd.DataFrame()
    return pd.concat(events, ignore_index=True)


def summarize(events: pd.DataFrame, forward_days: list[int] | None = None) -> dict:
    """事件表 → 统计摘要（毛/净收益、胜率、分位、逐年）。"""
    forward_days = forward_days or [1, 3, 5, 10, 20]
    if events.empty:
        return {"n_signals": 0}

    out = {"n_signals": int(len(events)),
           "n_symbols": int(events["symbol"].nunique()),
           "date_range": [str(events["date"].min()), str(events["date"].max())],
           "windows": {}}
    for n in forward_days:
        col = events[f"fwd_{n}"].dropna()
        if col.empty:
            continue
        net = col - ROUND_TRIP_COST
        out["windows"][n] = {
            "n": int(len(col)),
            "win_rate": round(float((col > 0).mean()), 4),
            "win_rate_net": round(float((net > 0).mean()), 4),
            "mean": round(float(col.mean()), 4),
            "mean_net": round(float(net.mean()), 4),
            "median": round(float(col.median()), 4),
            "p10": round(float(col.quantile(0.1)), 4),
            "p90": round(float(col.quantile(0.9)), 4),
        }
    # 逐年拆分（主窗口=5日）
    main = f"fwd_5" if "fwd_5" in events.columns else f"fwd_{forward_days[0]}"
    ev = events.dropna(subset=[main]).copy()
    ev["year"] = ev["date"].astype(str).str[:4]
    by_year = {}
    for year, g in ev.groupby("year"):
        by_year[year] = {
            "n": int(len(g)),
            "win_rate": round(float((g[main] > 0).mean()), 4),
            "mean": round(float(g[main].mean()), 4),
        }
    out["by_year"] = by_year
    return out


def cross_sectional_ic(events: pd.DataFrame, factor_col: str | None = None,
                       window: int = 5) -> list[float]:
    """逐日截面IC（信号事件的因子值 vs 前向收益）。

    布尔信号无截面强弱差异时返回空；连续因子可传 factor_col。
    """
    col = f"fwd_{window}"
    if events.empty or col not in events.columns or factor_col is None:
        return []
    from alphapulse.ranking.factor_weighter import compute_rank_ic
    ics = []
    for _, g in events.groupby("date"):
        if len(g) >= 30:
            ics.append(compute_rank_ic(g[factor_col], g[col]))
    return ics


def validate_signal(
    factor_name: str,
    stocks: dict[str, pd.DataFrame],
    params: dict | None = None,
    forward_days: list[int] | None = None,
    start: str = "2020-01-01",
    end: str = "9999-12-31",
) -> dict:
    """一站式信号验证：事件收集 + 统计摘要。"""
    forward_days = forward_days or [1, 3, 5, 10, 20]
    events = collect_signal_events(factor_name, stocks, params, forward_days, start, end)
    result = summarize(events, forward_days)
    result["factor"] = factor_name
    result["params"] = params or {}
    return result


def save_result(result: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (PROJECT_ROOT / "backtest_results")
    out_dir.mkdir(exist_ok=True)
    name = result["factor"]
    p = out_dir / f"signal_validation_{name}.json"
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return p
