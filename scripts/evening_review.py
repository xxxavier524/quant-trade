"""晚间复盘 CLI — 选股成功率跟踪报告（2026-07-10 重写，接入 signal_tracker 闭环）。

统计口径（用户定义）：
- 每只选出的股票跟踪 5 个交易日
- 5日内相对选入日收盘涨超 +5% = 脱离成本区（成功），自动生成复盘
- 累计跌超 -5% = 大幅下跌，停止跟踪
- 成功率按两大战法（基本面法/砖型图法）分开统计

15:30 eod_pipeline 里的 track_signals.py 每天自动做同样的事并推飞书；
本脚本是手动/按需入口：只读统计+可选推送，不重复录入。

用法：
    python scripts/evening_review.py             # 打印复盘报告
    python scripts/evening_review.py --push      # 同时推飞书
    python scripts/evening_review.py --window 60 # 统计窗口改为60天
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.config.settings import FEISHU_WEBHOOK_URL  # noqa: E402
from alphapulse.tracking import signal_tracker as tk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="推送飞书")
    ap.add_argument("--window", type=int, default=30, help="成功率统计窗口（自然日）")
    ap.add_argument("--output", help="Markdown 输出路径（可选）")
    args = ap.parse_args()

    stats = tk.success_stats(window_days=args.window)
    text = tk.nightly_review_text()

    md = [f"# 晚间复盘（近{args.window}日）\n",
          f"实盘口径（唯一主口径，v5）：持有{tk.HORIZON_DAYS}个交易日收盘退出，"
          f"期间收盘破{abs(tk.STOP_DROP_PCT):.0f}%即止损，扣往返成本≈{tk.ROUND_TRIP_COST_PCT:.2f}%；"
          f"'曾触及+5%'仅作对照（路径最大值，偏乐观）\n",
          "| 战法 | 已结算 | 实盘胜率 | 实盘均值 | 曾触及+5% | 跟踪中 | 大跌止踪 |",
          "|---|---|---|---|---|---|---|"]
    for fam, s in stats.items():
        rw = f"{s['realized_win']}%" if s["realized_win"] is not None else "—"
        rm = f"{s['realized_mean']:+.2f}%" if s["realized_mean"] is not None else "—"
        touch = f"{s['touch_rate']}%" if s["touch_rate"] is not None else "—"
        md.append(f"| {fam} | {s['n_realized']} | {rw} | {rm} | {touch} "
                  f"| {s['tracking']} | {s['stopped']} |")
    report = "\n".join(md)
    print(report)
    print("\n--- 飞书文本预览 ---\n" + text)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"\n已写入 {args.output}")

    if args.push and FEISHU_WEBHOOK_URL:
        from alphapulse.notify.feishu_bot import send_feishu
        ok = send_feishu(FEISHU_WEBHOOK_URL, text)
        print(f"飞书推送: {'成功' if ok else '失败'}")


if __name__ == "__main__":
    main()
