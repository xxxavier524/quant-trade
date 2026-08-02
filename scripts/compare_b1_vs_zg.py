#!/usr/bin/env python3
"""B1_FORMULA vs ZG_B1_BRICK 对比回测。

ZG_B1_BRICK 的信号是 B1_FORMULA 的严格子集（B1 ∧ 砖型图早段 ∧ 非尾段），
因此对比的本质是：**砖型图周期过滤对 B1 信号有没有增益**。

两个层面，同一样本、同一退出规则：

A. 信号级事件研究（隔离进场质量）
   把每个 B1 信号日分为「ZG放行组」（砖型图早段）和「ZG拒绝组」（其余），
   对两组用完全相同的退出方案统计单笔收益：
   - 固定持有 5/10/20 交易日（信号日收盘进，N日后收盘出）
   - Z哥纪律退出：止损=入场日最低价-3价位，收盘破位即出；最多持有4天（时间止损）

B. 组合级回测（仓库引擎原封口径）
   BacktestEngine：最多5只持仓、-10%止损/+30%止盈、含滑点手续费，
   分别跑 B1_FORMULA 与 ZG_B1_BRICK 全量信号。

用法：
    python scripts/compare_b1_vs_zg.py                       # 默认 temp_data
    python scripts/compare_b1_vs_zg.py --data-dir data/day   # 本地全量数据
    python scripts/compare_b1_vs_zg.py --start 2021-01-01 --end 2026-06-30

注意：temp_data 为案例股样本（偏赢家），绝对数值偏乐观；
相对比较（同样本同退出的两组差异）才是本报告的看点。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.factors import b1_formula, four_brick_cycle  # noqa: E402
from alphapulse.strategies import zg_b1_brick  # noqa: E402
from alphapulse.strategies.b1_formula_strategy import generate_signals as b1_signals  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("compare_b1_vs_zg")

RESULTS_DIR = PROJECT_ROOT / "backtest_results"
TICK = 0.01
TICK_OFFSET = 3


# ---------------------------------------------------------------- 数据加载

def load_stocks(data_dir: Path, start: str, end: str) -> dict[str, pd.DataFrame]:
    stocks = {}
    for f in sorted(data_dir.glob("*.csv")):
        try:
            df = pd.read_csv(f, parse_dates=["date"]).set_index("date").sort_index()
        except Exception:
            continue
        if len(df) < 150 or not {"open", "high", "low", "close", "volume"} <= set(df.columns):
            continue
        df = df[str(df.index[0])[:10]: end]
        stocks[f.stem[:6]] = df
    logger.info(f"加载 {len(stocks)} 只（{data_dir}）")
    return stocks


# ---------------------------------------------------------------- A. 信号级

def zg_discipline_exit(df: pd.DataFrame, t_idx: int, max_hold: int = 4) -> tuple[float, str, int]:
    """Z哥纪律退出：止损=入场日最低价-3价位（收盘破位即出），最多持有max_hold天。

    Returns: (return_pct, exit_reason, hold_days)
    """
    entry = float(df["close"].iloc[t_idx])
    stop = float(df["low"].iloc[t_idx]) - TICK_OFFSET * TICK
    last = len(df) - 1
    for n in range(1, max_hold + 1):
        i = t_idx + n
        if i > last:
            px = float(df["close"].iloc[last])
            return (px / entry - 1) * 100, "end_of_data", last - t_idx
        px = float(df["close"].iloc[i])
        if px < stop:
            return (px / entry - 1) * 100, "stop_loss", n
    px = float(df["close"].iloc[t_idx + max_hold])
    return (px / entry - 1) * 100, "time_stop", max_hold


def fixed_hold_return(df: pd.DataFrame, t_idx: int, n: int) -> float | None:
    if t_idx + n >= len(df):
        return None
    entry = float(df["close"].iloc[t_idx])
    return (float(df["close"].iloc[t_idx + n]) / entry - 1) * 100


def signal_event_study(stocks: dict[str, pd.DataFrame], start: str, end: str) -> pd.DataFrame:
    """每个 B1 信号一行：组别 + 各退出方案收益。"""
    rows = []
    for symbol, df in stocks.items():
        try:
            b1 = b1_formula.compute(df)
            early = four_brick_cycle.compute(df, early_max=2)
            late = four_brick_cycle.compute_late(df, late_from=4)
            brick_pos = four_brick_cycle.compute_brick_position(df)
        except Exception as e:
            logger.debug(f"{symbol} 因子异常: {e}")
            continue
        zg = b1 & early & ~late
        idx_map = {d: i for i, d in enumerate(df.index)}
        for dt in df.index[b1]:
            d = str(dt)[:10]
            if not (start <= d <= end):
                continue
            t = idx_map[dt]
            if t + 1 >= len(df):
                continue
            ret_zg, reason, hold = zg_discipline_exit(df, t)
            rows.append({
                "symbol": symbol,
                "date": d,
                "group": "ZG放行" if bool(zg.loc[dt]) else "ZG拒绝",
                "brick_pos": int(brick_pos.loc[dt]),
                "ret_5d": fixed_hold_return(df, t, 5),
                "ret_10d": fixed_hold_return(df, t, 10),
                "ret_20d": fixed_hold_return(df, t, 20),
                "ret_zg_exit": ret_zg,
                "zg_exit_reason": reason,
                "zg_hold_days": hold,
            })
    return pd.DataFrame(rows)


def summarize_group(g: pd.DataFrame) -> dict:
    out = {"信号数": len(g)}
    for col, label in [("ret_5d", "5日"), ("ret_10d", "10日"),
                       ("ret_20d", "20日"), ("ret_zg_exit", "Z哥退出")]:
        s = g[col].dropna()
        if len(s) == 0:
            continue
        pos, neg = s[s > 0].sum(), s[s < 0].sum()
        out[f"{label}·均值%"] = round(s.mean(), 2)
        out[f"{label}·中位%"] = round(s.median(), 2)
        out[f"{label}·胜率%"] = round((s > 0).mean() * 100, 1)
        out[f"{label}·盈亏比"] = round(pos / abs(neg), 2) if neg < 0 else float("inf")
    return out


# ---------------------------------------------------------------- B. 组合级

def _zg_pos2_only(data, symbol="", **params):
    """变体：只取第2砖信号（分层研究显示第2砖是唯一正增益砖位）。"""
    gs = zg_b1_brick.generate_signals(data, symbol=symbol, **params)
    return gs[gs["brick_position"] == 2] if len(gs) else gs


def _zg_v2(data, symbol="", **params):
    """v2：仅第2砖 ∧ MACD多头区间（砖型图×MACD共振，registry=ZG_B1_BRICK_V2）。"""
    return zg_b1_brick.generate_signals(
        data, symbol=symbol, positions=[2], require_dif_positive=True, **params)


def portfolio_backtest(stocks, start, end) -> dict:
    """v5：交易引擎已移除，改为纯选股成功率评估（见 alphapulse.screening）。"""
    from alphapulse.screening.evaluator import evaluate_strategy, signal_dates_of

    results = {}
    for name, fn in [("B1_FORMULA", b1_signals),
                     ("ZG_B1_BRICK", zg_b1_brick.generate_signals),
                     ("ZG仅第2砖", _zg_pos2_only),
                     ("ZG_v2(2砖∧DIF>0)", _zg_v2)]:
        logger.info(f"选股成功率评估: {name}")
        closes_map = {s: d.set_index("date")["close"].astype(float)
                      for s, d in stocks.items()}
        dates_by_symbol: dict[str, list[str]] = {}
        for sym, df in stocks.items():
            try:
                dates = signal_dates_of(fn(df, symbol=sym), df)
                if dates:
                    dates_by_symbol[sym] = dates
            except Exception:
                continue
        results[name] = evaluate_strategy(dates_by_symbol, closes_map)
    return results


# ---------------------------------------------------------------- 报告

def fmt_pct(x):
    """引擎已返回百分数（如 12.34 = 12.34%）。"""
    return f"{x:+.2f}%" if isinstance(x, (int, float)) and not pd.isna(x) else "—"


def build_report(ev: pd.DataFrame, port: dict, args, n_stocks: int) -> str:
    lines = [
        "# B1_FORMULA vs ZG_B1_BRICK 对比回测",
        "",
        f"- 样本：{n_stocks} 只（{args.data_dir}），区间 {args.start} ~ {args.end}",
        "- ZG = B1 ∧ 砖型图早段(第1-2红砖) ∧ 非尾段 —— 对比即「砖型图过滤的增益」",
        "- ⚠️ temp_data 为案例股样本（偏赢家），看**相对差异**而非绝对收益；不构成投资建议",
        "",
        "## A. 信号级事件研究（同退出规则下的分组对比）",
        "",
    ]
    groups = {}
    for gname in ["ZG放行", "ZG拒绝"]:
        g = ev[ev["group"] == gname]
        if len(g):
            groups[gname] = summarize_group(g)
    groups["B1全部"] = summarize_group(ev)

    keys = ["信号数"] + [k for k in next(iter(groups.values())) if k != "信号数"]
    lines.append("| 指标 | " + " | ".join(groups) + " |")
    lines.append("|------|" + "|".join(["------"] * len(groups)) + "|")
    for k in keys:
        lines.append(f"| {k} | " + " | ".join(str(g.get(k, "—")) for g in groups.values()) + " |")

    era = ev[ev["group"] == "ZG放行"]["ret_zg_exit"].dropna()
    erb = ev[ev["group"] == "ZG拒绝"]["ret_zg_exit"].dropna()
    if len(era) > 5 and len(erb) > 5:
        diff = era.mean() - erb.mean()
        lines += ["", f"**Z哥退出口径下，放行组单笔均值比拒绝组高 {diff:+.2f}pp**"
                      f"（放行 {era.mean():+.2f}% vs 拒绝 {erb.mean():+.2f}%）"]

    reasons = ev[ev["group"] == "ZG放行"]["zg_exit_reason"].value_counts()
    lines += ["", "ZG放行组退出原因分布：" +
              "、".join(f"{k}={v}" for k, v in reasons.items())]

    # 按砖位分层：B1 信号在砖型图哪个位置最有效？
    lines += ["", "### 按砖位分层（B1信号 × 砖型图位置）", "",
              "| 砖位 | 信号数 | 5日均值% | 5日胜率% | 10日均值% | 10日胜率% | 20日均值% | 20日胜率% | Z哥退出均值% | Z哥退出胜率% |",
              "|------|-------|---------|---------|----------|----------|----------|----------|------------|------------|"]
    ev2 = ev.copy()
    ev2["砖位"] = ev2["brick_pos"].apply(lambda p: "0(绿砖中)" if p == 0 else (f"{p}" if p < 4 else "≥4(尾段)"))
    for pos in ["0(绿砖中)", "1", "2", "3", "≥4(尾段)"]:
        g = ev2[ev2["砖位"] == pos]
        if len(g) == 0:
            continue
        cells = [pos, str(len(g))]
        for col in ["ret_5d", "ret_10d", "ret_20d"]:
            s = g[col].dropna()
            cells += [f"{s.mean():+.2f}", f"{(s > 0).mean() * 100:.1f}"] if len(s) else ["—", "—"]
        s = g["ret_zg_exit"].dropna()
        cells += [f"{s.mean():+.2f}", f"{(s > 0).mean() * 100:.1f}"] if len(s) else ["—", "—"]
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## B. 选股成功率（v5 纯选股口径：5日内任一收盘≥+5%机会命中，无交易模拟）", ""]
    metric_rows = [
        ("信号数", "n"), ("成功率%", "success_rate"), ("基线%", "base_rate"),
        ("超额pp", "lift_pp"), ("期末收益均值%", "end_ret_mean"),
        ("期末中位%", "end_ret_median"), ("期末上涨占比%", "hit_ratio_end"),
    ]
    names = list(port)
    lines.append("| 指标 | " + " | ".join(names) + " |")
    lines.append("|------|" + "|".join(["------"] * len(names)) + "|")
    for label, key in metric_rows:
        vals = []
        for n in names:
            v = port[n].get(key)
            if v is None:
                vals.append("—")
            elif key in ("success_rate", "base_rate", "lift_pp",
                         "end_ret_mean", "end_ret_median", "hit_ratio_end"):
                vals.append(fmt_pct(v))
            elif isinstance(v, float):
                vals.append(f"{v:.2f}")
            else:
                vals.append(str(v))
        lines.append(f"| {label} | " + " | ".join(vals) + " |")

    lines += ["", "> 复现：`python scripts/compare_b1_vs_zg.py --data-dir <目录>`（本地全量数据更有说服力）"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="temp_data")
    ap.add_argument("--start", default="2020-07-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--skip-portfolio", action="store_true")
    args = ap.parse_args()

    data_dir = PROJECT_ROOT / args.data_dir if not Path(args.data_dir).is_absolute() else Path(args.data_dir)
    stocks = load_stocks(data_dir, args.start, args.end)
    if not stocks:
        logger.error("无可用数据")
        return

    logger.info("A. 信号级事件研究…")
    ev = signal_event_study(stocks, args.start, args.end)
    logger.info(f"  共 {len(ev)} 个B1信号（放行 {(ev['group']=='ZG放行').sum()} / 拒绝 {(ev['group']=='ZG拒绝').sum()}）")

    port = {}
    if not args.skip_portfolio:
        port = portfolio_backtest(stocks, args.start, args.end)

    report = build_report(ev, port, args, len(stocks))
    RESULTS_DIR.mkdir(exist_ok=True)
    out_md = RESULTS_DIR / "b1_vs_zg_comparison.md"
    out_md.write_text(report, encoding="utf-8")
    ev.to_csv(RESULTS_DIR / "b1_vs_zg_signals.csv", index=False)
    logger.info(f"报告：{out_md}")
    print("\n" + report)


if __name__ == "__main__":
    main()
