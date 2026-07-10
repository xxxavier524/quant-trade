"""AB验证：B1信号 加/不加 筹码过滤 的胜率对比（路线图#5 验收）。

方法（同 ab_test_rps）：收集 B1 全历史信号事件 → 计算每个事件日的筹码指标
（profit_ratio 获利盘 / conc90 集中度，CYQ 历史重建，无泄漏）→ 按阈值分组对比
5/10 日前向净收益与净胜率，看"低获利盘+单峰密集"是否提纯 B1 底部信号。

用法：python scripts/ab_test_chip.py --sample 800
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR, REPORTS_DIR  # noqa: E402
from alphapulse.backtest.signal_validator import collect_signal_events, ROUND_TRIP_COST  # noqa: E402
from alphapulse.factors.chip_distribution import compute_chips  # noqa: E402
from validate_signal import load_universe  # noqa: E402


def chip_long_table(stocks: dict) -> pd.DataFrame:
    """每股 CYQ 一次 → 长表 [symbol, date, profit_ratio, conc90]。"""
    parts = []
    for i, (sym, df) in enumerate(stocks.items()):
        if i % 200 == 0 and i:
            print(f"  筹码 {i}/{len(stocks)}")
        if len(df) < 120:
            continue
        chips = compute_chips(df)
        t = pd.DataFrame({
            "symbol": sym,
            "date": df["date"].astype(str).values,
            "profit_ratio": chips["profit_ratio"].values,
            "conc90": chips["conc90"].values,
        })
        parts.append(t)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def grid_rows(ev: pd.DataFrame, col: str, thresholds: list, direction: str) -> list:
    """按阈值网格统计净胜率/净均值（direction='below' 取 col<th）。"""
    rows = []
    base = None
    for th in thresholds:
        sub = ev if th is None else (ev[ev[col] < th] if direction == "below"
                                     else ev[ev[col] >= th])
        if len(sub) < 150:
            rows.append({"过滤": "无(纯B1)" if th is None else f"{col}<{th}",
                         "样本": len(sub), "注": "样本<150略过"})
            continue
        rec = {"过滤": "无(纯B1)" if th is None else f"{col}<{th}", "样本": len(sub)}
        for w in (5, 10):
            net = sub[f"fwd_{w}"].dropna() - ROUND_TRIP_COST
            rec[f"净胜率{w}%"] = round(float((net > 0).mean() * 100), 1)
            rec[f"净均值{w}%"] = round(float(net.mean() * 100), 2)
        if th is None:
            base = rec
        rows.append(rec)
    return rows, base


def fmt_table(rows: list) -> str:
    if not rows:
        return "(无数据)"
    cols = ["过滤", "样本", "净胜率5%", "净均值5%", "净胜率10%", "净均值10%"]
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    lines = [head, sep]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "-")) for c in cols) + " |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--factor", default="B1_FORMULA")
    args = ap.parse_args()

    stocks = load_universe(Path(DATA_DIR), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")

    print(f"收集 {args.factor} 信号事件...")
    events = collect_signal_events(args.factor, stocks, forward_days=[5, 10])
    if events.empty:
        print("无信号事件"); return 1
    print(f"事件 {len(events)} 条")

    print("重建筹码分布（CYQ，无泄漏）...")
    chips = chip_long_table(stocks)
    ev = events.merge(chips, on=["symbol", "date"], how="left").dropna(
        subset=["profit_ratio", "conc90"])
    print(f"匹配到筹码的事件 {len(ev)} 条\n")

    pr_rows, base = grid_rows(ev, "profit_ratio", [None, 0.30, 0.20, 0.15, 0.10], "below")
    c90_rows, _ = grid_rows(ev, "conc90", [None, 0.30, 0.20, 0.15, 0.12], "below")

    # 组合过滤：低获利盘 且 单峰密集
    combo = ev[(ev["profit_ratio"] < 0.20) & (ev["conc90"] < 0.20)]
    combo_rows = []
    if len(combo) >= 150:
        rec = {"过滤": "profit<0.20 且 conc90<0.20", "样本": len(combo)}
        for w in (5, 10):
            net = combo[f"fwd_{w}"].dropna() - ROUND_TRIP_COST
            rec[f"净胜率{w}%"] = round(float((net > 0).mean() * 100), 1)
            rec[f"净均值{w}%"] = round(float(net.mean() * 100), 2)
        combo_rows = [base, rec] if base else [rec]

    def verdict(rows, min_keep=5000):
        """判定并推荐"甜点"阈值：留样≥min_keep 前提下净胜率提升最大，避免过度过滤失真。"""
        if not base:
            return "基线样本不足"
        cand = [r for r in rows if "净胜率5%" in r and r["过滤"] != "无(纯B1)"]
        if not cand:
            return "过滤后样本均不足"
        best = max(cand, key=lambda r: r["净胜率5%"])
        d = best["净胜率5%"] - base["净胜率5%"]
        dm = best["净均值5%"] - base["净均值5%"]
        tag = ("提纯有效" if d >= 1.0 and dm > 0 else
               "边际提纯" if d > 0 and dm > 0 else "未提纯（或减样过多）")
        # 甜点：留样充足的稳健操作点
        robust = [r for r in cand if r["样本"] >= min_keep]
        sweet = max(robust, key=lambda r: r["净胜率5%"], default=None)
        rec = ""
        if sweet and sweet["过滤"] != best["过滤"]:
            rec = (f"；推荐操作点 {sweet['过滤']}（留样{sweet['样本']}，净胜率5日"
                   f"{sweet['净胜率5%']}%、净均值10日{sweet.get('净均值10%')}%，避免过度过滤）")
        elif sweet:
            rec = f"（该点留样{sweet['样本']}充足，可直接采用）"
        return (f"{tag}：最佳 {best['过滤']} 净胜率5日 {base['净胜率5%']}%→"
                f"{best['净胜率5%']}%（Δ{d:+.1f}，样本{best['样本']}）{rec}")

    lines = [
        "# B1 + 筹码过滤 AB 验证（路线图#5）",
        "",
        f"> universe {len(stocks)} 只 | B1事件 {len(ev)} 条（含筹码）| "
        f"净收益=前向收益−双边成本{ROUND_TRIP_COST:.3f} | 主判据=5日净胜率",
        "",
        f"**获利盘过滤结论：{verdict(pr_rows)}**",
        "",
        "## 一、获利盘比例过滤（profit_ratio 越低=套牢盘越多=底部吸筹）",
        "",
        fmt_table(pr_rows),
        "",
        f"**单峰密集过滤结论：{verdict(c90_rows)}**",
        "",
        "## 二、筹码集中度过滤（conc90 越低=单峰越密集）",
        "",
        fmt_table(c90_rows),
        "",
        "## 三、组合过滤（低获利盘 且 单峰密集）",
        "",
        fmt_table(combo_rows) if combo_rows else "(样本不足)",
        "",
        "说明：过滤有效=净胜率提升且不因减样过度失真；负结果照实记录（沿用#3标准）。",
        "结论用于是否把筹码条件并入 B1 选股；生成因子默认不自动进选股。",
    ]
    out = Path(REPORTS_DIR) / "ab_chip_b1.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:6]))
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
