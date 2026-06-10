"""历史日全市场选股回放 — Phase 0 黄金案例回归的核心工具。

将数据切片到指定交易日（含当日，杜绝未来函数），对全市场跑通达信公式翻译，
输出命中清单；可与黄金案例对比生成 命中/漏选/多选 报告，漏选股逐条件诊断。

流通市值从 CSV 换手率反推：float_shares = volume / (turnover/100)，
market_cap = close * float_shares（单位元，逐日精确，无需网络）。

用法：
    # 2026-05-15（周五，对应通达信导出"20260517"）回放两公式并集
    python scripts/replay_screen.py --date 2026-05-15 --formula union \\
        --golden tests/golden/golden_20260517.csv

    # 单公式 + 指定股票逐条件诊断
    python scripts/replay_screen.py --date 2026-05-15 --formula b1 --diagnose 603618,605318

    # 区间逐日回放定位案例信号日
    python scripts/replay_screen.py --start 2026-03-01 --end 2026-05-15 \\
        --formula union --watch tests/golden/golden_2604.csv
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.factors import b1_formula, volume_b1  # noqa: E402

REPORTS_DIR = PROJECT_ROOT / "reports"

FORMULAS = ("b1", "volume_b1", "union")


def load_stock(csv_path: Path, end_date: str, min_rows: int = 60) -> pd.DataFrame | None:
    """读取单只股票并切片到 end_date（含），注入流通市值列。"""
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None
    if "date" not in df.columns or len(df) < min_rows:
        return None
    df = df[df["date"] <= end_date]
    if len(df) < min_rows:
        return None
    turn = pd.to_numeric(df["turnover"], errors="coerce").replace(0, np.nan) if "turnover" in df.columns else pd.Series(np.nan, index=df.index)
    float_shares = (df["volume"] / (turn / 100)).ffill()
    df["market_cap"] = df["close"] * float_shares
    return df.reset_index(drop=True)


def signal_on_last_day(df: pd.DataFrame, formula: str, target_date: str) -> dict | None:
    """计算公式信号；仅当最后一行恰为目标日（当日有交易）时有效。"""
    if df.iloc[-1]["date"] != target_date:
        return None
    out = {}
    if formula in ("b1", "union"):
        out["b1"] = bool(b1_formula.compute(df).iloc[-1])
    if formula in ("volume_b1", "union"):
        out["volume_b1"] = bool(volume_b1.compute(df).iloc[-1])
    out["hit"] = any(v for k, v in out.items() if k != "hit")
    return out


def run_screen(date: str, formula: str, data_dir: Path) -> pd.DataFrame:
    """全市场回放，返回每只股票的信号结果。"""
    rows = []
    files = sorted(data_dir.glob("*.csv"))
    print(f"扫描 {len(files)} 只股票 @ {date} ({formula}) ...")
    for i, f in enumerate(files):
        if i % 1000 == 0 and i > 0:
            print(f"  ... {i}/{len(files)}")
        df = load_stock(f, date)
        if df is None:
            continue
        res = signal_on_last_day(df, formula, date)
        if res is None:
            continue
        rows.append({"symbol": f.stem, **res})
    return pd.DataFrame(rows)


def diagnose(symbols: list[str], date: str, data_dir: Path) -> None:
    """对指定股票输出两公式的逐条件明细（最后一行）。"""
    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        df = load_stock(path, date)
        print(f"\n===== {sym} @ {date} =====")
        if df is None:
            print("  无数据或历史不足")
            continue
        if df.iloc[-1]["date"] != date:
            print(f"  当日无交易（最后交易日 {df.iloc[-1]['date']}）")
            continue
        mv = df.iloc[-1]["market_cap"]
        print(f"  流通市值 ≈ {mv/1e8:.1f} 亿")
        b1_det = b1_formula.compute_detail(df).iloc[-1]
        print("  [B1公式]", " | ".join(
            f"{k}={v}" for k, v in b1_det.items()))
        v_det = volume_b1.compute_detail(df).iloc[-1]
        print("  [量能B1]", " | ".join(f"{k}={v}" for k, v in v_det.items()))
        v_sig = volume_b1.compute(df).iloc[-1]
        print(f"  量能B1 signal={bool(v_sig)}")


def compare_golden(result: pd.DataFrame, golden_path: Path, date: str, formula: str) -> None:
    """与黄金案例对比：命中/漏选/多选。"""
    golden = pd.read_csv(golden_path, dtype={"symbol": str})
    golden_syms = set(golden["symbol"].str.zfill(6))
    hits = set(result.loc[result["hit"], "symbol"])
    matched = golden_syms & hits
    missed = golden_syms - hits
    extra = hits - golden_syms
    print(f"\n========== 黄金案例对比 @ {date} ({formula}) ==========")
    print(f"黄金案例: {len(golden_syms)} 只 | 程序命中: {len(hits)} 只")
    print(f"✅ 命中 {len(matched)}/{len(golden_syms)} = {len(matched)/len(golden_syms)*100:.0f}%")
    name_map = dict(zip(golden["symbol"].str.zfill(6), golden["name"]))
    if matched:
        print("命中:", " ".join(sorted(s + name_map.get(s, "") for s in matched)))
    if missed:
        print("❌ 漏选:", " ".join(sorted(s + name_map.get(s, "") for s in missed)))
    if extra:
        print(f"⚠️ 多选 {len(extra)} 只:", " ".join(sorted(extra)[:40]), "..." if len(extra) > 40 else "")


def watch_range(start: str, end: str, formula: str, data_dir: Path, watch_path: Path) -> None:
    """区间逐日回放：定位关注股票各自的信号日。"""
    watch = pd.read_csv(watch_path, dtype={"symbol": str})
    watch_syms = list(watch["symbol"].str.zfill(6))
    name_map = dict(zip(watch["symbol"].str.zfill(6), watch["name"]))
    print(f"在 {start} ~ {end} 区间为 {len(watch_syms)} 只案例股定位信号日 ...")
    found: dict[str, list[str]] = {s: [] for s in watch_syms}
    for sym in watch_syms:
        path = data_dir / f"{sym}.csv"
        full = load_stock(path, end)
        if full is None:
            print(f"  {sym}{name_map.get(sym, '')}: 无数据")
            continue
        dates = [d for d in full["date"] if start <= d <= end]
        for d in dates:
            df = full[full["date"] <= d]
            if len(df) < 60:
                continue
            res = signal_on_last_day(df.reset_index(drop=True), formula, d)
            if res and res["hit"]:
                tags = [k for k in ("b1", "volume_b1") if res.get(k)]
                found[sym].append(f"{d}({'+'.join(tags)})")
    print("\n========== 信号日定位结果 ==========")
    for sym in watch_syms:
        days = found[sym]
        status = " ".join(days) if days else "（区间内无信号）"
        print(f"  {sym} {name_map.get(sym, ''):8s}: {status}")


def main():
    ap = argparse.ArgumentParser(description="历史日全市场选股回放")
    ap.add_argument("--date", help="回放日 YYYY-MM-DD")
    ap.add_argument("--start", help="区间起（与 --watch 配合）")
    ap.add_argument("--end", help="区间止")
    ap.add_argument("--formula", choices=FORMULAS, default="union")
    ap.add_argument("--golden", help="黄金案例CSV路径，对比命中率")
    ap.add_argument("--watch", help="关注股票CSV，区间逐日定位信号日")
    ap.add_argument("--diagnose", help="逗号分隔股票代码，输出逐条件明细")
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--out", help="结果CSV输出路径")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        sys.exit(f"数据目录不存在: {data_dir}（外接硬盘未挂载？）")

    if args.diagnose:
        if not args.date:
            sys.exit("--diagnose 需要 --date")
        diagnose([s.strip() for s in args.diagnose.split(",")], args.date, data_dir)
        return

    if args.watch:
        if not (args.start and args.end):
            sys.exit("--watch 需要 --start/--end")
        watch_range(args.start, args.end, args.formula, data_dir, Path(args.watch))
        return

    if not args.date:
        sys.exit("需要 --date")

    result = run_screen(args.date, args.formula, data_dir)
    hits = result[result["hit"]]
    print(f"\n共命中 {len(hits)} 只: {' '.join(sorted(hits['symbol']))}")

    out = args.out or str(REPORTS_DIR / f"replay_{args.date}_{args.formula}.csv")
    result.to_csv(out, index=False)
    print(f"结果已存 {out}")

    if args.golden:
        compare_golden(result, Path(args.golden), args.date, args.formula)


if __name__ == "__main__":
    main()
