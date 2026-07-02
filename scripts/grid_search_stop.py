#!/usr/bin/env python3
"""B1B2B3 止损口径网格 — 攻击头号亏损源"等B2期止损过紧"（路线图 price_ticks 调优）。

背景（agent_team_backtest.md 2026-07-02）：窗口内 3700 笔 B1_stop（-1.8%均值）
吞掉大部分期望；绝对价位止损（3价位=0.03元）对高价股结构性过紧。

网格：baseline(3价位) + 价位加宽{10,30} + 百分比止损{0.5%,1%,2%,3%,5%}
指标：总体/近一年 交易数、胜率、净均值、期望和、B1_stop占比与其净贡献
选择：期望(sum_net/交易数)最优且邻域平滑（相邻参数不塌方）

用法：
    python scripts/grid_search_stop.py --sample 800            # 抽样探索
    python scripts/grid_search_stop.py --configs 0.02          # 全市场单点验证
"""

import argparse
import logging
import random
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.strategies.playbook_engine import simulate_b1b2b3  # noqa: E402
from replay_screen import load_stock  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("grid_stop")

RECENT_START = "2025-06-01"

CONFIGS = [("ticks_3(基线)", {"price_ticks": 3}),
           ("ticks_10", {"price_ticks": 10}),
           ("ticks_30", {"price_ticks": 30}),
           ("pct_0.5%", {"stop_pct": 0.005}),
           ("pct_1%", {"stop_pct": 0.01}),
           ("pct_2%", {"stop_pct": 0.02}),
           ("pct_3%", {"stop_pct": 0.03}),
           ("pct_5%", {"stop_pct": 0.05})]


def run_config(name, kw, frames):
    rows = []
    for sym, df in frames.items():
        for t in simulate_b1b2b3(df, symbol=sym, **kw):
            rows.append(t)
    tdf = pd.DataFrame(rows)
    if tdf.empty:
        return None

    def _stats(d):
        if d.empty:
            return {"n": 0, "win": float("nan"), "mean_net": float("nan"),
                    "stop_share": float("nan"), "stop_net": float("nan"),
                    "b2_win": float("nan"), "b2_n": 0}
        stop = d[d["signal_type"] == "B1_stop"]
        b2 = d[d["signal_type"].isin(["B1B2", "B1B2B3"])]
        return {"n": len(d),
                "win": float((d["net_return"] > 0).mean()),
                "mean_net": float(d["net_return"].mean()),
                "stop_share": float(len(stop) / len(d)),
                "stop_net": float(stop["net_return"].mean()) if len(stop) else 0.0,
                "b2_win": float((b2["net_return"] > 0).mean()) if len(b2) else float("nan"),
                "b2_n": len(b2)}

    full = _stats(tdf)
    recent = _stats(tdf[tdf["entry_date"] >= RECENT_START])
    return {"config": name, "full": full, "recent": recent}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--configs", nargs="*", help="只跑指定 stop_pct 值（全市场验证用）")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    files = sorted(Path(args.data_dir).glob("*.csv"))
    if args.sample:
        random.seed(42)
        files = random.sample(files, min(args.sample, len(files)))
    frames = {}
    for f in files:
        df = load_stock(f, "9999-12-31", min_rows=180)
        if df is not None:
            frames[f.stem] = df
    logger.info(f"股票 {len(frames)} 只")

    configs = CONFIGS
    if args.configs:
        configs = [(f"pct_{float(c)*100:g}%", {"stop_pct": float(c)}) for c in args.configs]
        configs.insert(0, ("ticks_3(基线)", {"price_ticks": 3}))

    lines = ["| 配置 | 交易数 | 胜率 | 净均值 | 止损占比 | 止损净均值 | B2段胜率(n) "
             "| 近1年:胜率/净均值/止损占比 |",
             "|---|---|---|---|---|---|---|---|"]
    for name, kw in configs:
        r = run_config(name, kw, frames)
        if r is None:
            continue
        f, rc = r["full"], r["recent"]
        lines.append(
            f"| {name} | {f['n']} | {f['win']*100:.1f}% | {f['mean_net']*100:+.2f}% "
            f"| {f['stop_share']*100:.0f}% | {f['stop_net']*100:+.2f}% "
            f"| {f['b2_win']*100:.1f}%({f['b2_n']}) "
            f"| {rc['win']*100:.1f}%/{rc['mean_net']*100:+.2f}%/{rc['stop_share']*100:.0f}% |")
        logger.info(lines[-1])

    out = PROJECT_ROOT / "reports" / "grid_stop_results.md"
    hdr = (f"# B1B2B3 止损口径网格（{len(frames)}只"
           f"{'抽样' if args.sample else '全市场'} · {(time.monotonic()-t0)/60:.1f}分钟）\n\n")
    out.write_text(hdr + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    logger.info(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
