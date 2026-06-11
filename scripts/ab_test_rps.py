"""AB验证：B1信号 加/不加 RPS下限过滤 的胜率对比（融合验证，路线图#1）。

方法：收集 B1 全历史信号事件 → 计算每个事件日的 RPS120（历史截面，无泄漏）
→ 按 RPS 阈值分组对比 5/10 日前向净收益与胜率。

用法：python scripts/ab_test_rps.py --sample 800
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.backtest.signal_validator import collect_signal_events, ROUND_TRIP_COST  # noqa: E402
from alphapulse.factors.rps import build_close_panel, rps_panel  # noqa: E402
from validate_signal import load_universe  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--factor", default="B1_FORMULA")
    ap.add_argument("--period", type=int, default=120)
    ap.add_argument("--thresholds", default="0,40,50,60,70")
    args = ap.parse_args()

    stocks = load_universe(Path(DATA_DIR), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")

    print("收集B1信号事件...")
    events = collect_signal_events(args.factor, stocks, forward_days=[5, 10])
    print(f"事件: {len(events)} 条")

    print("构建历史RPS面板（截面无泄漏）...")
    panel = build_close_panel(stocks, lookback=2000)
    rps = rps_panel(panel, args.period)

    # 事件日RPS查表（向量化：long表join）
    rps_long = rps.stack().rename("rps").reset_index()
    rps_long.columns = ["date", "symbol", "rps"]
    ev = events.merge(rps_long, on=["date", "symbol"], how="left").dropna(subset=["rps"])
    print(f"匹配到RPS的事件: {len(ev)} 条\n")

    rows = []
    for th in [float(x) for x in args.thresholds.split(",")]:
        sub = ev[ev["rps"] >= th]
        if len(sub) < 200:
            continue
        for w in (5, 10):
            col = sub[f"fwd_{w}"].dropna()
            net = col - ROUND_TRIP_COST
            rows.append({
                "RPS下限": int(th), "窗口": f"{w}日", "样本": len(col),
                "净胜率%": round(float((net > 0).mean() * 100), 1),
                "净均值%": round(float(net.mean() * 100), 2),
                "中位%": round(float(col.median() * 100), 2),
            })
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    p = PROJECT_ROOT / "backtest_results" / f"ab_rps_{args.factor}.csv"
    out.to_csv(p, index=False, encoding="utf-8-sig")
    print(f"\n已存 {p}")


if __name__ == "__main__":
    main()
