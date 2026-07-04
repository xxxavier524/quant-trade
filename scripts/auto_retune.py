#!/usr/bin/env python3
"""每周自动回测调参（无人值守，launchd 周日 04:00）。

围绕 config/best_params.json 的 PLAYBOOK_B1B2B3 当前参数做邻域网格
（stop_pct ±0.02、b2_wait ±3），指标=每持有日净收益 + 近一年净均值。
邻居在两项指标上都相对现参改善 ≥15% 才写"建议"——**只建议不自动改参**
（参数变更需人工确认，防无人值守漂移）。结果追加 daily_auto_report.md。

用法：python scripts/auto_retune.py [--sample 800]
"""

import argparse
import json
import random
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.strategies.playbook_engine import simulate_b1b2b3  # noqa: E402
from replay_screen import load_stock  # noqa: E402

BEST = PROJECT_ROOT / "config" / "best_params.json"
REPORT = PROJECT_ROOT / "daily_auto_report.md"
RECENT_DAYS = 365


def _metrics(frames: dict, kw: dict, recent_start: str) -> dict:
    rows = []
    for sym, df in frames.items():
        try:
            rows += simulate_b1b2b3(df, symbol=sym, **kw)
        except Exception:
            continue
    t = pd.DataFrame(rows)
    if t.empty:
        return {"per_day": 0.0, "recent_net": 0.0, "n": 0}
    r = t[t["entry_date"] >= recent_start]
    return {"per_day": float(t["net_return"].sum()
                             / t["hold_days"].clip(lower=1).sum()),
            "recent_net": float(r["net_return"].mean()) if len(r) else 0.0,
            "n": len(t)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    today = date.today().isoformat()
    recent_start = (pd.Timestamp(today) - pd.Timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")

    bp = json.loads(BEST.read_text())
    cur = bp.get("PLAYBOOK_B1B2B3", {})
    cur_kw = {k: cur[k] for k in ("stop_pct", "b2_wait", "b2_vol_mult") if k in cur}
    if not cur_kw:
        print("best_params 无 PLAYBOOK_B1B2B3 调优参数，跳过")
        return 0

    files = sorted(Path(args.data_dir).glob("*.csv"))
    random.seed(42)
    files = random.sample(files, min(args.sample, len(files)))
    frames = {}
    for f in files:
        df = load_stock(f, "9999-12-31", min_rows=180)
        if df is not None:
            frames[f.stem] = df

    base = _metrics(frames, cur_kw, recent_start)
    lines = [f"\n## 自动调参周检 {today}",
             f"当前参数 {cur_kw} → 每持有日 {base['per_day']*100:+.3f}% · "
             f"近一年净均值 {base['recent_net']*100:+.2f}%（{base['n']}笔/{len(frames)}只）"]

    sp = float(cur_kw.get("stop_pct", 0.10))
    bw = int(cur_kw.get("b2_wait", 8))
    neighbors = []
    for dsp in (-0.02, 0.0, 0.02):
        for dbw in (-3, 0, 3):
            if dsp == 0 and dbw == 0:
                continue
            nsp = round(min(max(sp + dsp, 0.02), 0.20), 3)
            nbw = max(bw + dbw, 2)
            neighbors.append({**cur_kw, "stop_pct": nsp, "b2_wait": nbw})

    suggestions = []
    for kw in neighbors:
        m = _metrics(frames, kw, recent_start)
        tag = f"stop_pct={kw['stop_pct']} b2_wait={kw['b2_wait']}"
        lines.append(f"- {tag}: 每持有日 {m['per_day']*100:+.3f}% · "
                     f"近1年 {m['recent_net']*100:+.2f}%")
        if (base["per_day"] > 0 and base["recent_net"] > 0
                and m["per_day"] >= base["per_day"] * 1.15
                and m["recent_net"] >= base["recent_net"] * 1.15):
            suggestions.append(tag)

    if suggestions:
        lines.append(f"**⚠️ 建议人工复核参数（两指标均改善≥15%）：{'; '.join(suggestions)}**"
                     f"——需全市场验证后手动更新 best_params.json，不自动改。")
    else:
        lines.append("当前参数仍处邻域最优，无调整建议。")
    lines.append(f"（耗时 {(time.monotonic()-t0)/60:.1f} 分钟）")

    with REPORT.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
