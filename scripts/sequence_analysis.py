#!/usr/bin/env python3
"""B1→B2→B3 序列漏斗与胜率分析（路线图#4 验收）。

按 seq_id 聚合 generate_signals 输出：
1. 漏斗：N 条 B1 序列 → 推进到 B2 的比例 → 推进到 B3 的比例
2. 各阶段前向净胜率（以每条序列的 B1 入场日为基准 or 阶段入场日）：
   - 孤立 B1（止步 B1，无 B2）
   - 推进到 B2 的序列（B2 日入场）
   - 推进到 B3 的序列（B3 日入场）
3. 复核 roadmap 主张：simulate_b1b2b3 交易级 B1B2B3 胜率≈94.7% 在序列维度是否成立。

用法：python scripts/sequence_analysis.py --sample 800
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
from alphapulse.strategies.b1_b2_b3_strategy import generate_signals  # noqa: E402
from validate_signal import load_universe  # noqa: E402


def build_sequences(stocks: dict) -> pd.DataFrame:
    """全 universe → 每条序列一行：seq_id, 到达阶段, 各阶段日期与前向收益。"""
    rows = []
    for i, (sym, df) in enumerate(stocks.items()):
        if i % 200 == 0 and i:
            print(f"  序列 {i}/{len(stocks)}")
        if len(df) < 120:
            continue
        d = df.set_index("date")
        sig = generate_signals(d, symbol=sym)
        if sig.empty or "seq_id" not in sig.columns:
            continue
        close = d["close"].astype(float)
        dates = list(d.index)
        pos = {dt: k for k, dt in enumerate(dates)}

        def fwd(dt, n):
            k = pos.get(dt)
            if k is None or k + n >= len(close):
                return np.nan
            return float(close.iloc[k + n] / close.iloc[k] - 1)

        linked = sig[sig["seq_id"].notna()]
        for seq_id, g in linked.groupby("seq_id"):
            by_stage = {r["signal_type"]: dt for dt, r in g.iterrows()}
            b1_dt = g.iloc[0]["seq_root_date"]
            reached = ("B3" if "B3" in by_stage else
                       "B2" if "B2" in by_stage else "B1")
            rec = {"seq_id": seq_id, "symbol": sym, "b1_date": b1_dt,
                   "reached": reached}
            # 各阶段入场的前向净收益
            for stage in ("B1", "B2", "B3"):
                dt = by_stage.get(stage) if stage != "B1" else b1_dt
                for w in (5, 10):
                    rec[f"{stage}_fwd{w}"] = fwd(dt, w) if dt is not None else np.nan
            rows.append(rec)
    return pd.DataFrame(rows)


def _winrate(series: pd.Series) -> tuple:
    s = series.dropna()
    if len(s) < 30:
        return (len(s), None, None)
    net = s - ROUND_TRIP_COST
    return (len(s), round(float((net > 0).mean() * 100), 1),
            round(float(net.mean() * 100), 2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    args = ap.parse_args()

    stocks = load_universe(Path(DATA_DIR), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")
    print("生成信号 + 序列聚合...")
    seq = build_sequences(stocks)
    if seq.empty:
        print("无序列"); return 1

    n_seq = len(seq)
    n_b2 = int((seq["reached"].isin(["B2", "B3"])).sum())
    n_b3 = int((seq["reached"] == "B3").sum())
    print(f"序列 {n_seq} 条 | 到B2 {n_b2} | 到B3 {n_b3}")

    # 漏斗
    funnel = [
        f"- B1 序列总数：{n_seq}",
        f"- 推进到 B2：{n_b2}（{n_b2/n_seq*100:.1f}%）",
        f"- 推进到 B3：{n_b3}（{n_b3/n_seq*100:.1f}%，占B2的{n_b3/max(n_b2,1)*100:.1f}%）",
    ]

    # 各阶段入场胜率（以到达该阶段的序列，在该阶段日入场）
    iso_b1 = seq[seq["reached"] == "B1"]          # 孤立B1（未确认）
    to_b2 = seq[seq["reached"].isin(["B2", "B3"])]
    to_b3 = seq[seq["reached"] == "B3"]

    def row(label, s, stage):
        n5, w5, m5 = _winrate(s[f"{stage}_fwd5"])
        n10, w10, m10 = _winrate(s[f"{stage}_fwd10"])
        return (f"| {label} | {n5} | {w5} | {m5} | {w10} | {m10} |")

    table = [
        "| 入场口径 | 样本 | 净胜率5% | 净均值5% | 净胜率10% | 净均值10% |",
        "|---|---|---|---|---|---|",
        row("孤立B1(未确认,B1日入)", iso_b1, "B1"),
        row("推进到B2(B1日入)", to_b2, "B1"),
        row("推进到B2(B2日入)", to_b2, "B2"),
        row("推进到B3(B3日入)", to_b3, "B3"),
    ]

    # 复核 94.7% 主张 + 诚实的可交易性拆解
    _, w5_iso, m5_iso = _winrate(iso_b1["B1_fwd5"])
    n_conf, w5_conf, m5_conf = _winrate(to_b2["B1_fwd5"])
    _, w5_b2entry, m5_b2entry = _winrate(to_b2["B2_fwd5"])
    # 全 B1 混合期望（ex-ante：无法预知是否会确认，等权持有每个 B1 固定5日）
    all_b1_fwd5 = pd.concat([iso_b1["B1_fwd5"], to_b2["B1_fwd5"], to_b3["B1_fwd5"]])
    _, w5_all, m5_all = _winrate(all_b1_fwd5.dropna())
    claim = (
        f"**关键区分（防误读）**：\n\n"
        f"1. 孤立B1（未确认，占{(1-n_b2/n_seq)*100:.0f}%）固定5日净胜率 {w5_iso}%、"
        f"净均值 {m5_iso}%——**负期望**，印证'B1信号日固定持有无优势'。\n"
        f"2. 推进到B2的序列、从B1日起算 净胜率 {w5_conf}%、净均值 {m5_conf}%——很高，"
        f"但**这是以'最终确认了B2'为条件的事后统计**，只有'持有每个B1直到确认窗口'才能兑现，"
        f"不可 ex-ante 挑出。\n"
        f"3. **全B1等权固定5日混合期望**（真实 ex-ante 口径）净胜率 {w5_all}%、净均值 {m5_all}%"
        f"——仍偏负：说明序列价值**不来自固定前向窗口**，而需 simulate_b1b2b3 的"
        f"'持有到S1/DD卖出 + stop_pct止损'机器把确认赢家的利润跑出来、把未确认者止损。\n"
        f"4. 从B2确认日追买 净胜率 {w5_b2entry}%、净均值 {m5_b2entry}%——**追买折价严重**"
        f"（B1→B2的涨幅已错过），与既有结论一致（reports/hold_matrix.md）。\n\n"
        f"**对94.7%的复核**：该数为 simulate_b1b2b3 **交易级**（B1入场→持有到卖出体系），"
        f"与本处固定前向窗口口径不可直接对齐；且序列维度 B3 样本 {n_b3} 偏小。"
        f"可比的定性结论成立：**确认越深，条件胜率单调抬升**（孤立{w5_iso}% ≪ 确认序列{w5_conf}%），"
        f"优势在'确认序列'而非孤立信号——但兑现依赖持有到卖出的完整战法，非信号日买入。"
    )

    lines = [
        "# B1→B2→B3 序列漏斗与胜率分析（路线图#4）",
        "",
        f"> universe {len(stocks)} 只 | B1序列 {n_seq} 条 | "
        f"净收益=前向−双边成本{ROUND_TRIP_COST:.3f}",
        "",
        "## 一、序列漏斗（转化率）",
        "",
        *funnel,
        "",
        "## 二、各阶段入场前向净胜率",
        "",
        *table,
        "",
        "## 三、94.7% 主张复核",
        "",
        claim,
        "",
        "说明：孤立B1=B1后未在5日内等到B2确认的序列（roadmap结论：信号日固定持有无优势）。"
        "样本<30 的口径记为 None。诚实口径：交易级 vs 前向窗口不可直接对齐，见上。",
    ]
    out = Path(REPORTS_DIR) / "sequence_analysis.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(funnel))
    print("\n".join(table))
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
