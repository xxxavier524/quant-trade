#!/usr/bin/env python3
"""Nightly automated run (02:00): 真实信号复盘 + 因子权重更新。

2026-07-11 重写：此前夜场报告基于 mock_signals 占位假数据（硬编码20只/买价10元/
固定2026-05-01），"参数优化"的评估函数是参数求和——两者输出均无意义却每天推飞书。
现改为：
1. 复盘 = signal_tracker 真实追踪库（选股 Top50 的 5日/+5% 成功率，按战法分列）
2. 假参数优化下线（run_param_sweep 需要真实回测评估函数才有意义，待接
   scripts/run_backtest.py 的组合级评估后再启用）
3. 因子权重 IC 更新保留（FactorWeighter，无 IC 历史时不写权重）
"""
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from alphapulse.ranking.factor_weighter import FactorWeighter
from alphapulse.notify.feishu_bot import send_feishu
from alphapulse.config.settings import FEISHU_WEBHOOK_URL, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nightly_runner")
DATA_DIR = Path(DATA_DIR)


def validate_data() -> bool:
    files = list(DATA_DIR.glob("*.csv"))
    logger.info(f"Data check: {len(files)} CSV files")
    if len(files) < 4000:
        logger.warning(f"Low file count: {len(files)}, expected ~5229")
    return len(files) >= 4000


def run_factor_update():
    logger.info("=== Factor Weight Update ===")
    fw = FactorWeighter()
    for strategy in ["B1B2", "BRICK", "NEEDLE"]:
        weights = fw.compute_weights(strategy, half_life=30)
        logger.info(f"{strategy} weights: {weights}")
    fw.save()


def build_nightly_summary() -> str:
    """夜场报告 = 追踪库真实成功率（与15:30复盘同源，凌晨视角再确认一次）。"""
    from alphapulse.tracking import signal_tracker as tk
    stats = tk.success_stats(window_days=30)
    lines = [f"🔬 夜场报告 ({datetime.now():%Y-%m-%d}) — 真实追踪数据",
             f"近30日选股成功率（{tk.HORIZON_DAYS}日内+{tk.SUCCESS_PCT:.0f}%脱离成本区）:"]
    for fam, s in stats.items():
        if s["resolved"] == 0 and s["tracking"] == 0:
            continue
        rate = f"{s['rate']}%" if s["rate"] is not None else "—"
        lines.append(f"· {fam}: {s['success']}/{s['resolved']}={rate}"
                     f" | 跟踪中{s['tracking']} 止踪{s['stopped']}")
    rep = tk.weekly_report()
    if not rep.empty:
        lines.append(f"近一周信号 {len(rep)} 条，连涨≥2天 {int((rep['streak'] >= 2).sum())} 条")
    return "\n".join(lines)


def main():
    logger.info("=== Nightly Runner Starting ===")
    start = time.monotonic()
    if not validate_data():
        logger.warning("Data validation failed")

    summary = ""
    try:
        summary = build_nightly_summary()
        logger.info(summary)
    except Exception as e:
        logger.error(f"复盘统计失败: {e}")

    # 参数优化：假评估函数(参数求和)已下线；待接真实回测评估后恢复
    logger.info("=== Auto-Research: 已停用（等待真实回测评估函数接入） ===")

    try:
        run_factor_update()
    except Exception as e:
        logger.error(f"Factor update failed: {e}")

    logger.info(f"Done in {(time.monotonic() - start) / 60:.0f}min")
    if summary and FEISHU_WEBHOOK_URL:
        send_feishu(FEISHU_WEBHOOK_URL, summary)


if __name__ == "__main__":
    main()
