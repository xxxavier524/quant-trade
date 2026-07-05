#!/usr/bin/env python3
"""Nightly automated run: 00:00-07:00 backtest + optimization + factor update."""
import sys, time, logging
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent))
import pandas as pd
from alphapulse.backtest.short_term_bt import run_short_backtest, init_db
from alphapulse.backtest.bt_storage import query_strategy_stats
from alphapulse.ml.auto_research import AutoResearch
from alphapulse.ranking.factor_weighter import FactorWeighter
from alphapulse.notify.feishu_bot import send_feishu
from alphapulse.config.settings import FEISHU_WEBHOOK_URL, AUTO_RESEARCH_START_HOUR, AUTO_RESEARCH_END_HOUR, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nightly_runner")
DATA_DIR = Path(DATA_DIR) if DATA_DIR else Path(__file__).resolve().parent.parent / "data" / "day"

def validate_data():
    files = list(DATA_DIR.glob("*.csv"))
    logger.info(f"Data check: {len(files)} CSV files")
    if len(files) < 4000: logger.warning(f"Low file count: {len(files)}, expected ~5229")
    return len(files) >= 4000

def run_nightly_backtest():
    logger.info("=== Nightly Backtest ===")
    init_db()
    stock_data = {}
    for f in list(DATA_DIR.glob("*.csv"))[:100]:
        # TODO: Increase to full universe (5229 stocks) once performance validates
        # Currently limited to 100 for development speed
        sym = f.stem
        df = pd.read_csv(f, parse_dates=["date"])
        if len(df) >= 60: stock_data[sym] = df.tail(120)
    # TODO: Replace mock signals with real strategy output from daily_screener
    # Currently using placeholder data for demo purposes
    mock_signals = pd.DataFrame([{"symbol":s,"name":"","strategy":"B1B2","date":"2026-05-01",
        "signal_type":"B1","buy_price":10.0,"sector":"","macro_level":"震荡偏多","score":75,"grade":"A"}
        for s in list(stock_data.keys())[:20]])
    stats = run_short_backtest(mock_signals, stock_data, max_hold_days=20)
    logger.info(f"Backtest: {stats}")
    return stats

def run_nightly_optimization():
    logger.info("=== Auto-Research ===")
    ar = AutoResearch()
    for task in ar.get_optimization_tasks():
        strategy = task["strategy"]
        logger.info(f"Optimizing {strategy}...")
        # TODO: Replace with real backtest evaluation running actual strategies
        # Currently returns arbitrary score based on parameter sum
        def make_eval(s):
            def eval_fn(params):
                return sum(v for v in params.values() if isinstance(v,(int,float))) / 100
            return eval_fn
        result = ar.run_param_sweep(strategy, task["param_grid"], make_eval(strategy), 0.3)
        logger.info(f"{strategy}: improved={result['improved']}, best={result['best_params']}")

def run_factor_update():
    logger.info("=== Factor Weight Update ===")
    fw = FactorWeighter()
    for strategy in ["B1B2","BRICK","NEEDLE"]:
        weights = fw.compute_weights(strategy, half_life=30)
        logger.info(f"{strategy} weights: {weights}")
    fw.save()

def send_nightly_summary(stats):
    if not FEISHU_WEBHOOK_URL: return
    msg = f"🔬 夜场优化报告 ({datetime.now().strftime('%Y-%m-%d')})\n"
    for s, v in stats.items():
        msg += f"{s}: 胜率 {v.get('win_rate','N/A')}% 平均收益 {v.get('avg_return','N/A')}%\n"
    send_feishu(FEISHU_WEBHOOK_URL, msg)

def main():
    logger.info("=== Nightly Runner Starting ===")
    start = time.monotonic()
    if not validate_data(): logger.warning("Data validation failed")
    stats = {}
    try: stats = run_nightly_backtest()
    except Exception as e: logger.error(f"Backtest failed: {e}")
    now_hour = datetime.now().hour + datetime.now().minute/60
    if AUTO_RESEARCH_START_HOUR <= now_hour <= AUTO_RESEARCH_END_HOUR:
        try: run_nightly_optimization()
        except Exception as e: logger.error(f"Optimization failed: {e}")
    try: run_factor_update()
    except Exception as e: logger.error(f"Factor update failed: {e}")
    logger.info(f"Done in {(time.monotonic()-start)/60:.0f}min")
    send_nightly_summary(stats)

if __name__ == "__main__":
    main()
