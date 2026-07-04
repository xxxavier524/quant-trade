"""三大战法状态机回测 CLI。

用法：
    python scripts/run_playbook.py --playbook B1B2B3 --sample 500
    python scripts/run_playbook.py --playbook ALL --start 2024-01-01
"""

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.strategies.playbook_engine import PLAYBOOKS, summarize_trades  # noqa: E402
from validate_signal import load_universe  # noqa: E402

RESULTS_DIR = PROJECT_ROOT / "backtest_results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playbook", default="ALL", choices=[*PLAYBOOKS, "ALL"])
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="9999-12-31")
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--stop-pct", type=float, default=None,
                    help="B1B2B3 百分比止损；缺省读 config/best_params.json "
                         "PLAYBOOK_B1B2B3.stop_pct（网格调优值0.10），传 0 用旧绝对价位")
    args = ap.parse_args()

    # B1B2B3 调优参数：CLI 显式 > best_params（stop_pct/b2_wait/b2_vol_mult）
    b1b2b3_kw = {}
    try:
        bp = json.loads((PROJECT_ROOT / "config" / "best_params.json").read_text())
        tuned = bp.get("PLAYBOOK_B1B2B3", {})
        b1b2b3_kw = {k: tuned[k] for k in ("stop_pct", "b2_wait", "b2_vol_mult")
                     if k in tuned}
    except Exception:
        pass
    if args.stop_pct is not None:
        if args.stop_pct == 0:
            b1b2b3_kw.pop("stop_pct", None)
        else:
            b1b2b3_kw["stop_pct"] = args.stop_pct
    if b1b2b3_kw:
        print(f"B1B2B3 调优参数: {b1b2b3_kw}（best_params 网格）")

    stocks = load_universe(Path(args.data_dir), args.sample, args.end)
    print(f"universe: {len(stocks)} 只")

    names = [args.playbook] if args.playbook != "ALL" else list(PLAYBOOKS)
    RESULTS_DIR.mkdir(exist_ok=True)
    for name in names:
        fn = PLAYBOOKS[name]
        t0 = time.monotonic()
        all_trades = []
        kw = b1b2b3_kw if name == "B1B2B3" else {}
        for sym, df in stocks.items():
            try:
                all_trades += fn(df, symbol=sym, **kw)
            except Exception:
                continue
        all_trades = [t for t in all_trades if args.start <= t["entry_date"] <= args.end]
        stats = summarize_trades(all_trades)
        print(f"\n===== {name}（{(time.monotonic()-t0)/60:.1f}分钟）=====")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        if all_trades:
            pd.DataFrame(all_trades).to_csv(
                RESULTS_DIR / f"playbook_{name}_trades.csv", index=False, encoding="utf-8-sig")
            (RESULTS_DIR / f"playbook_{name}_stats.json").write_text(
                json.dumps(stats, ensure_ascii=False, indent=2))
            print(f"逐笔交易已存 backtest_results/playbook_{name}_trades.csv")


if __name__ == "__main__":
    main()
