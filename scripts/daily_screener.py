#!/usr/bin/env python3
"""Daily screening pipeline - runs at 15:30 after market close.
Usage: python scripts/daily_screener.py [--full] [--output report.md]
"""
import sys, time, logging, argparse
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from alphapulse.market.macro_position import compute_macro_score
from alphapulse.market.sector_strength import rank_sectors, get_strong_sectors
from alphapulse.notify.feishu_bot import push_daily_screening
from alphapulse.config.settings import (
    DATA_SOURCES_PRIORITY, FEISHU_WEBHOOK_URL, STREAMLIT_PORT)
from alphapulse.utils.data_fetcher import DataFetcher
from alphapulse.factors.b1_formula import compute as b1_formula_compute
from alphapulse.strategies.brick import generate_signals as brick_signals
from alphapulse.strategies.needle_enhanced import generate_signals as needle_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_screener")

DATA_DIR = Path("/Volumes/Mac-480g外接/quantan_data/day/")
OUTPUT_DIR = Path(__file__).parent.parent / "reports"
DATA_UPDATE_TIMEOUT_SEC = 30  # max time to spend on data updates

def load_stock_data(symbol):
    path = DATA_DIR / f"{symbol}.csv"
    if not path.exists(): return pd.DataFrame()
    return pd.read_csv(path, parse_dates=["date"])

def _check_timeout(start_time, timeout_min, context):
    elapsed = (time.monotonic() - start_time) / 60
    if elapsed > timeout_min:
        logger.warning(f"TIMEOUT at {elapsed:.0f}min: {context}")
        return True
    return False

def _generate_report(macro, results, strong_sectors):
    date_str = datetime.now().strftime("%Y-%m-%d")
    report = f"# AlphaPulse 选股日报 ({date_str})\n\n## 大盘\n评分: {macro['score']}/100 档位: {macro['level']}\n\n## 强势板块\n{', '.join(strong_sectors[:5]) if strong_sectors else '无数据'}\n\n"
    for name, key in [("B1B2","B1B2"),("砖型图","BRICK"),("单针","NEEDLE")]:
        report += f"## {name} 信号 ({len(results.get(key,[]))}个)\n"
        for s in results.get(key, [])[:10]:
            report += f"- {s.get('symbol','')} ({s.get('signal_type','')})\n"
        report += "\n"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / f"daily_report_{date_str}.md", "w") as f: f.write(report)
    logger.info(f"Report: {OUTPUT_DIR / f'daily_report_{date_str}.md'}")

def run_screening(force_full=False):
    start_time = time.monotonic()
    results = {"B1B2":[],"BRICK":[],"NEEDLE":[]}
    macro_result = {"score":50,"level":"震荡","sub_scores":{}}
    try:
        logger.info("Step 1/7: Data update (quick check, skip if no network)...")
        fetcher = DataFetcher(sources=DATA_SOURCES_PRIORITY[:1], max_workers=1)  # only try first source
        today = datetime.now().strftime("%Y-%m-%d")
        symbols = [p.stem for p in DATA_DIR.glob("*.csv")]
        update_end = time.monotonic() + DATA_UPDATE_TIMEOUT_SEC
        if not force_full:
            # Quick probe: try updating 3 stocks, if all fail skip update entirely
            for sym in symbols[:3]:
                if time.monotonic() > update_end: break
                df = fetcher.fetch_single(sym, today, today)
                if df is not None and len(df) > 0:
                    existing = load_stock_data(sym)
                    if not existing.empty:
                        pd.concat([existing, df]).drop_duplicates(subset=["date"]).to_csv(DATA_DIR/f"{sym}.csv", index=False)
            logger.info("Data update done (or skipped due to network issues)")
        logger.info(f"Total CSV files available: {len(symbols)}")
        logger.info("Step 2/7: Macro position...")
        sh_idx = load_stock_data("000001")
        sz_idx = load_stock_data("399001")
        cyb_idx = load_stock_data("399006")
        if not sh_idx.empty:
            macro_result = compute_macro_score(sh_idx, sz_idx, cyb_idx)
            logger.info(f"Macro: {macro_result['score']}/100 {macro_result['level']}")
        logger.info("Step 3/7: Sector strength...")
        strong_sectors = get_strong_sectors(0.5)
        logger.info(f"Strong sectors: {strong_sectors[:5]}...")
        logger.info("Step 4/7: Strategy screening...")
        sample_symbols = [p.stem for p in DATA_DIR.glob("*.csv")][:200]
        for sym in sample_symbols:
            if _check_timeout(start_time, 30, f"screening {sym}"): break
            df = load_stock_data(sym)
            if df.empty or len(df) < 60: continue
            try:
                # --- B1B2: detect fresh False->True transition in last 8 trading days ---
                b1_raw = b1_formula_compute(df)
                if b1_raw is not None and len(b1_raw) > 0:
                    sig_int = b1_raw.astype(int)
                    diffs = sig_int.diff()
                    if (diffs.tail(8) == 1).any():
                        results["B1B2"].append({"symbol": sym, "signal_type": "B1"})

                # --- BRICK: latest signal within last 20 trading days ---
                br = brick_signals(df, symbol=sym)
                if len(br) > 0 and br["signal"].any():
                    sig_rows = br[br["signal"].astype(bool)]
                    trading_days_ago = int(df.index[-1]) - int(sig_rows.index[-1])
                    if 0 <= trading_days_ago <= 10:
                        results["BRICK"].append({"symbol": sym, "signal_type": br.iloc[-1].get("signal_type", "BRICK")})

                # --- NEEDLE: latest signal within last 20 trading days ---
                n = needle_signals(df, symbol=sym, mode="needle")
                if len(n) > 0 and n["signal"].any():
                    sig_rows = n[n["signal"].astype(bool)]
                    trading_days_ago = int(df.index[-1]) - int(sig_rows.index[-1])
                    if 0 <= trading_days_ago <= 10:
                        results["NEEDLE"].append({"symbol": sym, "signal_type": n.iloc[-1].get("signal_type", "NEEDLE")})
            except Exception as e: logger.debug(f"Error {sym}: {e}")
        logger.info(f"Signals: B1B2={len(results['B1B2'])}, BRICK={len(results['BRICK'])}, NEEDLE={len(results['NEEDLE'])}")
        if FEISHU_WEBHOOK_URL:
            push_daily_screening(FEISHU_WEBHOOK_URL, macro_result, {"strong_sectors":strong_sectors},
                                 results["B1B2"], results["BRICK"], results["NEEDLE"], web_url=f"http://localhost:{STREAMLIT_PORT}")
        _generate_report(macro_result, results, strong_sectors)
    except Exception as e: logger.error(f"Pipeline error: {e}", exc_info=True)
    logger.info(f"Screening done in {(time.monotonic()-start_time)/60:.0f}min")
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    run_screening(force_full=args.full)
