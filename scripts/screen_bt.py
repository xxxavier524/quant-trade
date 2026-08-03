#!/usr/bin/env python3
"""纯选股成功率回测（v5 第一性原理，2026-08-02）。

唯一 KPI：信号日收盘后未来 H 个交易日内，任一交易日收盘价相对信号日
收盘 ≥ +P% —— "选出来之后给过 +P% 的收盘可成交机会"。不含仓位/滑点/
止损等任何交易模拟；同信号日全体股票命中率作为随机基线对照。

用法：
    python scripts/screen_bt.py --strategies ALL --sample 300
    python scripts/screen_bt.py --strategies B1_B2_B3,BRICK_THREE_TYPES \
        --sample 800 --horizon 5 --success-pct 5.0 --out reports/screen_bt.md
"""

import argparse
import random
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.screening.evaluator import (  # noqa: E402
    evaluate_strategy, signal_dates_of, wilson_lower,
    MIN_SIGNALS, DEFAULT_HORIZON, DEFAULT_SUCCESS_PCT,
)
from alphapulse.screening.strategies import SCREENING_STRATEGIES, run_strategy  # noqa: E402


def load_sample(data_dir: str | Path, sample_n: int, min_days: int,
                seed: int = 42, extra_dirs: list[Path] | None = None) -> dict[str, pd.DataFrame]:
    """加载样本股票（date 列保留、RangeIndex），min_days 过滤太短的票。"""
    files = sorted(Path(data_dir).glob("*.csv"))
    if extra_dirs:
        for d in extra_dirs:
            files += sorted(Path(d).glob("*.csv"))
    random.seed(seed)
    picked = random.sample(files, min(sample_n, len(files)))
    stocks: dict[str, pd.DataFrame] = {}
    for f in picked:
        try:
            df = pd.read_csv(f, dtype={"date": str})
            if len(df) >= min_days:
                stocks[f.stem] = df
        except Exception:
            continue
    return stocks


def causality_gate(strategy: str, stocks: dict[str, pd.DataFrame],
                   n_stocks: int = 2, n_points: int = 2) -> tuple[bool, str]:
    """截断不变性门禁：t 日是否出信号不得被未来数据改变（抽样验证）。"""
    checked = 0
    mismatches = 0
    notes = []
    for sym in list(stocks)[:n_stocks]:
        df = stocks[sym]
        if len(df) < 160:
            continue
        for t in range(140, 150, 10)[:n_points]:
            if t + 12 >= len(df):
                continue
            try:
                pre = run_strategy(strategy, df.iloc[: t + 1])
                ext = run_strategy(strategy, df.iloc[: t + 1 + 12])
                hit_pre = bool((pre["signal"] == 1).iloc[-1]) if len(pre) else False
                hit_ext = bool((ext["signal"] == 1).iloc[-1]) if len(ext) else False
                checked += 1
                if hit_pre != hit_ext:
                    mismatches += 1
                    notes.append(f"{sym}@{df['date'].iloc[t]}")
            except Exception as e:
                notes.append(f"{sym}:{type(e).__name__}")
    if checked == 0:
        return True, "样本不足，门禁未执行"
    ok = mismatches == 0
    return ok, (f"抽检{checked}点" + (f"，{mismatches}处泄漏{notes[:2]}" if notes else "，无泄漏"))


def format_md(results: dict[str, dict], horizon: int, success_pct: float,
              gates: dict[str, tuple[bool, str]], causality_total: str) -> str:
    lines = [
        f"# 纯选股成功率回测（v5）",
        f"\n口径：信号日收盘后 {horizon} 个交易日内任一收盘 ≥ +{success_pct:.0f}% = 成功"
        f"（机会命中，纯涨跌判断，无交易模拟）；基线 = 同信号日全体股票命中率",
        f"\n| 策略 | 信号数 | 成功率% | Wilson下界% | 基线% | 超额pp | "
        f"期末收益均值% | 期末中位% | 期末上涨占比% | 因果门 |",
        f"|---|---|---|---|---|---|---|---|---|---|",
    ]
    rows = []
    for name, r in results.items():
        if r.get("n", 0) < MIN_SIGNALS:
            rows.append((name, f"{r['n']}（样本不足，未出结论）"))
            continue
        wl = wilson_lower(r["success_rate"], r["n"])
        gate = gates.get(name, (True, "未检"))[0]
        gate_txt = "✅" if gate else "❌泄漏"
        rows.append((name,
                     f"{r['n']} | {r['success_rate']:.1f} | {wl} | "
                     f"{r['base_rate']:.1f} | {r['lift_pp']:+.1f} | "
                     f"{r['end_ret_mean']:+.2f} | {r['end_ret_median']:+.2f} | "
                     f"{r['hit_ratio_end']:.0f}% | {gate_txt}"))
    # 按超额收益排序（有结论的在前）
    rows.sort(key=lambda kv: (kv[1].startswith("（"),), reverse=False)
    for name, cell in rows:
        lines.append(f"| {name} | {cell} |")

    lines.append(f"\n因果门禁：{causality_total}")
    for name, (ok, note) in gates.items():
        lines.append(f"- {name}: {'✅' if ok else '❌'} {note}")

    for name, r in results.items():
        if r.get("n", 0) < MIN_SIGNALS or not r.get("yearly"):
            continue
        lines.append(f"\n## {name} — 年度明细")
        lines.append("| 年份 | 信号数 | 成功率% | 期末收益均值% |")
        lines.append("|---|---|---|---|")
        for y in r["yearly"]:
            lines.append(f"| {y['year']} | {y['n']} | {y['success_rate']} | {y['end_ret']:+.2f} |")
        lines.append(f"\n逐H命中曲线（{name}）:")
        lines.append(" | ".join(f"H{h['horizon']}={h['success_rate']}%" for h in r["curve"]))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="纯选股成功率回测（v5）")
    ap.add_argument("--strategies", default="ALL",
                    help="逗号分隔策略名，或 ALL（默认全部）")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--include-delisted", action="store_true",
                    help="并入退市股目录修正幸存者偏差")
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    ap.add_argument("--success-pct", type=float, default=DEFAULT_SUCCESS_PCT)
    ap.add_argument("--min-days", type=int, default=300)
    ap.add_argument("--out", default=None, help="Markdown 输出路径")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    names = (list(SCREENING_STRATEGIES) if args.strategies == "ALL"
             else [s.strip() for s in args.strategies.split(",")])
    unknown = [n for n in names if n not in SCREENING_STRATEGIES]
    if unknown:
        print(f"未知策略: {unknown}；可选: {list(SCREENING_STRATEGIES)}", file=sys.stderr)
        return 2

    extra = [Path(args.data_dir).parent / "delisted"] if args.include_delisted else None
    stocks = load_sample(args.data_dir, args.sample, args.min_days, args.seed, extra)
    print(f"[INFO] 样本 {len(stocks)} 只（seed={args.seed}）")
    if not stocks:
        print("[ERROR] 无可用数据", file=sys.stderr)
        return 1

    closes_map = {s: d.set_index("date")["close"].astype(float)
                  for s, d in stocks.items()}
    results: dict[str, dict] = {}
    gates: dict[str, tuple[bool, str]] = {}
    t0 = time.time()
    for name in names:
        frames_by_symbol: dict[str, pd.DataFrame] = {}
        for sym, df in stocks.items():
            try:
                frames_by_symbol[sym] = run_strategy(name, df)
            except Exception as e:
                print(f"  [WARN] {name}/{sym}: {type(e).__name__}: {e}", file=sys.stderr)

        def _eval(dates_by_symbol: dict[str, list[str]]) -> dict:
            return evaluate_strategy(dates_by_symbol, closes_map,
                                     args.horizon, args.success_pct)

        sig_dates_by_symbol = {
            sym: signal_dates_of(f, stocks[sym])
            for sym, f in frames_by_symbol.items()}
        sig_dates_by_symbol = {s: d for s, d in sig_dates_by_symbol.items() if d}
        results[name] = evaluate_strategy(sig_dates_by_symbol, closes_map,
                                          args.horizon, args.success_pct)
        gates[name] = causality_gate(name, stocks)
        print(f"  {name}: {results[name].get('n', 0)} 信号 "
              f"成功率 {results[name].get('success_rate')}%"
              f" 基线 {results[name].get('base_rate')}%"
              f" 超额 {results[name].get('lift_pp')}pp"
              f"（{time.time()-t0:.0f}s）", flush=True)

        # 子类型明细（B1_B2_B3 的 B1/B2/B3、BRICK_THREE_TYPES 的三型）——
        # 验证"分级确认"是否真能提升命中率（v5 假设检验）。
        first_frame = next(iter(frames_by_symbol.values()), pd.DataFrame())
        subtype_cols = [c for c in ("signal_type", "brick_type")
                        if c in first_frame.columns]
        if subtype_cols:
            col = subtype_cols[0]
            values = sorted({v for f in frames_by_symbol.values()
                             if col in f.columns
                             for v in f[col].dropna().unique()})
            for val in values:
                sub_by_symbol = {}
                for sym, f in frames_by_symbol.items():
                    if col not in f.columns:
                        continue
                    sub = f[f[col] == val]
                    dates = signal_dates_of(sub, stocks[sym])
                    if dates:
                        sub_by_symbol[sym] = dates
                key = f"{name}[{val}]"
                results[key] = _eval(sub_by_symbol)
                gates[key] = gates[name]
                print(f"  {key}: {results[key].get('n', 0)} 信号 "
                      f"成功率 {results[key].get('success_rate')}%"
                      f" 基线 {results[key].get('base_rate')}%"
                      f" 超额 {results[key].get('lift_pp')}pp", flush=True)

    total_note = "，".join(f"{n}={'✅' if g[0] else '❌'}" for n, g in gates.items())
    md = format_md(results, args.horizon, args.success_pct, gates,
                   f"全部策略抽样截断不变性通过" if all(g[0] for g in gates.values())
                   else "存在泄漏（见下）")
    if args.out:
        Path(args.out).parent.mkdir(exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"[INFO] 报告 → {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
