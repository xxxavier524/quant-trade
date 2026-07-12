#!/usr/bin/env python3
"""每日选股（评分版）— 全市场扫描 → 加权评分 0-100 → Top N 结构化输出。

替代旧版（只扫前200只、纯布尔信号）。流程：
1. 加载全市场CSV（含市值反推），可用 --date 回放历史日
2. 每股计算11个连续子分数 + 3个严格信号徽章（B1/量能B1/知行超短）
3. 大盘档位调节 + 加权排序，输出 Top 50
4. 结构化输出 reports/screen_YYYY-MM-DD.csv（GUI直读）+ Markdown 摘要 + 飞书推送

用法：
    python scripts/daily_screener.py                 # 最新交易日
    python scripts/daily_screener.py --date 2026-05-15 --top 30
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR, FEISHU_WEBHOOK_URL  # noqa: E402
from alphapulse.market.market_score import compute_market_score  # noqa: E402
from alphapulse.market.sector_score import rank_sectors, symbol_sector_map  # noqa: E402
from alphapulse.ranking.composite import (  # noqa: E402
    build_stock_row, rank_all, reset_signal_errors, report_signal_errors)
from replay_screen import load_stock  # noqa: E402  复用市值反推/列自愈逻辑

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_screener")

REPORTS_DIR = PROJECT_ROOT / "reports"

# 子分数中文名（报告显示用）
SUB_NAMES = {
    "j_low": "J值低位", "trend_gap": "趋势强度", "vol_shrink": "缩量",
    "yangyin": "红肥绿瘦", "surge": "爆量阳", "dif": "DIF",
    "ql_pos": "QL位置", "pct_calm": "涨幅温和", "amplitude": "振幅",
    "bowl": "掉进碗里", "washout_recover": "单针回收",
}


def load_names() -> dict[str, str]:
    """股票名称表（来自股本meta或黄金案例，缺失为空）。"""
    names = {}
    meta = PROJECT_ROOT / "data" / "meta" / "share_capital.csv"
    if meta.exists():
        try:
            df = pd.read_csv(meta, dtype={"symbol": str})
            names = dict(zip(df["symbol"].str.zfill(6), df["name"]))
        except Exception:
            pass
    return names


def run(date: str | None, top_n: int, data_dir: Path,
        push_label: str = "") -> pd.DataFrame:
    t0 = time.monotonic()
    names = load_names()

    # ── 大盘诊断（量能+N型+知行BS，真实指数 data/index/）──
    macro_level, macro_score, macro_advice = "震荡", 50.0, ""
    try:
        macro = compute_market_score(end_date=date or "9999-12-31")
        macro_level, macro_score = macro["level"], macro["score"]
        macro_advice = macro["advice"]
    except Exception as e:
        logger.warning(f"大盘评分失败，用默认震荡档: {e}")
    logger.info(f"大盘: {macro_score}/100 [{macro_level}] {macro_advice}")

    # ── 全市场加载（先全量载入，目标日取最后日期众数，防数据陈旧偏差）──
    files = sorted(data_dir.glob("*.csv"))
    end_date = date or "9999-12-31"
    all_frames: dict[str, pd.DataFrame] = {}
    for i, f in enumerate(files):
        if i % 1000 == 0 and i:
            logger.info(f"  加载 {i}/{len(files)} ...")
        df = load_stock(f, end_date, min_rows=120)
        if df is not None:
            all_frames[f.stem] = df

    last_dates = pd.Series({s: d.iloc[-1]["date"] for s, d in all_frames.items()})
    target_date = date or last_dates.mode().iloc[0]
    coverage = (last_dates == target_date).mean()
    if coverage < 0.8:
        logger.warning(
            f"⚠️ 仅 {coverage*100:.0f}% 股票更新到 {target_date}，数据可能陈旧，"
            f"请先运行 scripts/daily_update.py")

    # 数据比目标日新的截断回目标日（更新到一半时众数落在旧日，直接剔除会把
    # 最新的那批股票整批扔出选股池）；比目标日旧的确实缺数据，只能剔除
    stock_frames: dict[str, pd.DataFrame] = {}
    n_truncated = n_stale = 0
    for s, d in all_frames.items():
        last = d.iloc[-1]["date"]
        if last == target_date:
            stock_frames[s] = d
        elif last > target_date:
            dd = d[d["date"] <= target_date]
            if len(dd) >= 120 and dd.iloc[-1]["date"] == target_date:
                stock_frames[s] = dd.reset_index(drop=True)
                n_truncated += 1
        else:
            n_stale += 1
    if n_truncated or n_stale:
        logger.info(f"对齐 {target_date}: 截断 {n_truncated} 只(数据更新), "
                    f"剔除 {n_stale} 只(数据陈旧)")
    reset_signal_errors()
    rows = []
    for sym, df in stock_frames.items():
        row = build_stock_row(sym, names.get(sym, ""), df)
        if row:
            rows.append(row)
    report_signal_errors(logger)

    # ── 板块评分排名 ──
    sector_df = pd.DataFrame()
    try:
        sector_df = rank_sectors(stock_frames)
        if not sector_df.empty:
            REPORTS_DIR.mkdir(exist_ok=True)
            sector_df.to_csv(REPORTS_DIR / f"sectors_{target_date}.csv",
                             index=False, encoding="utf-8-sig")
            logger.info("板块Top5: " + " | ".join(
                f"{r['sector']}{r['score']:.0f}" for _, r in sector_df.head(5).iterrows()))
    except Exception as e:
        logger.warning(f"板块评分失败: {e}")

    factor_df = pd.DataFrame(rows)
    logger.info(f"有效股票 {len(factor_df)} 只 @ {target_date}")
    if factor_df.empty:
        return factor_df
    # 市值覆盖告警：market_cap 缺失时 B1 公式的"市值>10亿"条件静默放行
    if "float_mv_yi" in factor_df.columns:
        mv_missing = factor_df["float_mv_yi"].isna().mean()
        if mv_missing > 0.2:
            logger.warning(f"⚠️ {mv_missing*100:.0f}% 股票缺市值数据，"
                           f"B1市值门槛对这些票不生效（检查 data/meta/share_capital.csv）")

    # ── 板块/概念标注并入因子帧（供 GUI 交互重排复用，无需重算全市场）──
    sec_map, cmap = {}, {}
    try:
        sec_map = symbol_sector_map()
    except Exception:
        pass
    try:
        from alphapulse.market.sector_score import symbol_concept_map
        cmap = symbol_concept_map()
    except Exception:
        pass
    factor_df["sector"] = factor_df["symbol"].map(sec_map).fillna("")
    factor_df["concepts"] = factor_df["symbol"].map(cmap).fillna("")
    if not sector_df.empty:
        sec_scores = dict(zip(sector_df["sector"], sector_df["score"]))
        factor_df["sector_score"] = factor_df["sector"].map(sec_scores)

    # 全市场因子帧落盘：GUI 调参后用 rank_all 秒级重排，不必重扫5000只
    REPORTS_DIR.mkdir(exist_ok=True)
    factor_df.to_csv(REPORTS_DIR / f"factor_frame_{target_date}.csv",
                     index=False, encoding="utf-8-sig")

    # ── 排序（默认硬过滤：股价站上黄线）──
    top = rank_all(factor_df, top_n=top_n, macro_level=macro_level, sector_map=sec_map)
    if not top.empty and not sector_df.empty:
        sec_scores = dict(zip(sector_df["sector"], sector_df["score"]))
        top["sector_score"] = top["sector"].map(sec_scores)
    if not top.empty:
        # 选股策略列：哪些公式/信号触发
        def _strategies(r):
            tags = []
            if r.get("sig_b1"):
                tags.append("B1")
            if r.get("sig_volume_b1"):
                tags.append("量能B1")
            if r.get("sig_zhixing"):
                tags.append("知行超短")
            if r.get("sig_needle"):
                tags.append("单针下三十")
            if r.get("sig_brick3"):
                tags.append("砖型图")
            # 周线金叉是连续因子非严格信号，只进 top_factors 贡献解释，不混入战法标签
            if not tags:
                tags.append("综合评分")
            return "+".join(tags)
        top["strategies"] = top.apply(_strategies, axis=1)
        try:
            from alphapulse.market.sector_score import symbol_concept_map
            cmap = symbol_concept_map()
            top["concepts"] = top["symbol"].map(cmap).fillna("")
        except Exception:
            top["concepts"] = ""

    # ── 结构化输出 ──
    REPORTS_DIR.mkdir(exist_ok=True)
    out_csv = REPORTS_DIR / f"screen_{target_date}.csv"
    top.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # Markdown 摘要
    md = [f"# 选股日报 {target_date}",
          f"\n大盘: {macro_score}/100 [{macro_level}] {macro_advice} | 扫描 {len(factor_df)} 只 | "
          f"严格信号 {int(top['strict_signal'].sum())} 只\n"]
    if not sector_df.empty:
        md.append("强势板块: " + " | ".join(
            f"{r['sector']}({r['score']:.0f}{('·'+r['tags']) if r['tags'] else ''})"
            for _, r in sector_df.head(5).iterrows()) + "\n")
    md += ["| 排名 | 代码 | 名称 | 总分 | 严格信号 | 板块 | 现价 | 涨幅% | 主要贡献 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for _, r in top.head(20).iterrows():
        sigs = [s for s, c in [("B1", "sig_b1"), ("量能B1", "sig_volume_b1"),
                               ("知行超短", "sig_zhixing"),
                               ("单针下三十", "sig_needle"),
                               ("砖型图", "sig_brick3")] if r.get(c)]
        md.append(f"| {r['rank']} | {r['symbol']} | {r['name']} | {r['score']:.1f} "
                  f"| {'+'.join(sigs) or '—'} | {r.get('sector', '')} | {r.get('close', '')} "
                  f"| {r.get('pct_change', '')} | {r['top_factors']} |")
    md_path = REPORTS_DIR / f"daily_report_{target_date}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    logger.info(f"Top{top_n} → {out_csv}")
    logger.info(f"耗时 {(time.monotonic()-t0)/60:.1f} 分钟")

    # 飞书推送（配置了webhook才发）：按两大战法分列，含板块/概念（用户需求 2026-07-10）
    if FEISHU_WEBHOOK_URL:
        try:
            from alphapulse.notify.feishu_bot import send_feishu
            from alphapulse.tracking.signal_tracker import family_of, _clean

            def _line(r):
                name = _clean(r.get("name"))
                concepts = "/".join(_clean(r.get("concepts")).split("/")[:2])
                return (f"{r['symbol']}{(' ' + name) if name else ''} · {r['score']:.0f}分"
                        f" · {_clean(r.get('sector')) or '未知板块'}"
                        + (f" · {concepts}" if concepts else "")
                        + f" · {r['strategies']}")

            fam_col = top["strategies"].map(family_of) if not top.empty else None
            label = f"·{push_label}" if push_label else ""
            sections = [f"📊 选股 {target_date}{label} 大盘{macro_score}[{macro_level}]"]
            for fam, icon in [("基本面法", "🎯"), ("砖型图法", "🧱")]:
                sub = top[fam_col.str.contains(fam, na=False)] if fam_col is not None else top.iloc[0:0]
                sections.append(f"{icon}【{fam}】" if not sub.empty else f"{icon}【{fam}】无信号")
                for _, r in sub.head(5).iterrows():
                    both = "+" in fam_col.loc[r.name]
                    sections.append(("🔗" if both else "· ") + _line(r)
                                    + ("（双法共振）" if both else ""))
            plain = top[fam_col == ""] if fam_col is not None else top.iloc[0:0]
            if not plain.empty:
                sections.append("📈【综合评分Top5】(无严格信号)")
                sections += ["· " + _line(r) for _, r in plain.head(5).iterrows()]
            send_feishu(FEISHU_WEBHOOK_URL, "\n".join(sections))
        except Exception as e:
            logger.warning(f"飞书推送失败: {e}")
    return top


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="回放历史日 YYYY-MM-DD（默认最新交易日）")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--push-label", default="", help="飞书推送标题附注（如 晚间版）")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        sys.exit(f"数据目录不存在: {data_dir}（外接硬盘未挂载？）")
    top = run(args.date, args.top, data_dir, push_label=args.push_label)
    if not top.empty:
        cols = ["rank", "symbol", "name", "score", "strict_signal", "top_factors"]
        print(top[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
