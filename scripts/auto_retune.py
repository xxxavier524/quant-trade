#!/usr/bin/env python3
"""每周自动回测调参（无人值守，launchd 周日 04:00）。

2026-07-28 重写（P2/C6+C7）。此前两个致命问题：
1. 目标函数是"每持有日净收益 + 近一年逐笔均值"——逐信号等权、无资金约束，
   与账户收益脱节（诚实组合回测 -12.4% 年化时该指标仍为正），优化它到不了年化10%。
2. 代码里写死"只建议不改参"，且门槛是两个指标同时改善≥15%（噪声带内几乎不可达），
   所以每周固定输出"邻域最优，无调整建议"——所谓自动升级从未发生过。

现在：
- 目标 = **组合级年化收益**（单票≤20%、最多5只并发，见 alphapulse/backtest/portfolio_eval）。
- **样本外纪律**：用较早的训练窗挑参数，用最近的留出窗验证；只有在留出窗上
  显著优于在任参数（且交易数足够、回撤不恶化）才写入 config/best_params.json。
- 写入即备份原参数为 _provenance_prev，并推飞书告知。--dry-run 只看不写。

用法：
    python scripts/auto_retune.py [--sample 800] [--dry-run]
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

from alphapulse.backtest.portfolio_eval import evaluate_portfolio  # noqa: E402
from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.strategies.playbook_engine import simulate_b1b2b3  # noqa: E402
from replay_screen import load_stock  # noqa: E402

BEST = PROJECT_ROOT / "config" / "best_params.json"
REPORT = PROJECT_ROOT / "daily_auto_report.md"

HOLDOUT_DAYS = 180        # 最近180自然日作为样本外留出窗（挑参数时完全不看）
MIN_HOLDOUT_TRADES = 30   # 留出窗至少要有这么多笔成交，否则样本太小不足以判优劣
MIN_IMPROVE_ANNUAL = 0.02 # 留出窗年化需比在任高出至少2个百分点（噪声容忍带）
MAX_DD_TOLERANCE = 0.05   # 回撤恶化超过5个百分点则否决（不为了收益牺牲风险）
# 绝对可行性下限：候选必须自身赚钱才配上生产。否则"从-70%改善到-47%"也会被判成
# +23个百分点的"改善"而写进生产参数——那只是从灾难换成亏损，不是升级。
MIN_ABSOLUTE_ANNUAL = 0.0
MAX_ABSOLUTE_DD = 0.35    # 留出窗回撤超过35%的参数一律不上生产


def _simulate(frames: dict, kw: dict) -> list[dict]:
    """跑出该参数下全样本的逐笔交易。"""
    rows = []
    for sym, df in frames.items():
        try:
            rows += simulate_b1b2b3(df, symbol=sym, **kw)
        except Exception:
            continue
    return rows


def _split_eval(trades: list[dict], split_date: str) -> tuple[dict, dict]:
    """按入场日切分训练/留出窗，各自折算组合绩效。"""
    train = [t for t in trades if str(t.get("entry_date", "")) < split_date]
    hold = [t for t in trades if str(t.get("entry_date", "")) >= split_date]
    return evaluate_portfolio(train), evaluate_portfolio(hold)


def decide_update(cand_hold: dict, base_hold: dict,
                  min_trades: int = MIN_HOLDOUT_TRADES,
                  min_improve: float = MIN_IMPROVE_ANNUAL,
                  dd_tolerance: float = MAX_DD_TOLERANCE,
                  min_absolute: float = MIN_ABSOLUTE_ANNUAL,
                  max_abs_dd: float = MAX_ABSOLUTE_DD) -> tuple[bool, str]:
    """是否用候选参数替换在任参数（纯函数，便于单测）。

    四道闸：留出窗样本量足够 → **候选自身可行（绝对下限）** → 年化显著改善 →
    回撤不明显恶化。绝对下限是关键：只做相对比较会把"从-70%变-47%"当成升级。
    """
    if cand_hold["n_taken"] < min_trades:
        return False, (f"留出窗成交仅 {cand_hold['n_taken']} 笔"
                       f"（<{min_trades}），样本不足以判优劣")
    if cand_hold["annual_return"] <= min_absolute:
        return False, (f"候选留出窗年化 {cand_hold['annual_return']:+.2%} 本身不赚钱"
                       f"（需 >{min_absolute:.0%}）——策略本身没有正期望，"
                       f"调参救不了，需重做信号而非换参数")
    if abs(cand_hold["max_drawdown"]) > max_abs_dd:
        return False, (f"候选留出窗回撤 {cand_hold['max_drawdown']:.2%} 超过绝对上限 "
                       f"{max_abs_dd:.0%}，不可上生产")
    gain = cand_hold["annual_return"] - base_hold["annual_return"]
    if gain < min_improve:
        return False, (f"留出窗年化 {cand_hold['annual_return']:+.2%} vs 在任 "
                       f"{base_hold['annual_return']:+.2%}，提升 {gain:+.2%} "
                       f"未达门槛 {min_improve:.0%}")
    dd_worse = base_hold["max_drawdown"] - cand_hold["max_drawdown"]
    if dd_worse > dd_tolerance:
        return False, (f"年化虽+{gain:.2%}，但留出窗回撤恶化 {dd_worse:.2%}"
                       f"（>{dd_tolerance:.0%}），否决")
    return True, (f"留出窗年化 {base_hold['annual_return']:+.2%} → "
                  f"{cand_hold['annual_return']:+.2%}（+{gain:.2%}），"
                  f"回撤 {cand_hold['max_drawdown']:.2%}，{cand_hold['n_taken']} 笔")


def _fmt(name: str, tr: dict, ho: dict) -> str:
    return (f"- {name}: 训练窗年化 {tr['annual_return']:+.2%}"
            f"(回撤{tr['max_drawdown']:.1%}/{tr['n_taken']}笔) | "
            f"留出窗年化 {ho['annual_return']:+.2%}"
            f"(回撤{ho['max_drawdown']:.1%}/{ho['n_taken']}笔)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--dry-run", action="store_true", help="只评估不写参数")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    today = date.today().isoformat()
    split_date = (pd.Timestamp(today) - pd.Timedelta(days=HOLDOUT_DAYS)).strftime("%Y-%m-%d")

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
    if not frames:
        print("无可用日线（外接盘未挂载？），跳过")
        return 0

    base_tr, base_ho = _split_eval(_simulate(frames, cur_kw), split_date)
    lines = [f"\n## 自动调参周检 {today}（组合级年化 · 留出窗样本外）",
             f"样本 {len(frames)} 只 · 训练窗 <{split_date} · 留出窗 ≥{split_date}",
             _fmt(f"当前参数 {cur_kw}", base_tr, base_ho)]

    sp = float(cur_kw.get("stop_pct", 0.10))
    bw = int(cur_kw.get("b2_wait", 8))
    neighbors = []
    for dsp in (-0.02, 0.0, 0.02):
        for dbw in (-3, 0, 3):
            if dsp == 0 and dbw == 0:
                continue
            neighbors.append({**cur_kw,
                              "stop_pct": round(min(max(sp + dsp, 0.02), 0.20), 3),
                              "b2_wait": max(bw + dbw, 2)})

    scored = []
    for kw in neighbors:
        tr, ho = _split_eval(_simulate(frames, kw), split_date)
        tag = f"stop_pct={kw['stop_pct']} b2_wait={kw['b2_wait']}"
        lines.append(_fmt(tag, tr, ho))
        scored.append((tr["annual_return"], kw, tr, ho, tag))

    # 只用训练窗挑候选（留出窗此刻仍是"未看过的未来"），再用留出窗裁决
    scored.sort(key=lambda x: -x[0])
    changed = False
    if scored:
        _, kw, tr, ho, tag = scored[0]
        ok, why = decide_update(ho, base_ho)
        lines.append(f"\n训练窗最佳候选：{tag}")
        if ok and not args.dry_run:
            entry = {**cur, **kw}
            entry["_source"] = {"method": "auto_retune_portfolio", "date": today,
                                "holdout_annual": ho["annual_return"],
                                "holdout_max_dd": ho["max_drawdown"],
                                "holdout_trades": ho["n_taken"],
                                "split_date": split_date, "sample": len(frames),
                                "metric": "组合级年化(单票≤20%/≤5并发)·留出窗样本外"}
            entry["_provenance_prev"] = {k: v for k, v in cur.items()
                                         if not k.startswith("_")}
            bp["PLAYBOOK_B1B2B3"] = entry
            BEST.write_text(json.dumps(bp, indent=2, ensure_ascii=False))
            changed = True
            lines.append(f"**✅ 已更新 best_params.json**：{why}")
            try:
                from alphapulse.config.settings import FEISHU_WEBHOOK_URL
                if FEISHU_WEBHOOK_URL:
                    from alphapulse.notify.feishu_bot import send_feishu
                    send_feishu(FEISHU_WEBHOOK_URL,
                                f"🔧 AlphaPulse 自动调参已生效：{tag}\n{why}")
            except Exception:
                pass
        elif ok and args.dry_run:
            lines.append(f"（--dry-run，未写入）本应更新：{why}")
        else:
            lines.append(f"维持在任参数：{why}")

        # 没有任何候选（含在任）在留出窗上赚钱 → 这不是"调参没找到更优"，
        # 而是策略本身在当前市况下无正期望。必须显式告警，否则每周"无调整建议"
        # 会被误读成"当前参数很好"（这正是旧版掩盖了两个月的事实）。
        all_hold = [base_ho] + [s[3] for s in scored]
        if all(h["annual_return"] <= 0 for h in all_hold):
            best_ho = max(h["annual_return"] for h in all_hold)
            warn = (f"⚠️ 全部 {len(all_hold)} 组参数在留出窗（≥{split_date}）均为负期望，"
                    f"最好也只有 {best_ho:+.2%} 年化。结论：B1B2B3 当前不具备正期望，"
                    f"问题在信号本身而非参数，调参无法达成年化10%目标。")
            lines.append(f"\n**{warn}**")
            if not args.dry_run:
                try:
                    from alphapulse.config.settings import FEISHU_WEBHOOK_URL
                    if FEISHU_WEBHOOK_URL:
                        from alphapulse.notify.feishu_bot import send_feishu
                        send_feishu(FEISHU_WEBHOOK_URL, f"📉 AlphaPulse 调参周检: {warn}")
                except Exception:
                    pass

    lines.append(f"（耗时 {(time.monotonic()-t0)/60:.1f} 分钟）")
    with REPORT.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if not changed else 0


if __name__ == "__main__":
    sys.exit(main())
