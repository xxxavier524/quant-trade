#!/usr/bin/env python3
"""AlphaPulse-A 独立回测引擎。

不依赖 VeighNa，直接使用 alphapulse 策略在日线数据上回测。

用法:
    python scripts/run_backtest.py --strategy B1 --data-dir /path/to/day --start 2020-01-01 --end 2025-12-31
    python scripts/run_backtest.py --strategy ALL --sample 50  # 在50只股票上测试所有策略
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import date
from collections import defaultdict

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.config.settings import (
    DATA_DIR, INITIAL_CAPITAL, BACKTEST_RESULTS_DIR,
    SLIPPAGE_BUY, SLIPPAGE_SELL,
)
from alphapulse.strategies.b1_formula_strategy import generate_signals as b1_signals
from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick_signals
from alphapulse.strategies.needle_enhanced import generate_signals as needle_signals
from alphapulse.utils.backtest_utils import (
    apply_slippage, calc_commission, calc_max_shares,
)

STRATEGIES = {"B1": b1_signals, "BRICK": brick_signals, "NEEDLE": needle_signals}


class BacktestEngine:
    """独立回测引擎。

    逐日遍历，在每个交易日：
    1. 加载当日前的历史数据
    2. 运行信号生成器
    3. 执行买入/卖出（含滑点、手续费、仓位限制）
    4. 记录持仓和净值曲线

    成交假设（2026-07-11 修正）：
    - 信号日收盘后确认信号，次一交易日【开盘价】成交（此前按信号当日收盘成交，
      现实中收盘才知信号，系统性乐观）
    - 开盘较前收涨幅 ≥9.8% 视为涨停无法买入，跳过该信号；成交量为0（停牌）跳过
    - 卖出在触发日收盘执行（EOD 系统收盘检查止损/止盈/到期）

    已知局限（诚实入账）：universe 为现存股票，无退市股 → 多年期结果有幸存者偏差；
    不模拟盘中触价，止损按收盘价判定。
    """

    LIMIT_UP_PCT = 0.098  # 开盘涨幅超此值视为涨停买不进（主板10%留缓冲；创业板20%从宽）

    def __init__(
        self,
        initial_capital: float = INITIAL_CAPITAL,
        max_holdings: int = 5,
        max_single_pct: float = 0.20,
        max_hold_days: int = 20,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_holdings = max_holdings
        self.max_single_pct = max_single_pct
        self.max_hold_days = max_hold_days  # 持有期上限（交易日），防区间震荡票无限期占坑
        self.holdings = {}       # symbol -> {shares, cost, entry_date}
        self.trades = []         # 交易记录
        self.nav_curve = []      # 净值曲线: [{date, nav, cash, holdings_value}]
        self._cur_date = None

    def run(
        self,
        stocks: dict[str, pd.DataFrame],
        strategy_fn,
        start_date: str,
        end_date: str,
        **strategy_params,
    ) -> dict:
        """运行回测（优化版：预计算信号，分离组合模拟）。

        Args:
            stocks: symbol -> DataFrame (OHLCV, index=date)
            strategy_fn: 信号生成函数
            start_date: 回测起始日
            end_date: 回测结束日

        Returns:
            dict: 回测结果摘要
        """
        # 收集所有交易日
        all_dates = set()
        for df in stocks.values():
            all_dates.update(df.index)
        all_dates = sorted(d for d in all_dates if start_date <= str(d)[:10] <= end_date)
        if len(all_dates) < 60:
            return {"error": "交易日不足"}

        lookback_days = 365
        print(f"  [Phase 1/2] 预计算信号 ({len(stocks)} stocks x ~{len(all_dates)} days)...")

        # Phase 1: 预计算所有股票的信号（只算一次）
        all_signals = {}  # symbol -> set of signal dates
        n_done = 0
        n_errors = 0
        err_samples = []
        for symbol, full_data in stocks.items():
            try:
                signals = strategy_fn(full_data, symbol=symbol, **strategy_params)
                if len(signals) > 0:
                    buy_dates = set(signals[signals["signal"] == 1].index)
                    if buy_dates:
                        all_signals[symbol] = buy_dates
            except Exception as e:
                # v5 P1（2026-08-02）：旧版 except: pass 把策略异常静默吞掉，
                # 系统性故障会表现为"零信号回测成功"。现在计数上报，
                # 错误率过高直接中止而非产出假结果。
                n_errors += 1
                if len(err_samples) < 10:
                    err_samples.append(f"{symbol}: {type(e).__name__}: {e}")
            n_done += 1
            if n_done % 50 == 0:
                print(f"    signals: {n_done}/{len(stocks)} stocks, {sum(len(v) for v in all_signals.values())} total signals")

        if n_errors:
            rate = n_errors / max(len(stocks), 1)
            print(f"[WARN] 信号预计算失败 {n_errors}/{len(stocks)}（{rate:.1%}）", file=sys.stderr)
            for s in err_samples:
                print(f"    {s}", file=sys.stderr)
            if rate > 0.10 or n_errors > 50:
                raise RuntimeError(
                    f"信号预计算错误率过高（{rate:.1%}），疑似系统性故障——"
                    f"已中止而非静默输出零信号。请先修复策略/数据问题。")

        print(f"    signals ready: {len(all_signals)} stocks with signals, {sum(len(v) for v in all_signals.values())} total")

        # 信号日 → 次一交易日开盘执行（收盘后确认信号，当日收盘不可成交）
        exec_dates: dict[str, set] = {}
        for symbol, sig_dates in all_signals.items():
            idx = stocks[symbol].index
            pos = {d: i for i, d in enumerate(idx)}
            ex = set()
            for d in sig_dates:
                i = pos.get(d)
                if i is not None and i + 1 < len(idx):
                    ex.add(idx[i + 1])
            if ex:
                exec_dates[symbol] = ex

        # Phase 2: 组合模拟（快速，只查字典）
        print(f"  [Phase 2/2] 组合模拟...")
        n_days = len(all_dates)
        for di, trade_date in enumerate(all_dates):
            self._cur_date = trade_date

            # 检查持仓退出
            self._check_exits(stocks, trade_date)

            # 检查信号买入（次日开盘）
            for symbol in sorted(exec_dates.keys()):
                if symbol in self.holdings:
                    continue
                if len(self.holdings) >= self.max_holdings:
                    break
                if trade_date not in exec_dates.get(symbol, set()):
                    continue
                if trade_date not in stocks.get(symbol, pd.DataFrame()).index:
                    continue
                self._execute_buy(symbol, stocks[symbol], trade_date, stocks)

            # 记录净值
            hv = self._calc_holdings_value(stocks)
            self.nav_curve.append({"date": trade_date, "nav": self.cash + hv, "cash": self.cash, "holdings_value": hv})

            if (di + 1) % 252 == 0:
                print(f"    sim: {di+1}/{n_days} days")

        return self._compute_metrics()

    def _execute_buy(self, symbol: str, data: pd.DataFrame, trade_date, stocks: dict):
        """执行买入：次日开盘价+滑点；涨停开盘/停牌跳过；仓位按真实总资产。"""
        row = data.loc[trade_date]
        price = row.get("open", row["close"])
        if pd.isna(price) or price <= 0:
            price = row["close"]
        # 停牌（零量）与开盘涨停不可成交
        if float(row.get("volume", 1) or 0) == 0:
            return
        pos = data.index.get_loc(trade_date)
        if pos > 0:
            prev_close = float(data.iloc[pos - 1]["close"])
            if prev_close > 0 and price / prev_close - 1 >= self.LIMIT_UP_PCT:
                return
        buy_price = apply_slippage(price, 1)

        # 总资产必须用各持仓自己的行情估值（此前误用候选股数据估全部持仓 → 仓位失真）
        total_nav = self.cash + self._calc_holdings_value(stocks)
        max_shares = calc_max_shares(buy_price, total_nav)

        if max_shares < 100:
            return

        cost = buy_price * max_shares + calc_commission(buy_price * max_shares)
        if cost > self.cash:
            # 按可用资金重新计算
            affordable = int((self.cash - 5) / buy_price / 100) * 100
            if affordable < 100:
                return
            max_shares = affordable
            cost = buy_price * max_shares + calc_commission(buy_price * max_shares)

        self.cash -= cost
        self.holdings[symbol] = {
            "shares": max_shares,
            "cost": buy_price,
            "entry_date": trade_date,
        }
        self.trades.append({
            "date": trade_date,
            "symbol": symbol,
            "direction": "BUY",
            "price": buy_price,
            "shares": max_shares,
            "cost": cost,
        })

    def _execute_sell(self, symbol: str, data: pd.DataFrame, trade_date, reason: str = "signal"):
        """执行卖出。"""
        if symbol not in self.holdings:
            return
        h = self.holdings[symbol]
        price = data.loc[trade_date, "close"]
        sell_price = apply_slippage(price, -1)
        revenue = sell_price * h["shares"] - calc_commission(sell_price * h["shares"])
        self.cash += revenue
        self.trades.append({
            "date": trade_date,
            "symbol": symbol,
            "direction": "SELL",
            "price": sell_price,
            "shares": h["shares"],
            "revenue": revenue,
            "reason": reason,
            "pnl": revenue - h["cost"] * h["shares"] - calc_commission(h["cost"] * h["shares"]),
        })
        del self.holdings[symbol]

    def _check_exits(self, stocks: dict, trade_date):
        """检查持仓退出条件。"""
        for symbol in list(self.holdings.keys()):
            if symbol not in stocks:
                continue
            data = stocks[symbol]
            if trade_date not in data.index:
                continue

            h = self.holdings[symbol]
            current_price = data.loc[trade_date, "close"]
            pnl_pct = (current_price - h["cost"]) / h["cost"]

            # 止损：-10%
            if pnl_pct < -0.10:
                self._execute_sell(symbol, data, trade_date, "stop_loss")
            # 止盈：+30%
            elif pnl_pct > 0.30:
                self._execute_sell(symbol, data, trade_date, "take_profit")
            # 持有期上限：区间震荡票到期离场，防无限期占坑（最多5坑）
            elif self.max_hold_days:
                try:
                    held = (data.index.get_loc(trade_date)
                            - data.index.get_loc(h["entry_date"]))
                    if held >= self.max_hold_days:
                        self._execute_sell(symbol, data, trade_date, "time_exit")
                except KeyError:
                    pass

    def _calc_holdings_value(self, stocks: dict) -> float:
        """计算当前持仓总市值。"""
        total = 0.0
        for symbol, h in self.holdings.items():
            if symbol in stocks and self._cur_date in stocks[symbol].index:
                total += h["shares"] * stocks[symbol].loc[self._cur_date, "close"]
            else:
                total += h["shares"] * h["cost"]
        return total

    def _compute_metrics(self) -> dict:
        """计算绩效指标（含Calmar/Sortino/连续亏损）。规格书6.2节"""
        if len(self.nav_curve) < 2:
            return {"error": "净值数据不足"}

        nav_df = pd.DataFrame(self.nav_curve)
        nav_df["daily_return"] = nav_df["nav"].pct_change()

        total_return = (nav_df["nav"].iloc[-1] - self.initial_capital) / self.initial_capital
        n_days = len(nav_df)
        annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1

        cummax = nav_df["nav"].cummax()
        drawdown = (nav_df["nav"] - cummax) / cummax
        max_dd = drawdown.min()

        risk_free = 0.03
        excess = nav_df["daily_return"].dropna() - risk_free / 252
        annual_vol = nav_df["daily_return"].std() * np.sqrt(252)

        sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

        # Calmar比率 = 年化收益率 / |最大回撤|
        calmar = annual_return / abs(max_dd) if abs(max_dd) > 0 else 0

        # Sortino比率：仅考虑下行波动率
        downside = nav_df["daily_return"].dropna()
        downside = downside[downside < 0]
        downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-10
        sortino = (annual_return - risk_free) / downside_std if downside_std > 0 else 0

        trades_df = pd.DataFrame(self.trades)
        if len(trades_df) > 0:
            sells = trades_df[trades_df["direction"] == "SELL"]
            if len(sells) > 0 and "pnl" in sells.columns:
                win_rate = (sells["pnl"] > 0).mean()
                avg_win = sells[sells["pnl"] > 0]["pnl"].mean() if (sells["pnl"] > 0).any() else 0
                avg_loss = abs(sells[sells["pnl"] < 0]["pnl"].mean()) if (sells["pnl"] < 0).any() else 0
                profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
                # 最大连续亏损次数
                loss_streak = (sells["pnl"] < 0).astype(int)
                max_consec_losses = 0
                current = 0
                for v in loss_streak:
                    if v:
                        current += 1
                        max_consec_losses = max(max_consec_losses, current)
                    else:
                        current = 0
            else:
                win_rate, profit_loss_ratio, max_consec_losses = 0, 0, 0
        else:
            win_rate, profit_loss_ratio, max_consec_losses = 0, 0, 0

        return {
            "initial_capital": self.initial_capital,
            "final_nav": round(nav_df["nav"].iloc[-1], 2),
            "total_return": round(total_return * 100, 2),
            "annual_return": round(annual_return * 100, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "calmar_ratio": round(calmar, 2),
            "sortino_ratio": round(sortino, 2),
            "win_rate": round(win_rate * 100, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "max_consecutive_losses": max_consec_losses,
            "annual_volatility": round(float(annual_vol) * 100, 2) if annual_vol else 0,
            "total_trades": len(self.trades),
            "n_days": n_days,
        }


def load_stocks(data_dir: str, symbols: list[str] = None, min_days: int = 365) -> dict:
    """加载股票数据。"""
    data_path = Path(data_dir)
    stocks = {}
    n_fail = 0
    files = list(data_path.glob("*.csv"))
    if symbols:
        files = [f for f in files if f.stem in set(symbols)]

    for f in files:
        try:
            df = pd.read_csv(f)
            first_col = df.columns[0]
            try:
                maybe_dates = pd.to_datetime(df[first_col])
                if len(maybe_dates.dropna()) > 0.8 * len(df):
                    df["date"] = maybe_dates
                    df = df.set_index("date")
            except Exception:
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")
            if isinstance(df.index, pd.DatetimeIndex) and len(df) >= min_days:
                stocks[f.stem] = df.sort_index()
        except Exception:
            n_fail += 1

    if n_fail > 20:
        print(f"[WARN] load_stocks: {n_fail} 只股票解析失败被跳过（{data_dir}）",
              file=sys.stderr)

    return stocks


def format_report(results: dict, strategy_name: str, start: str, end: str) -> str:
    """格式化回测报告。"""
    if "error" in results:
        return f"# 回测报告\n\n**策略**: {strategy_name}\n**错误**: {results['error']}\n"

    lines = [
        f"# 回测报告",
        f"",
        f"**策略**: {strategy_name}",
        f"**回测区间**: {start} ~ {end}",
        f"**初始资金**: {results['initial_capital']:,.0f}",
        f"**最终净值**: {results['final_nav']:,.0f}",
        f"",
        f"## 绩效指标",
        f"",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 总收益率 | {results['total_return']}% |",
        f"| 年化收益率 | {results['annual_return']}% |",
        f"| 最大回撤 | {results['max_drawdown']}% |",
        f"| 夏普比率 | {results['sharpe_ratio']} |",
        f"| 胜率 | {results['win_rate']}% |",
        f"| 盈亏比 | {results['profit_loss_ratio']} |",
        f"| 总交易次数 | {results['total_trades']} |",
        f"| 回测天数 | {results['n_days']} |",
        f"",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AlphaPulse-A 回测")
    parser.add_argument("--strategy", default="ALL", choices=["B1", "BRICK", "NEEDLE", "ALL"])
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--symbols", default=None, help="逗号分隔代码，默认全部")
    parser.add_argument("--sample", type=int, default=None, help="随机抽样N只")
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--mode", default="standard", help="standard or short")
    parser.add_argument("--output", default=None)
    parser.add_argument("--include-delisted", action="store_true",
                        help="加载退市股(数据盘 delisted/ 目录)修正幸存者偏差；"
                             "退市股不受 --sample 抽样影响，全量并入")
    args = parser.parse_args()

    # v3.0: Short-term backtest mode（修复：原版引用未定义变量直接NameError）
    if args.mode == "short":
        from alphapulse.backtest.short_term_bt import run_short_backtest

        stock_data = load_stocks(args.data_dir)
        if args.sample and len(stock_data) > args.sample:
            import random
            random.seed(42)
            keys = random.sample(list(stock_data.keys()), args.sample)
            stock_data = {k: stock_data[k] for k in keys}

        strategies = list(STRATEGIES.items()) if args.strategy == "ALL" \
            else [(args.strategy, STRATEGIES[args.strategy])]
        sig_rows = []
        for strat_name, strat_fn in strategies:
            for symbol, df in stock_data.items():
                try:
                    sigs = strat_fn(df, symbol=symbol)
                except Exception:
                    continue
                if len(sigs) == 0 or "signal" not in sigs.columns:
                    continue
                # v5 P1：旧版 astype(bool) 会把 -1（卖出信号）当买入——
                # BRICK 类策略的卖出行会被错误计为买点。
                hit = sigs[sigs["signal"] == 1]
                # generate_signals 以信号日为索引（df.index 值）
                for idx, srow in hit.iterrows():
                    d = str(idx)[:10]
                    if not (args.start <= d <= args.end):
                        continue
                    snap = srow.get("factor_snapshot") or {}
                    price = snap.get("close") if isinstance(snap, dict) else None
                    if price is None:
                        try:
                            price = float(df.loc[idx, "close"])
                        except Exception:
                            continue
                    sig_rows.append({
                        "symbol": symbol, "name": "", "strategy": strat_name,
                        "date": d, "signal_type": strat_name,
                        "buy_price": float(price),
                    })
        signals = pd.DataFrame(sig_rows)
        print(f"[INFO] 信号预计算完成: {len(signals)} 条")
        if signals.empty:
            print("[ERROR] 区间内无信号")
            return
        stats = run_short_backtest(signals, stock_data)
        print(json.dumps(stats, indent=2, ensure_ascii=False, default=str))
        return

    print(f"[INFO] 加载数据: {args.data_dir}")
    stocks = load_stocks(args.data_dir)
    if args.sample and len(stocks) > args.sample:
        import random
        random.seed(42)
        keys = random.sample(list(stocks.keys()), args.sample)
        stocks = {k: stocks[k] for k in keys}
    if args.symbols:
        syms = set(args.symbols.split(","))
        stocks = {k: v for k, v in stocks.items() if k in syms}

    if args.include_delisted:
        delisted_dir = Path(args.data_dir).parent / "delisted"
        delisted = load_stocks(str(delisted_dir), min_days=200)
        # 按真实市场占比并入：现存股被 --sample 抽样时，退市股按同比例抽样，
        # 否则退市股在universe里的权重会被放大（239全量 vs 300现存 = 44%，
        # 真实占比仅 ~4.4%，会把偏差高估一个数量级）
        if args.sample:
            import random
            n_alive_all = len(list(Path(args.data_dir).glob("*.csv")))
            n_del = max(1, round(len(delisted) * len(stocks) / max(n_alive_all, 1)))
            random.seed(43)
            keys = random.sample(list(delisted.keys()), min(n_del, len(delisted)))
            delisted = {k: delisted[k] for k in keys}
        n_before = len(stocks)
        for k, v in delisted.items():
            stocks.setdefault(k, v)
        print(f"[INFO] 退市股并入: +{len(stocks) - n_before} 只（{delisted_dir}，按占比抽样）")

    print(f"[INFO] 可用股票: {len(stocks)} 只")
    if len(stocks) == 0:
        print("[ERROR] 无可用数据")
        return

    strategies_to_run = list(STRATEGIES.items()) if args.strategy == "ALL" else [(args.strategy, STRATEGIES[args.strategy])]

    all_results = {}
    for name, fn in strategies_to_run:
        print(f"[INFO] 运行 {name} 回测...")
        engine = BacktestEngine(initial_capital=args.capital)
        t0 = time.time()
        results = engine.run(stocks, fn, args.start, args.end)
        elapsed = time.time() - t0
        results["elapsed_seconds"] = round(elapsed, 1)
        all_results[name] = results
        report = format_report(results, name, args.start, args.end)
        print(report)

    # 保存结果
    Path(BACKTEST_RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else Path(BACKTEST_RESULTS_DIR) / f"backtest_{date.today().isoformat()}.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"[INFO] 结果已保存: {out_path}")


if __name__ == "__main__":
    main()
