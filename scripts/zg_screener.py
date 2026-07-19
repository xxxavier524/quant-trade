#!/usr/bin/env python3
"""Z哥融合选股（独立版）— B1买点 + 砖型图周期确认 + 择时闸门 + 纪律卡。

刻意与 daily_screener 分开：这是 zettaranc-perspective 体系的独立试验田，
跑一段时间效果好，再考虑把 ZG_B1_BRICK 并入主选股。

流程（对应 Z哥少妇战法 SOP）：
  0. 择时闸门：大盘档位为「空/危险」时，默认不出票（--ignore-macro 可关）
     = 体系「不见兔子不撒鹰 / 心中无牛熊唯有纪律坚」
  1. 全市场扫描，每股跑 zg_b1_brick.generate_signals（B1 + 砖型图早段）
  2. 输出独立报告 reports/zg_screen_YYYY-MM-DD.{csv,md}
     每只票带 Z哥纪律卡：止损线 / 离场提示 / 砖型图周期位置 / 置信度

用法：
    python scripts/zg_screener.py                      # 最新交易日
    python scripts/zg_screener.py --date 2026-05-15 --top 30
    python scripts/zg_screener.py --data-dir temp_data --ignore-macro
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.strategies import zg_b1_brick  # noqa: E402
from replay_screen import load_stock  # noqa: E402  复用市值反推/列自愈

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("zg_screener")

REPORTS_DIR = PROJECT_ROOT / "reports"


def macro_gate(end_date: str) -> tuple[bool, str]:
    """择时闸门：返回 (放行, 大盘描述)。大盘诊断不可用时默认放行。"""
    try:
        from alphapulse.market.market_score import compute_market_score
        m = compute_market_score(end_date)
        level = str(m.get("level", ""))
        blocked = any(k in level for k in ("空", "危险", "回避"))
        return (not blocked), f"{level}({m.get('score', '—')}分)"
    except Exception as e:  # 无指数数据等 → 不阻塞
        logger.warning(f"大盘诊断不可用，择时闸门跳过: {e}")
        return True, "择时不可用"


def load_names() -> dict[str, str]:
    try:
        import json
        p = PROJECT_ROOT / "config" / "sector_tags.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return {k: v.get("name", "") for k, v in d.items()} if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def run(date: str, data_dir: Path, top: int, ignore_macro: bool, **params) -> pd.DataFrame:
    passed, macro_desc = (True, "已忽略") if ignore_macro else macro_gate(date)
    logger.info(f"择时闸门: 大盘{macro_desc} → {'放行' if passed else '空仓（不出票）'}")
    if not passed:
        logger.warning("大盘档位不利，按Z哥体系空仓等待。加 --ignore-macro 可强制扫描。")
        return pd.DataFrame()

    files = sorted(data_dir.glob("*.csv"))
    logger.info(f"扫描 {len(files)} 只，数据目录 {data_dir}")
    names = load_names()

    rows = []
    for i, f in enumerate(files, 1):
        if i % 500 == 0:
            logger.info(f"  进度 {i}/{len(files)}")
        symbol = f.stem[:6]
        df = load_stock(f, date)
        if df is None or len(df) < 120:
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        try:
            gs = zg_b1_brick.generate_signals(df, symbol=symbol, **params)
        except Exception as e:
            logger.debug(f"{symbol} 计算异常: {e}")
            continue
        if len(gs) == 0:
            continue
        # 只保留最新交易日当天触发的信号（当日选股）
        last_day = df.index[-1]
        if gs.index[-1] != last_day:
            continue
        r = gs.iloc[-1]
        snap = r["factor_snapshot"]
        rows.append({
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "signal_date": last_day.strftime("%Y-%m-%d"),
            "close": snap.get("close"),
            "brick_position": int(r["brick_position"]),
            "confidence": r["confidence"],
            "stop_loss": r["stop_loss"],
            "stop_pct": round((snap.get("close", 0) - r["stop_loss"]) / snap.get("close", 1) * 100, 2)
                        if snap.get("close") else None,
            "exit_hint": r["exit_hint"],
            "kdj_j": round(snap.get("kdj_j", float("nan")), 1),
            "macd_dif": round(snap.get("macd_dif", float("nan")), 3),
        })

    if not rows:
        logger.info("今日无 Z哥融合信号。")
        return pd.DataFrame()

    out = pd.DataFrame(rows).sort_values(
        ["confidence", "brick_position"], ascending=[False, True]
    ).head(top).reset_index(drop=True)
    return out


def write_reports(out: pd.DataFrame, date: str, macro_desc: str) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    csv_path = REPORTS_DIR / f"zg_screen_{date}.csv"
    out.to_csv(csv_path, index=False)
    md = [
        f"# Z哥融合选股 · {date}",
        "",
        f"> B1买点 + 砖型图周期早段 + 只输一根K线止损 · 大盘：{macro_desc}",
        f"> 命中 {len(out)} 只（独立试验，不构成投资建议）",
        "",
        "| 代码 | 名称 | 收盘 | 砖位 | 置信 | 止损 | 止损% | 离场提示 | J | DIF |",
        "|------|------|------|------|------|------|-------|---------|---|-----|",
    ]
    for _, r in out.iterrows():
        md.append(
            f"| {r['symbol']} | {r['name']} | {r['close']} | 第{r['brick_position']}砖 "
            f"| {r['confidence']} | {r['stop_loss']} | {r['stop_pct']}% "
            f"| {r['exit_hint'] or '—'} | {r['kdj_j']} | {r['macd_dif']} |"
        )
    md_path = REPORTS_DIR / f"zg_screen_{date}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    logger.info(f"报告已输出：{csv_path.name} / {md_path.name}")


def main():
    ap = argparse.ArgumentParser(description="Z哥融合选股（独立版）")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--data-dir", default=None, help="数据目录，默认 settings.DATA_DIR")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--ignore-macro", action="store_true", help="忽略择时闸门强制扫描")
    ap.add_argument("--early-max", type=int, default=2, help="砖型图早段红砖上限")
    ap.add_argument("--no-brick", action="store_true", help="不强制砖型图早段（仅否决尾段）")
    args = ap.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else Path(DATA_DIR)
    if not data_dir.exists():
        fallback = PROJECT_ROOT / "temp_data"
        logger.warning(f"{data_dir} 不存在，回退到 {fallback}")
        data_dir = fallback

    _, macro_desc = (True, "已忽略") if args.ignore_macro else macro_gate(args.date)
    out = run(
        args.date, data_dir, args.top, args.ignore_macro,
        early_max=args.early_max, require_brick_early=not args.no_brick,
    )
    if len(out) == 0:
        return
    write_reports(out, args.date, macro_desc)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
