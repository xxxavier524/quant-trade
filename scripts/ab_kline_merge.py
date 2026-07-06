#!/usr/bin/env python3
"""AB验证：长下影探底信号 在 原始K线 vs 合并K线 上的对比（路线图#10）。

缠论合并去毛刺 → 长下影/底分型更稳定。用自包含的长下影信号（单针核心）在两种
K线上计算，映射回原始日历，对比信号数（合并后应更少=去毛刺）与前向净胜率。

用法：python scripts/ab_kline_merge.py --sample 800
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR, REPORTS_DIR  # noqa: E402
from alphapulse.backtest.signal_validator import ROUND_TRIP_COST  # noqa: E402
from alphapulse.utils.kline_merge import (  # noqa: E402
    merge_klines, map_merged_signal_to_original)
from validate_signal import load_universe  # noqa: E402


def long_lower_shadow(df: pd.DataFrame, shadow_mult: float = 2.0,
                      low_lookback: int = 20, low_tol: float = 1.02) -> np.ndarray:
    """长下影探底：下影 > shadow_mult×实体 且 处于近 low_lookback 日低位。"""
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    body = np.abs(c - o)
    lower_shadow = np.minimum(o, c) - low
    long_shadow = (lower_shadow > shadow_mult * np.maximum(body, 1e-9)) & (lower_shadow > 0)
    roll_min = pd.Series(low).rolling(low_lookback, min_periods=low_lookback).min().to_numpy()
    at_low = low <= roll_min * low_tol
    return long_shadow & at_low


def forward_stats(signal_orig: np.ndarray, close: np.ndarray, days=(5, 10)) -> dict:
    out = {}
    idx = np.flatnonzero(signal_orig)
    for w in days:
        rets = [close[i + w] / close[i] - 1 for i in idx if i + w < len(close)]
        out[w] = np.array(rets)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--shadow-mult", type=float, default=2.0)
    args = ap.parse_args()

    stocks = load_universe(Path(DATA_DIR), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")

    raw_r = {5: [], 10: []}
    mrg_r = {5: [], 10: []}
    n_raw = n_mrg = 0
    for i, (sym, df) in enumerate(stocks.items()):
        if i % 200 == 0 and i:
            print(f"  {i}/{len(stocks)}")
        if len(df) < 60:
            continue
        close = df["close"].to_numpy(dtype=float)
        # 原始K线
        sig_raw = long_lower_shadow(df, args.shadow_mult)
        # 合并K线 → 映射回原始
        merged, _ = merge_klines(df)
        sig_m = long_lower_shadow(merged, args.shadow_mult)
        sig_mrg = map_merged_signal_to_original(sig_m, merged, len(df))
        n_raw += int(sig_raw.sum())
        n_mrg += int(sig_mrg.sum())
        fr = forward_stats(sig_raw, close)
        fm = forward_stats(sig_mrg, close)
        for w in (5, 10):
            raw_r[w].append(fr[w]); mrg_r[w].append(fm[w])

    def summ(store, w):
        arr = np.concatenate(store[w]) if store[w] else np.array([])
        if len(arr) < 50:
            return (len(arr), None, None)
        net = arr - ROUND_TRIP_COST
        return (len(arr), round(float((net > 0).mean() * 100), 1),
                round(float(net.mean() * 100), 2))

    rows = []
    for label, store, n in [("原始K线", raw_r, n_raw), ("合并K线", mrg_r, n_mrg)]:
        n5, w5, m5 = summ(store, 5)
        n10, w10, m10 = summ(store, 10)
        rows.append((label, n, w5, m5, w10, m10))

    drop = (n_raw - n_mrg) / max(n_raw, 1) * 100
    w5_raw, w5_mrg = rows[0][2], rows[1][2]
    dwin = (w5_mrg - w5_raw) if (w5_raw is not None and w5_mrg is not None) else None
    verdict = (f"合并去毛刺：信号数 {n_raw}→{n_mrg}（−{drop:.0f}%）；"
               f"5日净胜率 {w5_raw}%→{w5_mrg}%（Δ{dwin:+.1f}）" if dwin is not None
               else "样本不足")
    if dwin is not None:
        verdict += "，去毛刺后胜率" + ("提升=有效" if dwin > 0.5 else
                                      "持平" if dwin > -0.5 else "下降(漏真信号,代价>收益)")

    lines = [
        "# 长下影探底：原始K线 vs 合并K线 AB（路线图#10）",
        "",
        f"> universe {len(stocks)} 只 | 长下影(下影>{args.shadow_mult}×实体)+近20日低位 | "
        f"净收益−双边成本{ROUND_TRIP_COST:.3f}",
        "",
        f"**结论：{verdict}**",
        "",
        "| K线口径 | 信号数 | 净胜率5% | 净均值5% | 净胜率10% | 净均值10% |",
        "|---|---|---|---|---|---|",
    ]
    for label, n, w5, m5, w10, m10 in rows:
        lines.append(f"| {label} | {n} | {w5} | {m5} | {w10} | {m10} |")
    lines += ["", "说明：缠论合并把横盘毛刺并成一根，长下影/底分型在合并序列上更稳定。"
              "信号减少=去毛刺；胜率变化揭示去掉的是噪音还是真信号（诚实记录）。"]
    out = Path(REPORTS_DIR) / "ab_kline_merge.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:]))
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
