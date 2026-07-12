#!/usr/bin/env python3
"""Walk-forward 参数评估框架（阶段六升级，2026-07-12）。

替代单窗口样本内选参（旧 grid_search_b1b2b3 的 hit_rate 是"案例股覆盖率"，
评分里没有任何前向收益——曾产出 hit_rate=1.0 的过拟合参数组）。

方法：
1. 锚定扩张窗：训练窗从 2020 起逐步扩张，验证窗 6 个月滚动，共 8 个验证窗
2. 评价口径 = 实盘同源：信号日后 5 个交易日内最高收盘涨幅 ≥ +5% 记成功
   （与 signal_tracker 的"脱离成本区"完全一致，不发明新指标）
3. 每组参数得到 8 个窗口的样本外成功率 → robust_score = 0.5×中位数 + 0.5×最差窗
   （惩罚方差，不选单窗口冠军）；信号不足的窗口记 None，有效窗 <5 的组合出局
4. 链式流程回测：每个验证窗用"仅凭之前窗口选出的参数"评估——衡量选参流程本身
   在实盘中的期望表现
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HORIZON = 5          # 前向交易日窗口
SUCCESS_PCT = 5.0    # 成功阈值：+5% 脱离成本区
MIN_SIGNALS_PER_WINDOW = 8   # 窗口内信号少于此不计入（避免小样本噪声）
MIN_VALID_WINDOWS = 5        # 有效窗口少于此的参数组合直接出局


def make_windows(first_valid: str = "2022-01-01",
                 last_end: str = "2025-12-31",
                 valid_months: int = 6) -> list[dict]:
    """锚定扩张训练窗 + 滚动验证窗。训练窗起点固定 2020-01-01。"""
    windows = []
    v_start = pd.Timestamp(first_valid)
    last = pd.Timestamp(last_end)
    while v_start < last:
        v_end = min(v_start + pd.DateOffset(months=valid_months) - pd.Timedelta(days=1), last)
        windows.append({
            "train_start": "2020-01-01",
            "train_end": (v_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            "valid_start": v_start.strftime("%Y-%m-%d"),
            "valid_end": v_end.strftime("%Y-%m-%d"),
        })
        v_start = v_start + pd.DateOffset(months=valid_months)
    return windows


def forward_success(sig_dates: list, closes: pd.Series,
                    horizon: int = HORIZON, success_pct: float = SUCCESS_PCT) -> list[dict]:
    """对一只股票的若干信号日算前向结果。closes 以日期为索引（字符串日期）。"""
    idx = {d: i for i, d in enumerate(closes.index)}
    vals = closes.to_numpy(dtype=float)
    out = []
    for d in sig_dates:
        i = idx.get(d)
        if i is None or i + 1 >= len(vals):
            continue
        base = vals[i]
        if not np.isfinite(base) or base <= 0:
            continue
        fwd = vals[i + 1: i + 1 + horizon]
        if len(fwd) < horizon:   # 窗口末尾不足5日的信号丢弃，避免右删失偏差
            continue
        max_ret = (fwd.max() / base - 1) * 100
        end_ret = (fwd[-1] / base - 1) * 100
        out.append({"date": d, "success": max_ret >= success_pct,
                    "max_ret": max_ret, "end_ret": end_ret})
    return out


def evaluate_combo_on_windows(all_signals: dict[str, list],
                              closes_map: dict[str, pd.Series],
                              windows: list[dict]) -> list[dict | None]:
    """一组参数（已生成全历史信号）在每个验证窗的样本外表现。"""
    per_window = []
    for w in windows:
        n = succ = 0
        rets = []
        for sym, sigs in all_signals.items():
            closes = closes_map[sym]
            dates_in = [d for d in sigs if w["valid_start"] <= d <= w["valid_end"]]
            for r in forward_success(dates_in, closes):
                n += 1
                succ += bool(r["success"])
                rets.append(r["end_ret"])
        if n < MIN_SIGNALS_PER_WINDOW:
            per_window.append(None)
        else:
            per_window.append({"n": n, "success_rate": succ / n,
                               "avg_end_ret": float(np.mean(rets))})
    return per_window


def robust_score(per_window: list[dict | None]) -> dict | None:
    """0.5×中位数 + 0.5×最差窗；有效窗不足出局。"""
    rates = [w["success_rate"] for w in per_window if w]
    if len(rates) < MIN_VALID_WINDOWS:
        return None
    return {
        "valid_windows": len(rates),
        "median": float(np.median(rates)),
        "worst": float(np.min(rates)),
        "best": float(np.max(rates)),
        "robust": 0.5 * float(np.median(rates)) + 0.5 * float(np.min(rates)),
        "total_signals": int(sum(w["n"] for w in per_window if w)),
    }


def chain_selection(combo_windows: dict[str, list], windows: list[dict]) -> list[dict]:
    """链式流程回测：第k窗用"仅凭前k-1个窗选出的参数"评估。

    选参规则与最终规则一致（前序窗口的 0.5中位+0.5最差）。返回每窗的
    {window, chosen_params, oos_success_rate}——这串数字才是"这套选参流程
    实盘能拿到什么"的无偏估计。
    """
    results = []
    for k in range(1, len(windows)):
        best_key, best_score = None, -1.0
        for key, pw in combo_windows.items():
            rates = [w["success_rate"] for w in pw[:k] if w]
            if len(rates) < max(2, k // 2):
                continue
            s = 0.5 * float(np.median(rates)) + 0.5 * float(np.min(rates))
            if s > best_score:
                best_key, best_score = key, s
        cur = combo_windows[best_key][k] if best_key else None
        results.append({
            "window": f"{windows[k]['valid_start']}~{windows[k]['valid_end']}",
            "chosen": best_key,
            "oos": (round(cur["success_rate"], 4) if cur else None),
            "n": (cur["n"] if cur else 0),
        })
    return results
