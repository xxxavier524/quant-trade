#!/usr/bin/env python3
"""K线包含合并预处理 — 生产信号专项AB（D4，2026-07-12）。

问题：kline_merge（缠论合并去毛刺）此前的AB是研究性正结果，但从未在
【生产严格信号 + 实盘评价口径】上验证过，不能凭研究结论直接上生产。

设计：
- 样本 1000 只（seed=123），评价期 2024-01-01 ~ 2025-12-31
- 两臂：raw（原始K线）vs merged（合并预处理后生成信号）
- 两个生产信号：知行超短(zhixing_trend.compute_ultra) / 砖型图(BRICK_THREE_TYPES，
  用 composite 生产参数)
- 前向评价永远在【原始收盘价】上算（合并只影响信号生成，不改真实成交价格）：
  信号后5个交易日内最高收盘 ≥ +5% 记成功——与 signal_tracker 实盘口径同源
- 判定：merged 相对 raw 成功率 ≥ +2pp 且双比例z检验 z ≥ 2 → 建议接入（配置开关）；
  否则保持不接，报告如实入账

用法：python scripts/ab_kline_merge_prod.py [--sample 1000]
输出：reports/ab_kline_merge_prod.md
"""

import argparse
import math
import random
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.utils.kline_merge import merge_klines  # noqa: E402
from alphapulse.factors import zhixing_trend  # noqa: E402
from alphapulse.strategies import brick_three_types  # noqa: E402
from alphapulse.ranking.composite import _brick3_params  # noqa: E402
from scripts.walk_forward import forward_success  # noqa: E402

EVAL_START, EVAL_END = "2024-01-01", "2025-12-31"


def zhixing_dates(df: pd.DataFrame) -> list[str]:
    """知行超短信号日（bool Series 按行对齐输入帧）。"""
    try:
        s = zhixing_trend.compute_ultra(df)
    except Exception:
        return []
    fired = df.loc[s.to_numpy(dtype=bool), "date"] if len(s) == len(df) else []
    return [str(d)[:10] for d in fired]


def brick_dates(df: pd.DataFrame) -> list[str]:
    """砖型图信号日（信号帧索引=输入行标签，经date列映射回日期）。"""
    try:
        sig = brick_three_types.generate_signals(df, **_brick3_params())
    except Exception:
        return []
    if sig.empty:
        return []
    sig = sig[sig["signal"] == 1]
    return [str(d)[:10] for d in df["date"].reindex(sig.index).dropna()]


def two_prop_z(s1, n1, s2, n2) -> float:
    """双比例z检验（merged vs raw）。"""
    if n1 == 0 or n2 == 0:
        return 0.0
    p1, p2 = s1 / n1, s2 / n2
    p = (s1 + s2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return (p1 - p2) / se if se > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1000)
    args = ap.parse_args()

    files = sorted(Path(DATA_DIR).glob("*.csv"))
    random.seed(123)
    picked = random.sample(files, min(args.sample, len(files)))

    arms = {("zhixing", "raw"): [], ("zhixing", "merged"): [],
            ("brick", "raw"): [], ("brick", "merged"): []}
    t0 = time.time()
    n_used = 0
    for i, f in enumerate(picked, 1):
        try:
            df = pd.read_csv(f, dtype={"date": str})
        except Exception:
            continue
        if len(df) < 300:
            continue
        n_used += 1
        closes = df.set_index("date")["close"].astype(float)
        merged, _ = merge_klines(df)

        for sig_name, fn in [("zhixing", zhixing_dates), ("brick", brick_dates)]:
            for arm_name, frame in [("raw", df), ("merged", merged)]:
                dates = [d for d in fn(frame) if EVAL_START <= d <= EVAL_END]
                # 前向收益永远在原始收盘价上评价
                arms[(sig_name, arm_name)].extend(forward_success(dates, closes))
        if i % 200 == 0:
            print(f"  ... {i}/{len(picked)} ({time.time()-t0:.0f}s)", flush=True)

    md = [f"# K线合并预处理 生产AB（{EVAL_START}~{EVAL_END}）",
          f"\n样本 {n_used} 只(seed=123) | 口径: 信号后5日内最高收盘≥+5% | "
          f"前向收益均在原始价格上评价\n",
          "| 信号 | 臂 | 信号数 | 成功率 | 平均5日收 | Δ成功率 | z |",
          "|---|---|---|---|---|---|---|"]
    verdicts = {}
    for sig_name in ("zhixing", "brick"):
        res = {}
        for arm_name in ("raw", "merged"):
            rows = arms[(sig_name, arm_name)]
            n = len(rows)
            s = sum(r["success"] for r in rows)
            avg = (sum(r["end_ret"] for r in rows) / n) if n else 0.0
            res[arm_name] = (s, n, avg)
        (s_r, n_r, a_r), (s_m, n_m, a_m) = res["raw"], res["merged"]
        rate_r = s_r / n_r if n_r else 0.0
        rate_m = s_m / n_m if n_m else 0.0
        z = two_prop_z(s_m, n_m, s_r, n_r)
        md.append(f"| {sig_name} | raw | {n_r} | {rate_r:.1%} | {a_r:+.2f}% | — | — |")
        md.append(f"| {sig_name} | merged | {n_m} | {rate_m:.1%} | {a_m:+.2f}% "
                  f"| {(rate_m-rate_r)*100:+.1f}pp | {z:.2f} |")
        verdicts[sig_name] = {"delta_pp": (rate_m - rate_r) * 100, "z": z,
                              "n_raw": n_r, "n_merged": n_m}

    md.append("\n## 判定（接入门槛: Δ≥+2pp 且 z≥2）\n")
    for sig_name, v in verdicts.items():
        ok = v["delta_pp"] >= 2.0 and v["z"] >= 2.0
        md.append(f"- **{sig_name}**: Δ={v['delta_pp']:+.1f}pp, z={v['z']:.2f} → "
                  f"{'✅ 建议接入(配置开关)' if ok else '❌ 不接入，保持原始K线'}")

    out = PROJECT_ROOT / "reports" / "ab_kline_merge_prod.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"报告 → {out}")
    print("\n".join(md[-4:]))


if __name__ == "__main__":
    main()
