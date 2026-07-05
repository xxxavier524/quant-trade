#!/usr/bin/env python3
"""多周期持有验证矩阵（路线图 #11）— 用数据定 B2确认 后的最优持有期。

对全部 B2确认日（patterns.pattern_state_series 状态机首日），计算固定持有
N∈{1..20} 日的收益矩阵（胜率/均值/每持有日收益），并与卖出体系（S1/DD，
run_playbook B1B2 段）对照——回答两个问题：
1. B3 锁仓最优天数是多少？
2. 卖出体系是否跑赢最优固定持有？（若否，卖出规则需要重审）

用法：python scripts/hold_matrix.py [--sample 800]
输出：reports/hold_matrix.md
"""

import argparse
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.agent_team.patterns import (  # noqa: E402
    pattern_state_series, STATE_B2_CONFIRM, STATE_NEEDLE)
from replay_screen import load_stock  # noqa: E402

MAX_N = 20


def episode_starts(state: np.ndarray, target: int) -> np.ndarray:
    """状态段首日索引（进入 target 态的第一天，避免同一段重复计数）。"""
    is_t = state == target
    prev = np.roll(is_t, 1)
    prev[0] = False
    return np.flatnonzero(is_t & ~prev)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--start", default="2023-01-01", help="episode 起始日下限")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    files = sorted(Path(args.data_dir).glob("*.csv"))
    random.seed(42)
    files = random.sample(files, min(args.sample, len(files)))

    rets = {n: [] for n in range(1, MAX_N + 1)}          # B2确认
    rets_nd = {n: [] for n in range(1, MAX_N + 1)}       # 单针（参考）
    n_ep = n_stocks = 0
    for f in files:
        df = load_stock(f, "9999-12-31", min_rows=180)
        if df is None:
            continue
        n_stocks += 1
        close = df["close"].astype(float).values
        dates = df["date"].astype(str).values
        state = pattern_state_series(df)
        for target, bucket in [(STATE_B2_CONFIRM, rets), (STATE_NEEDLE, rets_nd)]:
            for i in episode_starts(state, target):
                if dates[i] < args.start or i + 1 >= len(close):
                    continue
                if target == STATE_B2_CONFIRM:
                    n_ep += 1
                for n in range(1, MAX_N + 1):
                    if i + n < len(close):
                        bucket[n].append(close[i + n] / close[i] - 1.0)

    lines = [f"# 多周期持有矩阵（B2确认日起，{n_stocks}只抽样 · "
             f"episode≥{args.start} · {n_ep}段）\n",
             "| N日 | 胜率 | 均值 | 每持有日 | 单针参考:胜率/均值 |",
             "|---|---|---|---|---|"]
    best_n, best_pd = 0, -9e9
    for n in range(1, MAX_N + 1):
        r = np.array(rets[n])
        if not len(r):
            continue
        pd_ret = r.mean() / n
        if pd_ret > best_pd:
            best_pd, best_n = pd_ret, n
        nd = np.array(rets_nd[n]) if rets_nd[n] else np.array([np.nan])
        lines.append(f"| {n} | {(r>0).mean()*100:.1f}% | {r.mean()*100:+.2f}% "
                     f"| {pd_ret*100:+.3f}% "
                     f"| {(nd>0).mean()*100:.0f}%/{np.nanmean(nd)*100:+.2f}% |")

    r_best = np.array(rets[best_n])
    lines += [f"\n**最优固定持有 N={best_n} 日**：均值 {r_best.mean()*100:+.2f}%、"
              f"每持有日 {best_pd*100:+.3f}%（{len(r_best)}段）",
              "\n> 对照：卖出体系（S1/DD+灾难止损）B1B2段 全市场 +5.04%/约9日持有"
              "≈每持有日+0.56%…（口径差异：那是B1入场起算含等待期；本矩阵从B2确认日起算。"
              "结论以每持有日与胜率的联合判断为准，见下）"]
    out = PROJECT_ROOT / "reports" / "hold_matrix.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n耗时 {(time.monotonic()-t0)/60:.1f} 分钟 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
