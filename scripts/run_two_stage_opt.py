#!/usr/bin/env python3
"""Two-Stage AI Model: 20-backtest parameter optimization.

Sweeps key parameters across 20 combinations, selects best config.
Output saved to reports/two_stage_opt_results.json
"""

import sys, json, time, random
from pathlib import Path
from datetime import date
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_backtest import BacktestEngine, load_stocks, STRATEGIES
from alphapulse.strategies.two_stage_selection import generate_signals as two_stage_fn
from alphapulse.factors.industry_rotation import load_industry_map, get_industry, rank_industries, build_industry_index as build_indices
from alphapulse.factors.beta_fundamental import predict_beta, rank_stocks_by_beta

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from alphapulse.config.settings import DATA_DIR

# --- Parameter grid: 20 combos ---
# Key tunables:
#   top_industries:     how many mainline industries (3-7)
#   stocks_per_industry: how many stocks per industry (5-15)
#   min_trend_score:    threshold for industry trend score (0.25-0.50)
#   rebalance_freq:     M=monthly, W=weekly
#   max_holdings:       max concurrent positions
#   stop_loss:          stop loss threshold
#   take_profit:        take profit threshold
PARAM_GRID = [
    # Conservative: fewer industries, strict score
    {"top_industries": 3, "stocks_per_industry": 5, "min_trend_score": 0.50, "rebalance_freq": "M", "max_holdings": 8, "stop_loss": -0.08, "take_profit": 0.25},
    {"top_industries": 3, "stocks_per_industry": 8, "min_trend_score": 0.44, "rebalance_freq": "M", "max_holdings": 10, "stop_loss": -0.10, "take_profit": 0.30},
    {"top_industries": 3, "stocks_per_industry": 10, "min_trend_score": 0.38, "rebalance_freq": "M", "max_holdings": 12, "stop_loss": -0.08, "take_profit": 0.30},
    {"top_industries": 3, "stocks_per_industry": 12, "min_trend_score": 0.32, "rebalance_freq": "W", "max_holdings": 15, "stop_loss": -0.12, "take_profit": 0.35},
    {"top_industries": 3, "stocks_per_industry": 15, "min_trend_score": 0.25, "rebalance_freq": "M", "max_holdings": 18, "stop_loss": -0.10, "take_profit": 0.25},
    # Balanced: moderate breadth
    {"top_industries": 4, "stocks_per_industry": 8, "min_trend_score": 0.44, "rebalance_freq": "M", "max_holdings": 12, "stop_loss": -0.10, "take_profit": 0.30},
    {"top_industries": 4, "stocks_per_industry": 10, "min_trend_score": 0.38, "rebalance_freq": "M", "max_holdings": 15, "stop_loss": -0.08, "take_profit": 0.28},
    {"top_industries": 4, "stocks_per_industry": 12, "min_trend_score": 0.35, "rebalance_freq": "W", "max_holdings": 16, "stop_loss": -0.10, "take_profit": 0.32},
    {"top_industries": 4, "stocks_per_industry": 15, "min_trend_score": 0.30, "rebalance_freq": "M", "max_holdings": 20, "stop_loss": -0.12, "take_profit": 0.35},
    {"top_industries": 4, "stocks_per_industry": 6, "min_trend_score": 0.50, "rebalance_freq": "M", "max_holdings": 10, "stop_loss": -0.08, "take_profit": 0.25},
    # Aggressive: more industries, looser score
    {"top_industries": 5, "stocks_per_industry": 10, "min_trend_score": 0.38, "rebalance_freq": "M", "max_holdings": 18, "stop_loss": -0.10, "take_profit": 0.30},
    {"top_industries": 5, "stocks_per_industry": 12, "min_trend_score": 0.32, "rebalance_freq": "W", "max_holdings": 20, "stop_loss": -0.10, "take_profit": 0.30},
    {"top_industries": 5, "stocks_per_industry": 8, "min_trend_score": 0.42, "rebalance_freq": "M", "max_holdings": 15, "stop_loss": -0.08, "take_profit": 0.28},
    {"top_industries": 5, "stocks_per_industry": 15, "min_trend_score": 0.25, "rebalance_freq": "M", "max_holdings": 22, "stop_loss": -0.12, "take_profit": 0.38},
    {"top_industries": 5, "stocks_per_industry": 6, "min_trend_score": 0.46, "rebalance_freq": "M", "max_holdings": 12, "stop_loss": -0.08, "take_profit": 0.25},
    # Wide coverage
    {"top_industries": 6, "stocks_per_industry": 10, "min_trend_score": 0.32, "rebalance_freq": "M", "max_holdings": 20, "stop_loss": -0.10, "take_profit": 0.30},
    {"top_industries": 6, "stocks_per_industry": 12, "min_trend_score": 0.30, "rebalance_freq": "W", "max_holdings": 24, "stop_loss": -0.12, "take_profit": 0.35},
    {"top_industries": 7, "stocks_per_industry": 10, "min_trend_score": 0.30, "rebalance_freq": "M", "max_holdings": 25, "stop_loss": -0.12, "take_profit": 0.35},
    {"top_industries": 7, "stocks_per_industry": 8, "min_trend_score": 0.35, "rebalance_freq": "M", "max_holdings": 20, "stop_loss": -0.10, "take_profit": 0.30},
    # Baseline: moderate everything
    {"top_industries": 5, "stocks_per_industry": 10, "min_trend_score": 0.38, "rebalance_freq": "M", "max_holdings": 15, "stop_loss": -0.10, "take_profit": 0.30},
]


def compute_score(metrics: dict) -> float:
    """Composite score: higher = better.
    Weight: 40% annual_return + 25% (-drawdown) + 20% sharpe + 10% calmar + 5% trades_bonus
    """
    if "error" in metrics:
        return -999
    ret = metrics.get("annual_return", 0) / 100
    dd = abs(metrics.get("max_drawdown", -50)) / 100
    sharpe = metrics.get("sharpe_ratio", 0)
    calmar = metrics.get("calmar_ratio", 0)
    trades = metrics.get("total_trades", 0)

    score = 0.40 * ret
    score -= 0.25 * dd
    score += 0.20 * max(sharpe, 0) / 3  # normalize sharpe
    score += 0.10 * max(calmar, 0) / 3
    score += 0.05 * min(trades / 100, 1.0)
    return round(score, 4)


def run_single_backtest(params: dict, stocks: dict, run_id: int) -> dict:
    """Run one backtest with given params."""
    # Override BacktestEngine defaults
    engine = BacktestEngine(
        initial_capital=1_000_000,
        max_holdings=params["max_holdings"],
        max_single_pct=0.20,
    )
    engine.max_holdings = params["max_holdings"]

    # Monkey-patch stop-loss/take-profit
    original_check_exits = engine._check_exits

    def custom_check_exits(stocks_dict, trade_date):
        for symbol in list(engine.holdings.keys()):
            if symbol not in stocks_dict:
                continue
            data = stocks_dict[symbol]
            if trade_date not in data.index:
                continue
            h = engine.holdings[symbol]
            current_price = data.loc[trade_date, "close"]
            pnl_pct = (current_price - h["cost"]) / h["cost"]
            if pnl_pct < params["stop_loss"]:
                engine._execute_sell(symbol, data, trade_date, "stop_loss")
            elif pnl_pct > params["take_profit"]:
                engine._execute_sell(symbol, data, trade_date, "take_profit")

    engine._check_exits = custom_check_exits

    # Pre-compute EVERYTHING once: industry rankings + beta for all stocks + selection
    print(f"    Pre-computing industry rankings...")
    pre_rankings = rank_industries(stocks, min_constituents=5, top_n=params["top_industries"])
    pre_indices = build_indices(stocks)
    mainline_industries = set(r["industry"] for r in pre_rankings if r["total"] >= params["min_trend_score"])

    # Pre-compute beta for stocks in mainline industries only
    pre_selected = set()
    pre_betas = {}
    pre_scores = {}
    ind_score_map = {r["industry"]: r["total"] for r in pre_rankings}

    for ind in mainline_industries:
        ind_syms = [s for s in stocks if get_industry(s) == ind]
        if len(ind_syms) < 3:
            continue
        ind_stocks = {s: stocks[s] for s in ind_syms}
        ind_returns = pre_indices.get(ind, pd.DataFrame()).get("return") if ind in pre_indices else None

        print(f"    Computing beta for {ind}: {len(ind_syms)} stocks...")
        ranked = rank_stocks_by_beta(ind_stocks, ind_returns, top_n=params["stocks_per_industry"])
        for _, row in ranked.iterrows():
            sym = row["symbol"]
            pre_selected.add(sym)
            pre_betas[sym] = row["predicted_beta"]
            pre_scores[sym] = ind_score_map.get(ind, 0)

    print(f"    Pre-selected {len(pre_selected)} stocks across {len(mainline_industries)} industries")

    # Fast wrapper: just check pre_selected set membership
    def two_stage_wrapper(data, symbol="", **kw):
        return two_stage_fn(
            data, symbol=symbol, all_stocks=stocks,
            top_industries=params["top_industries"],
            stocks_per_industry=params["stocks_per_industry"],
            min_trend_score=params["min_trend_score"],
            rebalance_freq=params["rebalance_freq"],
            pre_selected=pre_selected,
            pre_beta=pre_betas.get(symbol),
            pre_trend_score=pre_scores.get(symbol),
        )

    print(f"  Run {run_id}: top_ind={params['top_industries']}, per_ind={params['stocks_per_industry']}, "
          f"min_score={params['min_trend_score']}, freq={params['rebalance_freq']}, "
          f"max_hold={params['max_holdings']}, sl={params['stop_loss']}, tp={params['take_profit']}")
    t0 = time.time()
    results = engine.run(stocks, two_stage_wrapper, "2020-01-01", "2025-12-31")
    elapsed = time.time() - t0

    results["elapsed_seconds"] = round(elapsed, 1)
    results["score"] = compute_score(results)
    results["params"] = params
    results["run_id"] = run_id
    return results


def main():
    print("=" * 70)
    print("Two-Stage AI Model: 20-Backtest Parameter Optimization")
    print("=" * 70)

    # Load stocks (sample of 200 for speed)
    print(f"\n[1/3] Loading data from {DATA_DIR}...")
    stocks = load_stocks(DATA_DIR)
    print(f"  Loaded {len(stocks)} stocks")

    # Sample 300 stocks for manageable runtime
    if len(stocks) > 300:
        random.seed(42)
        sampled = random.sample(list(stocks.keys()), 300)
        stocks = {k: stocks[k] for k in sampled}
        print(f"  Sampled {len(stocks)} stocks for backtest")

    # Pre-load industry map
    ind_map = load_industry_map()
    industry_counts = {}
    for sym in stocks:
        ind = get_industry(sym)
        industry_counts[ind] = industry_counts.get(ind, 0) + 1
    print(f"  Industries: {len(industry_counts)} types")
    for ind, cnt in sorted(industry_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {ind}: {cnt} stocks")

    print(f"\n[2/3] Running 20 backtests...")
    all_results = []
    best_score = -999
    best_result = None

    for i, params in enumerate(PARAM_GRID):
        print(f"\n--- Run {i+1}/20 ---")
        try:
            result = run_single_backtest(params, stocks, i + 1)
            all_results.append(result)
            print(f"  Score={result['score']:.4f} | AnnRet={result.get('annual_return',0):.1f}% | "
                  f"DD={result.get('max_drawdown',0):.1f}% | Sharpe={result.get('sharpe_ratio',0):.2f} | "
                  f"Calmar={result.get('calmar_ratio',0):.2f} | Trades={result.get('total_trades',0)} | "
                  f"WinRate={result.get('win_rate',0):.1f}%")
            if result["score"] > best_score:
                best_score = result["score"]
                best_result = result
        except Exception as e:
            print(f"  FAILED: {e}")
            all_results.append({"error": str(e), "params": params, "run_id": i + 1, "score": -999})

    # Rank by score
    all_results.sort(key=lambda x: x.get("score", -999), reverse=True)

    print(f"\n[3/3] Results saved.")

    # === Report ===
    report_lines = [
        "# Two-Stage AI Model: 20-Backtest Optimization Results",
        f"",
        f"**Date**: {date.today().isoformat()}",
        f"**Stocks tested**: {len(stocks)}",
        f"**Period**: 2020-01-01 to 2025-12-31",
        f"",
        f"## Best Configuration",
        f"",
    ]

    if best_result:
        bp = best_result["params"]
        report_lines += [
            f"| Parameter | Value |",
            f"|-----------|-------|",
            f"| top_industries | {bp['top_industries']} |",
            f"| stocks_per_industry | {bp['stocks_per_industry']} |",
            f"| min_trend_score | {bp['min_trend_score']} |",
            f"| rebalance_freq | {bp['rebalance_freq']} |",
            f"| max_holdings | {bp['max_holdings']} |",
            f"| stop_loss | {bp['stop_loss']} |",
            f"| take_profit | {bp['take_profit']} |",
            f"",
            f"### Performance Metrics",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Annual Return | {best_result.get('annual_return', 0):.2f}% |",
            f"| Max Drawdown | {best_result.get('max_drawdown', 0):.2f}% |",
            f"| Sharpe Ratio | {best_result.get('sharpe_ratio', 0):.2f} |",
            f"| Calmar Ratio | {best_result.get('calmar_ratio', 0):.2f} |",
            f"| Sortino Ratio | {best_result.get('sortino_ratio', 0):.2f} |",
            f"| Win Rate | {best_result.get('win_rate', 0):.1f}% |",
            f"| Total Trades | {best_result.get('total_trades', 0)} |",
            f"| Composite Score | {best_result.get('score', 0):.4f} |",
            f"",
        ]

    report_lines += [
        f"## All 20 Runs (Ranked by Score)",
        f"",
        f"| Rank | Run | Score | AnnRet% | DD% | Sharpe | Calmar | Trades | WinRate% | Params |",
        f"|------|-----|-------|---------|-----|--------|--------|--------|----------|--------|",
    ]

    for rank, r in enumerate(all_results, 1):
        if "error" in r:
            report_lines.append(
                f"| {rank} | {r['run_id']} | ERR | - | - | - | - | - | - | {str(r['params'])[:60]} |"
            )
        else:
            bp = r["params"]
            ps = f"ind={bp['top_industries']} sp={bp['stocks_per_industry']} sc={bp['min_trend_score']} f={bp['rebalance_freq']} h={bp['max_holdings']}"
            report_lines.append(
                f"| {rank} | {r['run_id']} | {r['score']:.4f} | {r.get('annual_return',0):.1f} | "
                f"{r.get('max_drawdown',0):.1f} | {r.get('sharpe_ratio',0):.2f} | "
                f"{r.get('calmar_ratio',0):.2f} | {r.get('total_trades',0)} | "
                f"{r.get('win_rate',0):.1f} | {ps} |"
            )

    report = "\n".join(report_lines)
    print("\n" + report)

    # Save results
    out_dir = PROJECT_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = out_dir / "two_stage_opt_results.json"
    with open(json_path, "w") as f:
        json.dump({
            "timestamp": date.today().isoformat(),
            "n_stocks": len(stocks),
            "period": "2020-01-01 to 2025-12-31",
            "best_params": best_result["params"] if best_result else None,
            "best_score": best_result["score"] if best_result else None,
            "all_runs": all_results,
        }, f, indent=2, default=str)
    print(f"\n[JSON] {json_path}")

    # Markdown
    md_path = out_dir / "two_stage_opt_results.md"
    md_path.write_text(report)
    print(f"[MD]   {md_path}")

    # Summary
    if best_result:
        print(f"\n{'='*70}")
        print(f"BEST: Run {best_result['run_id']} | Score={best_result['score']:.4f}")
        print(f"  Annual Return: {best_result.get('annual_return',0):.2f}%")
        print(f"  Max Drawdown:  {best_result.get('max_drawdown',0):.2f}%")
        print(f"  Sharpe:        {best_result.get('sharpe_ratio',0):.2f}")
        print(f"  Best Params:   top_industries={bp['top_industries']}, stocks_per_industry={bp['stocks_per_industry']}, "
              f"min_trend_score={bp['min_trend_score']}, rebalance={bp['rebalance_freq']}")
        print(f"{'='*70}")


if __name__ == "__main__":
    main()
