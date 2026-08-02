"""纯选股成功率评估器（v5 第一性原理，2026-08-02）。

定义（规格见 docs/v5_screen_system.md）：
- 信号日 T 以收盘确认 → 观察未来 H 个交易日的收盘价
- 主口径 success（机会命中，唯一 KPI）：
      close[T+1..T+H] 任一 ≥ close[T] × (1+P)
  —— "选出来之后 H 天内给过 +P% 的收盘可成交卖出机会"。
    纯涨跌判断，不含仓位/滑点/止损等任何交易模拟。
- 对照口径（报告用，不参与优化目标）：
      end_ret: T+H 收盘相对 T 收盘的涨跌幅（持有到期末）
      max_ret: 未来 H 日收盘中最大涨幅（可成交上限）
      min_ret: 未来 H 日收盘中最大跌幅（风险暴露）
- 基线：每个信号日的全体股票截面基础成功率 —— 策略只有显著跑赢
  "随机选一只"才有存在价值（第一性原理：选股 = 提高命中率）。
- 因果铁律：信号帧索引是源帧的行标签，必须经源帧 date 列映射回日期；
  因子本身不得使用未来信息（screen_bt 内置截断不变性门禁抽样验证）。
- 样本门槛：结论只在 n ≥ MIN_SIGNALS 时给出（小样本成功率无意义）。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

# 默认评价窗口与阈值（可参数化）
DEFAULT_HORIZON = 5          # 未来交易日
DEFAULT_SUCCESS_PCT = 5.0    # +P% 命中阈值
MIN_SIGNALS = 100            # 低于此样本量不出结论（策略层面）
MIN_SIGNALS_PER_YEAR = 20    # 单年低于此样本量的年份不计入年度表


# ---------------------------------------------------------------------------
# 信号日期解析
# ---------------------------------------------------------------------------

def signal_dates_of(sig_frame: pd.DataFrame, src: pd.DataFrame) -> list[str]:
    """策略信号帧 → 买入信号日期列表（因果、可复现）。

    策略生成器输出帧的索引 = 输入帧的行标签（RangeIndex 输入即行号，
    DatetimeIndex 输入即日期），必须经源帧 date 列映射回日期字符串，
    不能直接把索引当日期。
    """
    if sig_frame is None or sig_frame.empty:
        return []
    if "signal" in sig_frame.columns:
        sig_frame = sig_frame[sig_frame["signal"] == 1]
    if sig_frame.empty:
        return []
    return [str(d)[:10] for d in src["date"].reindex(sig_frame.index).dropna()]


# ---------------------------------------------------------------------------
# 前向结果
# ---------------------------------------------------------------------------

@dataclass
class Outcome:
    date: str
    success: bool        # 主口径：H 日内任一收盘 ≥ +P%
    end_ret: float       # T+H 收盘相对 T 收盘（%）
    max_ret: float       # 未来 H 日收盘最大涨幅（%）
    min_ret: float       # 未来 H 日收盘最大跌幅（%）
    base_rate: float | None = None   # 该信号日的全体股票基础成功率（%）


def forward_outcome(
    sig_dates: list[str],
    closes: pd.Series,
    horizon: int = DEFAULT_HORIZON,
    success_pct: float = DEFAULT_SUCCESS_PCT,
) -> list[Outcome]:
    """对一只股票的若干信号日计算前向结果（closes 以日期字符串为索引）。

    右删失处理：窗口末尾不足 H 个交易日的信号丢弃（避免"只有涨了才有后续数据"
    的选择偏差）；信号日之后无数据也丢弃。
    """
    idx = {d: i for i, d in enumerate(closes.index)}
    vals = closes.to_numpy(dtype=float)
    out = []
    for d in sig_dates:
        i = idx.get(d)
        if i is None or i + 1 >= len(vals):
            continue
        base = float(vals[i])
        if not np.isfinite(base) or base <= 0:
            continue
        fwd = vals[i + 1: i + 1 + horizon]
        if len(fwd) < horizon:
            continue
        fwd = fwd.astype(float)
        max_ret = float((fwd.max() / base - 1) * 100)
        min_ret = float((fwd.min() / base - 1) * 100)
        end_ret = float((fwd[-1] / base - 1) * 100)
        out.append(Outcome(
            date=d,
            success=max_ret >= success_pct,
            end_ret=end_ret,
            max_ret=max_ret,
            min_ret=min_ret,
        ))
    return out


def _fwd_windows(
    sig_dates: list[str],
    closes: pd.Series,
    horizon: int,
) -> list[tuple[str, float, np.ndarray]]:
    """每股预计算 (信号日, 基准收盘, 未来H日收盘数组)，只对存在的日期。"""
    idx = {d: i for i, d in enumerate(closes.index)}
    vals = closes.to_numpy(dtype=float)
    out = []
    for d in sig_dates:
        i = idx.get(d)
        if i is None or i + 1 >= len(vals):
            continue
        base = float(vals[i])
        if not np.isfinite(base) or base <= 0:
            continue
        fwd = vals[i + 1: i + 1 + horizon]
        if len(fwd) < horizon:
            continue
        out.append((d, base, fwd.astype(float)))
    return out


def _hits(fwd: np.ndarray, base: float, success_pct: float) -> bool:
    return bool((fwd.max() / base - 1) * 100 >= success_pct)


def cross_sectional_base_rates(
    sig_dates: list[str],
    closes_map: dict[str, pd.Series],
    horizon: int = DEFAULT_HORIZON,
    success_pct: float = DEFAULT_SUCCESS_PCT,
) -> dict[str, float]:
    """每个信号日的全体股票基础成功率（%）。

    对每个信号日，用当天有完整后续 H 日数据的所有股票计算命中率
    （与 forward_outcome 完全同口径），构成"随机选一只"的对照基线。
    """
    by_date: dict[str, list[bool]] = defaultdict(list)
    for closes in closes_map.values():
        for d, base, fwd in _fwd_windows(sig_dates, closes, horizon):
            by_date[d].append(_hits(fwd, base, success_pct))
    return {
        d: (sum(ok) / len(ok) * 100 if ok else float("nan"))
        for d, ok in by_date.items()
    }


# ---------------------------------------------------------------------------
# 策略级汇总
# ---------------------------------------------------------------------------

def evaluate_strategy(
    sig_dates_by_symbol: dict[str, list[str]],
    closes_map: dict[str, pd.Series],
    horizon: int = DEFAULT_HORIZON,
    success_pct: float = DEFAULT_SUCCESS_PCT,
    min_signals: int = MIN_SIGNALS,
) -> dict:
    """策略成功率汇总（主口径 + 对照 + 基线 + 年度/逐日命中曲线）。

    Returns:
        dict：含 n、success_rate、基线、lift、均值/中位数收益、
        年度表、逐 H 命中曲线、样本不足标记等。n < min_signals 时
        success_rate=None（不出结论）。
    """
    # 每股前向结果（一次预计算，供 outcome/基线/曲线复用）。
    # sig_dates_by_symbol: {symbol: [信号日...]} —— 每个信号日只属于它自己的股票，
    # 绝不能用扁平日期表套用到全体股票（会虚增样本、洗掉个股差异）。
    all_out: list[Outcome] = []
    windows_by_date: dict[str, list[tuple[float, np.ndarray]]] = defaultdict(list)
    for sym, sym_dates in sig_dates_by_symbol.items():
        closes = closes_map.get(sym)
        if closes is None:
            continue
        for d, base, fwd in _fwd_windows(sym_dates, closes, horizon):
            windows_by_date[d].append((base, fwd))
            all_out.append(Outcome(
                date=d,
                success=_hits(fwd, base, success_pct),
                end_ret=float((fwd[-1] / base - 1) * 100),
                max_ret=float((fwd.max() / base - 1) * 100),
                min_ret=float((fwd.min() / base - 1) * 100),
            ))

    if not all_out:
        return {"n": 0, "success_rate": None,
                "reason": "无有效信号（右删失或数据缺失）"}
    if len(all_out) < min_signals:
        return {"n": len(all_out), "success_rate": None,
                "reason": f"样本不足（{len(all_out)} < {min_signals}）"}

    # 基线：按信号日求全体股票基础成功率（对照"随机选一只"，与信号所属股票无关）
    dates_union = sorted({d for sym_dates in sig_dates_by_symbol.values()
                          for d in sym_dates})
    base_map = cross_sectional_base_rates(
        dates_union, closes_map, horizon, success_pct)
    bases = [base_map.get(o.date, np.nan) for o in all_out]
    valid_base = [b for b in bases if np.isfinite(b)]
    base_mean = float(np.mean(valid_base)) if valid_base else float("nan")
    for o, b in zip(all_out, bases):
        o.base_rate = b

    success_rate = float(np.mean([o.success for o in all_out]) * 100)
    end = np.array([o.end_ret for o in all_out])
    mx = np.array([o.max_ret for o in all_out])
    mn = np.array([o.min_ret for o in all_out])

    # 年度表
    years = pd.DataFrame(
        [{"year": int(o.date[:4]), "success": o.success, "end": o.end_ret}
         for o in all_out if o.date[:4].isdigit()])
    yearly = []
    if not years.empty and "year" in years.columns:
        for y, g in years.groupby("year"):
            if len(g) < MIN_SIGNALS_PER_YEAR:
                continue
            yearly.append({
                "year": y, "n": len(g),
                "success_rate": round(float(g["success"].mean() * 100), 1),
                "end_ret": round(float(g["end"].mean()), 2),
            })

    # 逐 H 命中曲线（主口径随窗口长度变化；H 越短越严）
    curve = []
    for h in range(1, horizon + 1):
        hits = 0
        total = 0
        for wins in windows_by_date.values():
            for base, fwd in wins:
                total += 1
                hits += bool((fwd[:h].max() / base - 1) * 100 >= success_pct)
        if total:
            curve.append({"horizon": h, "success_rate": round(hits / total * 100, 1)})

    return {
        "n": len(all_out),
        "success_rate": round(success_rate, 2),
        "base_rate": round(base_mean, 2) if np.isfinite(base_mean) else None,
        "lift_pp": (round(success_rate - base_mean, 2)
                    if np.isfinite(base_mean) else None),
        "end_ret_mean": round(float(end.mean()), 2),
        "end_ret_median": round(float(np.median(end)), 2),
        "max_ret_mean": round(float(mx.mean()), 2),
        "min_ret_mean": round(float(mn.mean()), 2),
        "hit_ratio_end": round(float((end > 0).mean() * 100), 1),
        "yearly": yearly,
        "curve": curve,
    }


def wilson_lower(success_rate: float, n: int, z: float = 1.96) -> float | None:
    """Wilson 下界（%）——小样本成功率的不确定性量化。"""
    if n <= 0 or not (0 <= success_rate <= 100):
        return None
    p = success_rate / 100
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return round(max(0.0, (centre - half) * 100), 2)
