#!/usr/bin/env python3
"""P1 形态战法事件研究 — 新因子上线前的强制验证。

对每个 P1 因子：把信号日当买点，统计 5/10/20 日前向收益 + Z哥纪律退出口径，
与「全体交易日基准」对比 → 胜率/均值/盈亏比不达标的因子不进评分链。

用法：
    python scripts/p1_event_study.py                     # temp_data
    python scripts/p1_event_study.py --data-dir data/day # 本地全量
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.factors import zg_advanced_patterns as zap  # noqa: E402
from alphapulse.factors import chip_laws  # noqa: E402
from compare_b1_vs_zg import load_stocks, zg_discipline_exit, fixed_hold_return  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("p1_event_study")

FACTORS = {
    "双枪DUAL_CANNON": zap.compute_dual_cannon,
    "长安CHANGAN": zap.compute_changan,
    "娜娜NANA": zap.compute_nana,
    "跃跃欲试RESTLESS": zap.compute_restless,
    "灾后重建REBUILD": zap.compute_rebuild,
    "超级B1_SUPER_B1": zap.compute_super_b1,
    "SB1假摔RECLAIM": zap.compute_sb1_reclaim,
    "筹码低位密集CHIP_LOW": chip_laws.compute_low_density,
    "筹码锁仓拉升CHIP_LIFT": chip_laws.compute_locked_lift,
}
NEGATIVE_FACTORS = {          # True=应回避 → 检验其信号日的前向收益是否确实更差
    "蜈蚣图CENTIPEDE(负面)": zap.compute_centipede,
    "筹码高位禁买CHIP_FORBID(负面)": chip_laws.compute_high_density_forbid,
}


def study(stocks: dict[str, pd.DataFrame], start: str, end: str) -> pd.DataFrame:
    rows = []
    all_fns = {**FACTORS, **NEGATIVE_FACTORS, "基准(全体交易日)": None}
    for fname, fn in all_fns.items():
        rets = {"ret_5d": [], "ret_10d": [], "ret_20d": [], "ret_zg": []}
        n_sig = 0
        for symbol, df in stocks.items():
            try:
                sig = fn(df) if fn is not None else pd.Series(True, index=df.index)
            except Exception as e:
                logger.debug(f"{fname} {symbol}: {e}")
                continue
            idx_map = {d: i for i, d in enumerate(df.index)}
            sig_days = df.index[sig.fillna(False)]
            if fn is None and len(sig_days) > 40:      # 基准抽样，控制规模
                sig_days = sig_days[::5]
            for dt in sig_days:
                d = str(dt)[:10]
                if not (start <= d <= end):
                    continue
                t = idx_map[dt]
                if t + 1 >= len(df) or t < 120:
                    continue
                n_sig += 1
                for n, key in [(5, "ret_5d"), (10, "ret_10d"), (20, "ret_20d")]:
                    r = fixed_hold_return(df, t, n)
                    if r is not None:
                        rets[key].append(r)
                rets["ret_zg"].append(zg_discipline_exit(df, t)[0])
        row = {"因子": fname, "信号数": n_sig}
        for key, label in [("ret_5d", "5日"), ("ret_10d", "10日"),
                           ("ret_20d", "20日"), ("ret_zg", "Z哥退出")]:
            s = pd.Series(rets[key])
            if len(s) < 5:
                continue
            pos, neg = s[s > 0].sum(), s[s < 0].sum()
            row[f"{label}均值%"] = round(s.mean(), 2)
            row[f"{label}胜率%"] = round((s > 0).mean() * 100, 1)
            row[f"{label}盈亏比"] = round(pos / abs(neg), 2) if neg < 0 else float("inf")
        rows.append(row)
        logger.info(f"  {fname}: {n_sig} 信号")
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="temp_data")
    ap.add_argument("--start", default="2020-07-01")
    ap.add_argument("--end", default="2026-12-31")
    args = ap.parse_args()

    data_dir = PROJECT_ROOT / args.data_dir if not Path(args.data_dir).is_absolute() else Path(args.data_dir)
    stocks = load_stocks(data_dir, args.start, args.end)
    out = study(stocks, args.start, args.end)

    md = ["# P1 形态战法事件研究", "",
          f"- 样本：{len(stocks)} 只（{args.data_dir}），{args.start} ~ {args.end}",
          "- 判定基准：与「基准(全体交易日)」行对比；正面因子应显著优于基准，负面因子应显著差于基准",
          "- ⚠️ temp_data 为案例股偏赢家样本，结论需本地全量数据复核", "",
          out.to_markdown(index=False)]
    report = "\n".join(md)
    outdir = PROJECT_ROOT / "backtest_results"
    outdir.mkdir(exist_ok=True)
    (outdir / "p1_event_study.md").write_text(report, encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()
