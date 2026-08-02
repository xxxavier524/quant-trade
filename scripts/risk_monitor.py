#!/usr/bin/env python3
"""风控监控脚本。

接收持仓CSV，检查每个持仓是否触发减仓条件：
- 单票仓位超过20%
- 持仓数超过5只
- 个股自近60个交易日高点回撤超过15%（v5 P1：旧版用全历史最高，假警报常开）
- 组合浮亏超过总资金的10%（v5 P1：旧版分母只有持仓成本，20%仓位上限下永不触发）
- 个股累计浮亏超过5%（旧版规则名"单日亏损"与实现不符，已改名对齐）

用法:
    python scripts/risk_monitor.py --positions positions.csv --data-dir ./data/day
"""

import argparse
import sys
from pathlib import Path
from datetime import date

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alphapulse.config.settings import (
    MAX_SINGLE_POSITION,
    MAX_HOLDINGS,
    DATA_DIR,
)


def load_positions(positions_path: str) -> pd.DataFrame:
    """加载持仓CSV。

    期望列: symbol, shares, cost_price, current_price (可选), entry_date
    """
    df = pd.read_csv(positions_path, dtype={"symbol": str})
    required = {"symbol", "shares", "cost_price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"持仓CSV缺少必要列: {missing}")
    df["symbol"] = df["symbol"].str.zfill(6)   # 002475 等前导零防丢失
    return df


def check_positions(
    positions: pd.DataFrame,
    data_dir: str,
    total_capital: float = 1_000_000,
) -> list[dict]:
    """逐项检查风控条件。

    Returns:
        list[dict]: 每条警报含 symbol/level/rule/message
    """
    alerts = []

    # 1. 持仓数检查
    if len(positions) > MAX_HOLDINGS:
        alerts.append({
            "symbol": "*",
            "level": "WARN",
            "rule": f"持仓数 > {MAX_HOLDINGS}",
            "message": f"当前持仓 {len(positions)} 只，超过上限 {MAX_HOLDINGS}。建议减仓至 {MAX_HOLDINGS} 只。",
        })

    # CSV 读取缓存：每只股票只读一次（旧版逐条规则重复读 3 次）
    _cache: dict[str, pd.DataFrame | None] = {}

    def _load(symbol: str) -> pd.DataFrame | None:
        if symbol not in _cache:
            csv_path = Path(data_dir) / f"{symbol}.csv"
            df = None
            if csv_path.exists():
                try:
                    df = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
                except Exception:
                    df = None
            _cache[symbol] = df
        return _cache[symbol]

    total_cost = 0.0
    total_value = 0.0

    for _, row in positions.iterrows():
        symbol = row["symbol"]
        shares = row["shares"]
        cost_price = row["cost_price"]

        # 获取最新价格（行内 current_price 优先，否则读数据目录一次）
        current_price = row.get("current_price", np.nan)
        stock_data = _load(symbol)
        if (pd.isna(current_price) or current_price is None) \
                and stock_data is not None and len(stock_data) > 0:
            current_price = float(stock_data.iloc[-1]["close"])

        if pd.isna(current_price) or current_price == 0:
            alerts.append({
                "symbol": symbol,
                "level": "WARN",
                "rule": "无法获取最新价格",
                "message": f"{symbol}: 无法从数据目录获取最新价格。",
            })
            continue

        current_value = shares * current_price
        total_cost += shares * cost_price
        total_value += current_value

        # 2. 单票仓位检查
        position_pct = current_value / total_capital
        if position_pct > MAX_SINGLE_POSITION:
            alerts.append({
                "symbol": symbol,
                "level": "CRITICAL",
                "rule": f"单票仓位 > {MAX_SINGLE_POSITION:.0%}",
                "message": f"{symbol}: 当前仓位 {position_pct:.1%}（{current_value:.0f}元），超过上限 {MAX_SINGLE_POSITION:.0%}。建议减至 {shares * MAX_SINGLE_POSITION / position_pct:.0f} 股。",
            })

        # 3. 个股回撤检查（需历史数据）
        # v5 P1（2026-08-02）：回撤基准改为近 60 个交易日高点。
        # 旧版用全历史最高价——任何早年大牛的票都永久触发，是常开假警报。
        if stock_data is not None and len(stock_data) > 0 and "high" in stock_data:
            recent_high = float(stock_data["high"].tail(60).max())
            if recent_high > 0:
                drawdown = (recent_high - current_price) / recent_high
                if drawdown > 0.15:
                    alerts.append({
                        "symbol": symbol,
                        "level": "WARN",
                        "rule": "近60日高点回撤 > 15%",
                        "message": f"{symbol}: 近60日高点 {recent_high:.2f}，当前 {current_price:.2f}，回撤 {drawdown:.1%}。",
                    })

        # 4. 个股盈亏检查（累计浮亏，非单日——规则名已对齐实现）
        pnl_pct = (current_price - cost_price) / cost_price
        if pnl_pct < -0.05:
            alerts.append({
                "symbol": symbol,
                "level": "INFO",
                "rule": "个股浮亏 > 5%",
                "message": f"{symbol}: 成本 {cost_price:.2f}，当前 {current_price:.2f}，浮动盈亏 {pnl_pct:.1%}。",
            })

    # 5. 组合亏损（v5 P1）：分母改用总资金（含现金）。
    # 旧版分母只有持仓成本——单票≤20%仓位下，持仓全亏完也到不了10%，
    # 该 CRITICAL 规则实际是死规则，永远不触发。
    if total_cost > 0 and total_capital > 0:
        portfolio_loss = (total_cost - total_value) / total_capital
        if portfolio_loss > 0.10:
            alerts.append({
                "symbol": "*",
                "level": "CRITICAL",
                "rule": "组合浮亏 > 10%（占总资金）",
                "message": f"组合总成本 {total_cost:.0f}，当前市值 {total_value:.0f}，"
                           f"占总资金 {portfolio_loss:.1%}。建议减仓或止损。",
            })

    return sorted(alerts, key=lambda a: {"CRITICAL": 0, "WARN": 1, "INFO": 2}.get(a["level"], 3))


def check_holding_discipline(positions: pd.DataFrame, data_dir: str) -> list[dict]:
    """Z哥持仓纪律检查（P0应对层集成，docs/research_journal/12_*）。

    与 check_positions 的仓位/回撤规则互补，逐票执行：
    - S1 当日出现（先信，不研究真假）→ CRITICAL
    - DD 增强（连续两天收盘<前日最低）→ CRITICAL
    - BBI 两日破位 → CRITICAL 清仓
    - 防卖飞 V1.4 评分：≤2 离场 WARN / =3 减半 WARN / ≥4 INFO 持有
    - 卤煮止盈（BBI上两根中大阳）→ WARN 减半
    - 高位换手出货（4K累计≥160%）→ WARN
    - 组合摸顶税：浮盈>20% 时给出计提减仓建议 INFO

    注意：防卖飞评分只用于持仓管理，绝不作为开新仓依据（V1.4 第4条）。
    """
    from alphapulse.factors import bbi, sell_score_v14, s1_sell_signal, dd_sell_signal
    from alphapulse.factors.turnover_signals import compute_high_turnover_exit
    from alphapulse.utils.top_tax import top_tax_cut

    alerts: list[dict] = []
    total_cost = total_value = 0.0

    for _, row in positions.iterrows():
        symbol = str(row["symbol"])
        csv_path = Path(data_dir) / f"{symbol}.csv"
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
        except Exception:
            continue
        if len(df) < 120 or not {"open", "high", "low", "close", "volume"} <= set(df.columns):
            continue

        close = float(df["close"].iloc[-1])
        total_cost += row["shares"] * row["cost_price"]
        total_value += row["shares"] * close

        # --- S1（最高优先级：先信，不研究真假阴阳） ---
        try:
            if int(s1_sell_signal.compute(df).iloc[-1]) > 0:
                alerts.append({"symbol": symbol, "level": "CRITICAL", "rule": "S1卖出信号",
                               "message": f"{symbol}: 顶部放量阴线（S1），体系纪律=先走。"
                                          "小票清仓，中大票至少减半。"})
        except Exception:
            pass

        # --- DD增强 ---
        try:
            if int(dd_sell_signal.compute(df).iloc[-1]) >= 2:
                alerts.append({"symbol": symbol, "level": "CRITICAL", "rule": "DD增强",
                               "message": f"{symbol}: 连续两天收盘低于前日最低（滴滴增强），基本清仓。"})
        except Exception:
            pass

        # --- BBI 两日破位 ---
        try:
            if bool(bbi.compute_bbi_break(df).iloc[-1]):
                alerts.append({"symbol": symbol, "level": "CRITICAL", "rule": "BBI两日破位",
                               "message": f"{symbol}: 收盘连续两日跌破BBI，少妇战法离场规则=清仓走人。"})
        except Exception:
            pass

        # --- 防卖飞 V1.4 ---
        try:
            detail = sell_score_v14.compute_detail(df)
            score = int(detail["score"].iloc[-1])
            items = detail.iloc[-1]
            miss = [n for k, n in [("close_up", "收盘跌"), ("bbi_hold", "破BBI"),
                                   ("no_fangliang_yin", "放量阴线"), ("trend_up", "趋势走平/向下"),
                                   ("j_alive", "J死叉")] if not bool(items[k])]
            if score <= 2:
                alerts.append({"symbol": symbol, "level": "WARN", "rule": f"防卖飞评分{score}/5",
                               "message": f"{symbol}: 扣分项[{'/'.join(miss)}]，准备离场。"})
            elif score == 3:
                alerts.append({"symbol": symbol, "level": "WARN", "rule": "防卖飞评分3/5",
                               "message": f"{symbol}: 扣分项[{'/'.join(miss)}]，减一半，等BBI两日破位再清。"})
            else:
                alerts.append({"symbol": symbol, "level": "INFO", "rule": f"防卖飞评分{score}/5",
                               "message": f"{symbol}: 4-5分持有（仅限已持仓，不构成开新仓依据）。"})
        except Exception:
            pass

        # --- 卤煮止盈 ---
        try:
            if bool(bbi.compute_luzhu(df).iloc[-1]):
                alerts.append({"symbol": symbol, "level": "WARN", "rule": "卤煮止盈",
                               "message": f"{symbol}: 站上BBI后连续两根中/大阳线，落袋减半。"})
        except Exception:
            pass

        # --- 高位换手出货 ---
        try:
            if bool(compute_high_turnover_exit(df).iloc[-1]):
                alerts.append({"symbol": symbol, "level": "WARN", "rule": "高位换手≥160%",
                               "message": f"{symbol}: 4根K线累计换手≥160%，筹码快速发散，退出信号。"})
        except Exception:
            pass

    # --- 组合摸顶税 ---
    if total_cost > 0:
        gain = (total_value - total_cost) / total_cost
        if gain > 0.20:
            cut = top_tax_cut(gain)
            alerts.append({"symbol": "*", "level": "INFO", "rule": "摸顶税",
                           "message": f"组合浮盈 {gain:.1%}，按摸顶税规则建议计提减仓约 "
                                      f"{cut:.0%}（浮盈的30%）。顶不可预测，只能靠走出来；"
                                      "不要越到后期越金字塔加仓。"})

    return alerts


def format_alerts_markdown(alerts: list[dict], target_date: str) -> str:
    """格式化风控报告。"""
    if not alerts:
        return f"# AlphaPulse-A 风控报告\n\n**日期**: {target_date}\n\n> ✅ 无风险警报。所有仓位在安全范围内。"

    critical = [a for a in alerts if a["level"] == "CRITICAL"]
    warn = [a for a in alerts if a["level"] == "WARN"]
    info = [a for a in alerts if a["level"] == "INFO"]

    lines = [
        f"# AlphaPulse-A 风控报告",
        f"",
        f"**日期**: {target_date}",
        f"**总警报**: {len(alerts)}（🔴 CRITICAL: {len(critical)} / 🟡 WARN: {len(warn)} / 🔵 INFO: {len(info)}）",
        f"",
    ]

    for level, emoji, label in [
        ("CRITICAL", "🔴", "严重警报"),
        ("WARN", "🟡", "警告"),
        ("INFO", "🔵", "提示"),
    ]:
        subset = [a for a in alerts if a["level"] == level]
        if not subset:
            continue
        lines.append(f"## {emoji} {label} ({len(subset)})")
        lines.append("")
        lines.append("| 代码 | 规则 | 详情 |")
        lines.append("|------|------|------|")
        for a in subset:
            lines.append(f"| {a['symbol']} | {a['rule']} | {a['message']} |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AlphaPulse-A 风控监控")
    parser.add_argument("--positions", required=True, help="持仓CSV文件路径")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="日线CSV数据目录")
    parser.add_argument("--capital", type=float, default=1_000_000, help="总资金")
    parser.add_argument("--date", default=date.today().isoformat(), help="检查日期")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--no-discipline", action="store_true",
                        help="关闭Z哥持仓纪律检查（S1/DD/BBI破位/防卖飞/卤煮/换手/摸顶税）")
    args = parser.parse_args()

    print(f"[INFO] 加载持仓文件: {args.positions}")
    positions = load_positions(args.positions)
    print(f"[INFO] 持仓数量: {len(positions)}")

    alerts = check_positions(positions, args.data_dir, args.capital)
    if not args.no_discipline:
        alerts += check_holding_discipline(positions, args.data_dir)
        alerts = sorted(alerts, key=lambda a: {"CRITICAL": 0, "WARN": 1, "INFO": 2}.get(a["level"], 3))
    report = format_alerts_markdown(alerts, args.date)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[INFO] 报告已保存至: {args.output}")
    else:
        print(report)

    # 有 CRITICAL 时 exit 1
    if any(a["level"] == "CRITICAL" for a in alerts):
        sys.exit(1)


if __name__ == "__main__":
    main()
