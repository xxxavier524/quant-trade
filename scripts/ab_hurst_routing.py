#!/usr/bin/env python3
"""AB验证：Hurst 战法分流（路线图#12）。

命题：B1（均值回归逻辑）适合低 Hurst；砖型突破（趋势逻辑）适合高 Hurst。
方法：收集战法信号事件 × 事件日 Hurst → 按 Hurst 中位切分（分位法，避开有限样本
绝对偏差），对比低/高 Hurst 子集的 5/10 日净胜率。

用法：python scripts/ab_hurst_routing.py --sample 800
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
from alphapulse.backtest.signal_validator import collect_signal_events, ROUND_TRIP_COST  # noqa: E402
from alphapulse.factors import hurst  # noqa: E402
from validate_signal import load_universe  # noqa: E402


def hurst_long(stocks: dict, window: int) -> pd.DataFrame:
    parts = []
    for i, (sym, df) in enumerate(stocks.items()):
        if i % 200 == 0 and i:
            print(f"  Hurst {i}/{len(stocks)}")
        if len(df) < window + 20:
            continue
        h = hurst.compute(df, window=window)
        parts.append(pd.DataFrame({"symbol": sym,
                                   "date": df["date"].astype(str).values,
                                   "hurst": h.values}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def split_stats(ev: pd.DataFrame, thr: float) -> dict:
    lo = ev[ev["hurst"] < thr]
    hi = ev[ev["hurst"] >= thr]
    out = {}
    for name, sub in [("低Hurst(均值回归)", lo), ("高Hurst(趋势)", hi)]:
        rec = {"n": len(sub)}
        for w in (5, 10):
            net = sub[f"fwd_{w}"].dropna() - ROUND_TRIP_COST
            if len(net) >= 50:
                rec[f"净胜率{w}"] = round(float((net > 0).mean() * 100), 1)
                rec[f"净均值{w}"] = round(float(net.mean() * 100), 2)
        out[name] = rec
    return out


def factor_block(factor: str, stocks: dict, hl: pd.DataFrame, thesis: str) -> list:
    ev = collect_signal_events(factor, stocks, forward_days=[5, 10])
    if ev.empty:
        return [f"### {factor}", "(无信号事件)", ""]
    ev = ev.merge(hl, on=["symbol", "date"], how="left").dropna(subset=["hurst"])
    thr = float(ev["hurst"].median())
    st = split_stats(ev, thr)
    lines = [f"### {factor}（命题：{thesis}）",
             f"事件 {len(ev)} 条 | Hurst 中位 {thr:.3f} 切分", "",
             "| 子集 | 样本 | 净胜率5% | 净均值5% | 净胜率10% | 净均值10% |",
             "|---|---|---|---|---|---|"]
    for name, r in st.items():
        lines.append(f"| {name} | {r['n']} | {r.get('净胜率5','-')} | {r.get('净均值5','-')} "
                     f"| {r.get('净胜率10','-')} | {r.get('净均值10','-')} |")
    lo, hi = st["低Hurst(均值回归)"], st["高Hurst(趋势)"]
    if "净胜率5" in lo and "净胜率5" in hi:
        d = lo["净胜率5"] - hi["净胜率5"]
        lines += ["", f"低−高 净胜率5日差 = {d:+.1f}pp"]
    lines.append("")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--window", type=int, default=120)
    args = ap.parse_args()

    stocks = load_universe(Path(DATA_DIR), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")
    print("计算 Hurst 面板...")
    hl = hurst_long(stocks, args.window)

    lines = [
        "# Hurst 战法分流 AB（路线图#12）",
        "",
        f"> universe {len(stocks)} 只 | Hurst({args.window}窗,结构函数法) | 中位分位切分 | "
        f"净收益−双边成本{ROUND_TRIP_COST:.3f}",
        "",
        "分流命题：**B1（均值回归）在低 Hurst 更优；砖型（趋势）在高 Hurst 更优**。",
        "",
    ]
    lines += factor_block("B1_FORMULA", stocks, hl, "低Hurst应更优")
    lines += factor_block("BRICK_ULTRA", stocks, hl, "高Hurst应更优")
    lines += [
        "结论：若 B1 低−高净胜率差为正、砖型为负，则 Hurst 分流有效，可作战法门控。",
        "诚实：结构函数Hurst对趋势/随机游走分辨弱(见hurst.py标定注)，主要捕捉均值回归轴；",
        "分位切分规避绝对偏差；效应弱则如实报告不强行分流。",
    ]
    out = Path(REPORTS_DIR) / "ab_hurst_routing.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
