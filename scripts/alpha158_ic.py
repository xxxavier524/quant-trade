#!/usr/bin/env python3
"""Alpha158 批量 IC 扫描（路线图#3 验收第二项）。

协议（与 ic_weight_tuning 同口径）：
1. 抽样股票全历史 → 每股 compute_alpha158 + fwd5（未来5日收益）
2. 近 --window 交易日逐日截面 Spearman IC → mean IC / ICIR / 覆盖天数
3. 输出 reports/alpha158_ic.md（|meanIC| 排序全表 + Top20 摘要）
   + reports/alpha158_ic.json（供 LGBM 特征筛选复用）

用法：python scripts/alpha158_ic.py --sample 600
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR, REPORTS_DIR  # noqa: E402
from alphapulse.factors.alpha158 import ALPHA158, compute_alpha158  # noqa: E402
from ic_weight_tuning import daily_ic  # noqa: E402
from replay_screen import load_stock  # noqa: E402


def build_panel(frames: dict, window: int) -> pd.DataFrame:
    parts = []
    for i, (sym, df) in enumerate(frames.items()):
        if i % 100 == 0 and i:
            print(f"  因子帧 {i}/{len(frames)}")
        try:
            p = compute_alpha158(df).astype(np.float32)
        except Exception as e:  # noqa: BLE001 单股脏数据不阻塞整体
            print(f"  跳过 {sym}: {e}")
            continue
        close = df["close"].astype(float)
        p["fwd5"] = (close.shift(-5) / close - 1).values
        p["date"] = df["date"].astype(str).values
        p["symbol"] = sym
        parts.append(p.tail(window).dropna(subset=["fwd5"]))
    return pd.concat(parts, ignore_index=True)


def write_report(ic: pd.DataFrame, meta: dict, out_md: Path, out_json: Path) -> None:
    ic_sorted = ic.reindex(ic["mean_ic"].abs().sort_values(ascending=False).index)
    top20 = ic_sorted.head(20)

    lines = [
        "# Alpha158 批量 IC 报告",
        "",
        f"> 生成: {meta['date']} | 样本 {meta['n_stocks']} 只 | "
        f"面板 {meta['n_rows']} 股日 · {meta['n_days']} 交易日 | "
        f"标的收益 fwd5 | 日截面 Spearman",
        "",
        f"IC 概览：|meanIC|≥0.02 的因子 {int((ic['mean_ic'].abs() >= 0.02).sum())} 个；"
        f"|ICIR|≥0.3 的因子 {int((ic['icir'].abs() >= 0.3).sum())} 个（共158）",
        "",
        "## Top 20（按 |meanIC|）",
        "",
        "| 因子 | meanIC | ICIR | 覆盖天数 |",
        "|---|---|---|---|",
    ]
    for name, row in top20.iterrows():
        lines.append(f"| {name} | {row['mean_ic']:+.4f} | {row['icir']:+.3f} "
                     f"| {int(row['days'])} |")
    lines += [
        "",
        "说明：正IC=因子值越大未来5日收益越高。本体系以均值回归/底部挖掘为主，",
        "负IC动量类因子（如高RANK/ROC反向）同样有信息量，入LGBM时保留符号即可。",
        "",
        "## 全表（158因子，|meanIC| 降序）",
        "",
        "| 因子 | meanIC | ICIR | 覆盖天数 |",
        "|---|---|---|---|",
    ]
    for name, row in ic_sorted.iterrows():
        lines.append(f"| {name} | {row['mean_ic']:+.4f} | {row['icir']:+.3f} "
                     f"| {int(row['days'])} |")
    out_md.write_text("\n".join(lines) + "\n")

    payload = {"meta": meta,
               "ic": {k: {"mean_ic": round(float(v["mean_ic"]), 5),
                          "icir": round(float(v["icir"]), 4),
                          "days": int(v["days"])}
                      for k, v in ic.iterrows()}}
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=600)
    ap.add_argument("--window", type=int, default=500, help="近N交易日")
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    t0 = time.monotonic()
    files = sorted(Path(args.data_dir).glob("*.csv"))
    if not files:
        print(f"数据目录无CSV: {args.data_dir}")
        return 1
    random.seed(args.seed)
    files = random.sample(files, min(args.sample, len(files)))
    frames = {}
    for f in files:
        df = load_stock(f, "9999-12-31", min_rows=180)
        if df is not None:
            frames[f.stem] = df
    print(f"样本 {len(frames)} 只")

    panel = build_panel(frames, args.window)
    n_days = panel["date"].nunique()
    print(f"面板 {len(panel)} 股日 · {n_days} 交易日")

    factor_cols = list(ALPHA158)
    ic = daily_ic(panel, factor_cols)

    meta = {"date": pd.Timestamp.today().strftime("%Y-%m-%d"),
            "n_stocks": len(frames), "n_rows": len(panel),
            "n_days": n_days, "window": args.window, "seed": args.seed}
    out_md = Path(REPORTS_DIR) / "alpha158_ic.md"
    out_json = Path(REPORTS_DIR) / "alpha158_ic.json"
    write_report(ic, meta, out_md, out_json)

    print("\n=== Top 10（|meanIC|）===")
    top = ic.reindex(ic["mean_ic"].abs().sort_values(ascending=False).index).head(10)
    print(top.round(4).to_string())
    print(f"\n→ {out_md}\n→ {out_json}")
    print(f"耗时 {(time.monotonic() - t0) / 60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    sys.exit(main())
