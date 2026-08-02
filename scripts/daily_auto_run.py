#!/usr/bin/env python3
"""Nightly automated run (02:00): 真实信号复盘 + 因子权重更新。

2026-07-11 重写：此前夜场报告基于 mock_signals 占位假数据（硬编码20只/买价10元/
固定2026-05-01），"参数优化"的评估函数是参数求和——两者输出均无意义却每天推飞书。
现改为：
1. 复盘 = signal_tracker 真实追踪库（选股 Top50 的 5日/+5% 成功率，按战法分列）
2. 假参数优化下线（run_param_sweep 需要真实评估函数才有意义，待接
   alphapulse.screening 的纯选股成功率评估后再启用）
3. 因子权重 IC 调权 = scripts/ic_weight_tuning.py --apply（手动入口，写入 B1_SCORE）。
   2026-08-02 移除原 nightly 调权：它对 B1B2/BRICK/NEEDLE 三个空策略名算权重，
   与消费方 B1_SCORE 永远对不上，是纯 no-op（写键/读键/消费键三者不一致）。
"""
import json
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

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


def build_nightly_summary(reports_dir: Path | None = None) -> str:
    """夜场报告 = 追踪库真实成功率（与15:30复盘同源，凌晨视角再确认一次）。

    reports_dir 仅测试注入用（默认项目 reports/）。
    """
    reports_dir = reports_dir or (Path(__file__).resolve().parent.parent / "reports")
    from alphapulse.tracking import signal_tracker as tk
    stats = tk.success_stats(window_days=30)
    lines = [f"🔬 夜场报告 ({datetime.now():%Y-%m-%d}) — 真实追踪数据",
             f"近30日选股已实现胜率（唯一主口径：持有{tk.HORIZON_DAYS}日/破{abs(tk.STOP_DROP_PCT):.0f}%止损/"
             f"扣费≈{tk.ROUND_TRIP_COST_PCT:.2f}%）:"]
    for fam, s in stats.items():
        if s["resolved"] == 0 and s["tracking"] == 0 and s["n_realized"] == 0:
            continue
        rw = f"{s['realized_win']}%" if s["realized_win"] is not None else "—"
        rm = f"{s['realized_mean']:+.2f}%" if s["realized_mean"] is not None else "—"
        touch = f"{s['touch_rate']}%" if s["touch_rate"] is not None else "—"
        lines.append(f"· {fam}: 实盘{s['n_realized']}单={rw} 均值{rm}"
                     f" | 曾触及+5%={touch} 跟踪中{s['tracking']} 止踪{s['stopped']}")

    # v5 P0-3：硬闸门关闭必须提示（此前选股静默返回空，无人值守空转无告警）
    try:
        gate_files = sorted(reports_dir.glob("gate_closed_*.json"))
        if gate_files:
            latest = json.loads(gate_files[-1].read_text(encoding="utf-8"))
            gdate = latest.get("date", "?")
            gmsgs = "；".join(latest.get("gates", [])) or "上证MACD零轴/大盘S1关闭"
            lines.insert(1, f"🚧 硬闸门关闭中（自 {gdate}）：{gmsgs} → 今日不开新仓")
    except Exception as e:
        logger.warning(f"闸门标记读取失败: {e}")
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

    # v5 P1（2026-08-02）：nightly 调权是死代码（空策略名 + 空 IC 历史 → no-op），
    # 已移除。IC 调权唯一入口 = scripts/ic_weight_tuning.py --apply（手动，写 B1_SCORE）。
    logger.info("=== IC 调权: 手动入口 scripts/ic_weight_tuning.py --apply ===")

    logger.info(f"Done in {(time.monotonic() - start) / 60:.0f}min")
    if summary and FEISHU_WEBHOOK_URL:
        send_feishu(FEISHU_WEBHOOK_URL, summary)


if __name__ == "__main__":
    main()
