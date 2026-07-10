#!/usr/bin/env python3
"""单因子参数网格 × 前向净收益验证（路线图#6/#7 通用验收）。

对一个因子的某个参数做网格，收集其信号事件的 5/10 日前向净收益，
对比基线（全交易日随机基准）。用途：
- #6 WASHOUT_SEGMENT × max_vol_ratio：入场信号，净胜率**越高越好**
- #7 MACD_DIVERGENCE × divergence_rate：顶背离卖点，信号后净胜率**越低越好**（走弱=好卖点）

用法：
  python scripts/grid_factor_forward.py --factor WASHOUT_SEGMENT --param max_vol_ratio \
      --values 0.4,0.5,0.6,0.75 --goal high --sample 800
  python scripts/grid_factor_forward.py --factor MACD_DIVERGENCE --param divergence_rate \
      --values 0.7,0.8,0.9,1.0 --goal low --sample 800
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
from alphapulse.backtest.signal_validator import (  # noqa: E402
    collect_signal_events, ROUND_TRIP_COST)
from validate_signal import load_universe  # noqa: E402


def baseline_forward(stocks: dict, days=(5, 10)) -> dict:
    """全样本随机基准：所有交易日的前向净收益（信号需超越的对照）。"""
    out = {w: [] for w in days}
    for df in stocks.values():
        if len(df) < 30:
            continue
        close = df["close"].astype(float).to_numpy()
        for w in days:
            r = close[w:] / close[:-w] - 1
            out[w].append(r)
    res = {}
    for w in days:
        arr = np.concatenate(out[w]) - ROUND_TRIP_COST if out[w] else np.array([])
        res[w] = (len(arr), round(float((arr > 0).mean() * 100), 1) if len(arr) else None,
                  round(float(arr.mean() * 100), 2) if len(arr) else None)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", required=True)
    ap.add_argument("--param", required=True)
    ap.add_argument("--values", required=True, help="逗号分隔")
    ap.add_argument("--goal", choices=["high", "low"], default="high",
                    help="high=入场(净胜率越高越好); low=卖点(信号后净胜率越低越好)")
    ap.add_argument("--sample", type=int, default=800)
    args = ap.parse_args()

    values = [float(v) for v in args.values.split(",")]
    stocks = load_universe(Path(DATA_DIR), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")

    base = baseline_forward(stocks)
    rows = []
    for v in values:
        ev = collect_signal_events(args.factor, stocks, params={args.param: v},
                                   forward_days=[5, 10])
        rec = {args.param: v, "样本": 0 if ev.empty else len(ev)}
        if not ev.empty:
            for w in (5, 10):
                net = ev[f"fwd_{w}"].dropna() - ROUND_TRIP_COST
                if len(net) >= 50:
                    rec[f"净胜率{w}%"] = round(float((net > 0).mean() * 100), 1)
                    rec[f"净均值{w}%"] = round(float(net.mean() * 100), 2)
        rows.append(rec)
        print(f"  {args.param}={v}: 样本 {rec['样本']}")

    # 选优
    valid = [r for r in rows if "净胜率5%" in r]
    best = None
    if valid:
        best = (max(valid, key=lambda r: r["净胜率5%"]) if args.goal == "high"
                else min(valid, key=lambda r: r["净胜率5%"]))

    cols = [args.param, "样本", "净胜率5%", "净均值5%", "净胜率10%", "净均值10%"]
    lines = [
        f"# {args.factor} × {args.param} 网格前向验证（路线图#6/#7）",
        "",
        f"> universe {len(stocks)} 只 | 净收益=前向−双边成本{ROUND_TRIP_COST:.3f} | "
        f"目标={'入场净胜率越高越好' if args.goal=='high' else '卖点信号后净胜率越低越好'}",
        "",
        f"**随机基准**：5日净胜率 {base[5][1]}%（净均值 {base[5][2]}%）、"
        f"10日 {base[10][1]}%（{base[10][2]}%）",
        "",
        "| " + " | ".join(cols) + " |",
        "|" + "|".join(["---"] * len(cols)) + "|",
    ]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "-")) for c in cols) + " |")
    if best:
        b5 = best["净胜率5%"]
        if args.goal == "high":
            verdict = (f"最优 {args.param}={best[args.param]}：5日净胜率 {b5}% "
                       f"vs 基准 {base[5][1]}%（{'超越基准=入场有效' if b5 > base[5][1] else '未超基准'}）")
        else:
            verdict = (f"最优（走弱最强）{args.param}={best[args.param]}：信号后5日净胜率 {b5}% "
                       f"vs 基准 {base[5][1]}%（{'低于基准=顶背离后确实走弱,卖点有效' if b5 < base[5][1] else '未低于基准'}）")
        note = ("诚实口径：顶背离用'信号后前向走弱'做代理，非完整持仓卖出模拟；样本<50略过。"
                if args.goal == "low" else
                "诚实口径：这是**标量入场**口径；洗盘模板的设计用途是B3/单针的过滤部件，"
                "网格给出最优缩量上限即完成#6验收；样本<50略过。")
        lines += ["", f"**结论：{verdict}**", "", note]
    out = Path(REPORTS_DIR) / f"grid_{args.factor.lower()}_{args.param}.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:]))
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
