"""信号胜率验证 CLI — 验证经验、调参的日常工具。

用法：
    # 验证 B1 公式全历史表现
    python scripts/validate_signal.py --factor B1_FORMULA

    # 改参数验证（J阈值15）
    python scripts/validate_signal.py --factor B1_FORMULA --params '{"j_threshold": 15}'

    # 限定时间段与样本
    python scripts/validate_signal.py --factor VOLUME_B1 --start 2024-01-01 --sample 1000
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.backtest.signal_validator import validate_signal, save_result  # noqa: E402
from replay_screen import load_stock  # noqa: E402


def load_universe(data_dir: Path, sample: int | None, end: str) -> dict:
    files = sorted(data_dir.glob("*.csv"))
    if sample:
        import random
        random.seed(42)
        files = random.sample(files, min(sample, len(files)))
    stocks = {}
    for i, f in enumerate(files):
        if i % 1000 == 0 and i:
            print(f"  加载 {i}/{len(files)} ...")
        df = load_stock(f, end, min_rows=120)
        if df is not None:
            stocks[f.stem] = df
    return stocks


def fmt_report(r: dict) -> str:
    lines = [f"\n===== 信号验证: {r['factor']} {r['params'] or ''} =====",
             f"信号总数 {r.get('n_signals', 0)} | 覆盖 {r.get('n_symbols', 0)} 只 | "
             f"区间 {' ~ '.join(r.get('date_range', ['-', '-']))}",
             "\n窗口 | 样本 | 胜率 | 净胜率 | 均值 | 净均值 | 中位 | P10 | P90",
             "---- | ---- | ---- | ------ | ---- | ------ | ---- | --- | ---"]
    for n, w in r.get("windows", {}).items():
        lines.append(f"{n}日 | {w['n']} | {w['win_rate']*100:.1f}% | {w['win_rate_net']*100:.1f}% "
                     f"| {w['mean']*100:+.2f}% | {w['mean_net']*100:+.2f}% "
                     f"| {w['median']*100:+.2f}% | {w['p10']*100:+.1f}% | {w['p90']*100:+.1f}%")
    if r.get("by_year"):
        lines.append("\n逐年（5日窗口）: " + " | ".join(
            f"{y}:{v['win_rate']*100:.0f}%({v['n']})" for y, v in sorted(r["by_year"].items())))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", required=True)
    ap.add_argument("--params", default=None, help='JSON，如 \'{"j_threshold": 15}\'')
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="9999-12-31")
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--forward-days", default="1,3,5,10,20")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        sys.exit(f"数据目录不存在: {data_dir}")

    params = json.loads(args.params) if args.params else None
    fwd = [int(x) for x in args.forward_days.split(",")]

    stocks = load_universe(data_dir, args.sample, args.end)
    print(f"universe: {len(stocks)} 只")

    result = validate_signal(args.factor, stocks, params, fwd, args.start, args.end)
    print(fmt_report(result))
    p = save_result(result)
    print(f"\n结果已存 {p}")


if __name__ == "__main__":
    main()
