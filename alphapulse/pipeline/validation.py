"""Layer 2 验证框架。

实现三项核心验证：
1. Walk-forward Analysis: 滚动训练/测试，计算退化率 (OOS/IS Sharpe)
2. Combinatorial Purged CV: 生成 45+ 条不同的训练/测试路径，报告分布
3. Deflated Sharpe Ratio: López de Prado 多重测试校正

参考:
- López de Prado "Advances in Financial Machine Learning" Ch.7 (Cross-Validation)
- López de Prado & Bailey "The Deflated Sharpe Ratio" SSRN 3167017
- 退化率: OOS Sharpe / IS Sharpe (0.6-0.8 健康, <0.3 过拟合)
"""

from typing import Callable, Optional

import numpy as np
import pandas as pd
from scipy import stats


# ==============================================================================
# 1. Walk-Forward Analysis
# ==============================================================================
def walk_forward_analysis(
    stocks: dict[str, pd.DataFrame],
    strategy_fn: Callable,
    start_date: str,
    end_date: str,
    train_window_years: int = 3,
    test_window_years: int = 1,
    step_years: int = 1,
    initial_capital: float = 1_000_000,
    **strategy_params,
) -> dict:
    """滚动时间序列训练/测试（Walk-Forward Analysis）。

    严格按时间顺序分割，不使用随机 k-fold。
    这是评估策略在真实 OOS 环境下表现的关键方法。

    Args:
        stocks: symbol -> DataFrame (OHLCV, DatetimeIndex)
        strategy_fn: 策略信号生成函数
        start_date: 全局起始日期
        end_date: 全局结束日期
        train_window_years: 训练窗口长度（年）
        test_window_years: 测试窗口长度（年）
        step_years: 滚动步长（年）
        initial_capital: 每段测试期初资金
        **strategy_params: 传给 strategy_fn 的额外参数

    Returns:
        dict: {
            "windows": [(train_start, train_end, test_start, test_end), ...],
            "is_sharpes": [...],
            "oos_sharpes": [...],
            "degradation_ratio": OOS_mean / IS_mean,
            "avg_oos_sharpe": ..., "avg_is_sharpe": ...,
            "oos_sharpe_std": ..., "min_oos_sharpe": ...,
            "interpretation": str,
        }
    """
    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)
    train_delta = pd.DateOffset(years=train_window_years)
    test_delta = pd.DateOffset(years=test_window_years)
    step_delta = pd.DateOffset(years=step_years)

    windows = []
    train_start = start_dt
    while train_start + train_delta + test_delta <= end_dt:
        train_end = train_start + train_delta - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = min(test_start + test_delta - pd.Timedelta(days=1), end_dt)
        if test_start >= end_dt:
            break
        windows.append((
            str(train_start.date()), str(train_end.date()),
            str(test_start.date()), str(test_end.date()),
        ))
        train_start += step_delta

    if len(windows) < 2:
        return {
            "error": f"窗口不足: 仅生成 {len(windows)} 个窗口",
            "windows": windows,
        }

    is_sharpes = []
    oos_sharpes = []

    for train_s, train_e, test_s, test_e in windows:
        # IS 回测（训练集）
        is_result = _run_backtest_segment(
            stocks, strategy_fn, train_s, train_e, initial_capital, **strategy_params
        )
        # OOS 回测（测试集）
        oos_result = _run_backtest_segment(
            stocks, strategy_fn, test_s, test_e, initial_capital, **strategy_params
        )

        is_sharpes.append(is_result.get("sharpe_ratio", 0))
        oos_sharpes.append(oos_result.get("sharpe_ratio", 0))

    is_valid = [s for s in is_sharpes if not np.isnan(s) and not np.isinf(s)]
    oos_valid = [s for s in oos_sharpes if not np.isnan(s) and not np.isinf(s)]

    avg_is = float(np.mean(is_valid)) if is_valid else 0.0
    avg_oos = float(np.mean(oos_valid)) if oos_valid else 0.0
    oos_std = float(np.std(oos_valid)) if len(oos_valid) > 1 else 0.0
    min_oos = float(np.min(oos_valid)) if oos_valid else 0.0

    degradation_ratio = avg_oos / avg_is if abs(avg_is) > 1e-8 else 0.0

    # 解释退化率
    if degradation_ratio >= 0.8:
        interpretation = "优异: 退化率 >= 0.8，OOS 性能接近 IS"
    elif degradation_ratio >= 0.6:
        interpretation = "健康: 退化率 0.6-0.8，策略泛化良好"
    elif degradation_ratio >= 0.3:
        interpretation = "警告: 退化率 0.3-0.6，可能存在过拟合"
    else:
        interpretation = "严重: 退化率 < 0.3，策略严重过拟合"

    return {
        "n_windows": len(windows),
        "windows": windows,
        "is_sharpes": is_sharpes,
        "oos_sharpes": oos_sharpes,
        "avg_is_sharpe": round(avg_is, 4),
        "avg_oos_sharpe": round(avg_oos, 4),
        "oos_sharpe_std": round(oos_std, 4),
        "min_oos_sharpe": round(min_oos, 4),
        "degradation_ratio": round(degradation_ratio, 4),
        "interpretation": interpretation,
    }


def _run_backtest_segment(
    stocks, strategy_fn, start, end, capital, **params
) -> dict:
    """运行单段回测并返回指标。轻量版，不依赖完整 BacktestEngine。"""
    from alphapulse.config.settings import SLIPPAGE_BUY, SLIPPAGE_SELL
    from alphapulse.utils.backtest_utils import apply_slippage, calc_commission

    # 收集所有交易日
    all_dates = set()
    for df in stocks.values():
        all_dates.update(df.index)
    all_dates = sorted(
        d for d in all_dates
        if start <= str(d)[:10] <= end
    )
    if len(all_dates) < 30:
        return {"sharpe_ratio": 0.0}

    # 预计算信号
    all_signals = {}
    for symbol, data in stocks.items():
        try:
            sigs = strategy_fn(data, symbol=symbol, **params)
            if len(sigs) > 0:
                buy_dates = set(sigs[sigs["signal"] == 1].index)
                if buy_dates:
                    all_signals[symbol] = buy_dates
        except Exception:
            pass

    # 简化组合模拟
    cash = capital
    holdings = {}
    nav = [{"nav": capital}]

    for trade_date in all_dates:
        hv = 0.0
        for sym, h in holdings.items():
            if sym in stocks and trade_date in stocks[sym].index:
                hv += h["shares"] * stocks[sym].loc[trade_date, "close"]
            else:
                hv += h["shares"] * h["cost"]

        # 检查退出
        for sym in list(holdings.keys()):
            if sym in stocks and trade_date in stocks[sym].index:
                current_price = stocks[sym].loc[trade_date, "close"]
                pnl_pct = (current_price - holdings[sym]["cost"]) / holdings[sym]["cost"]
                if pnl_pct < -0.10 or pnl_pct > 0.30:
                    price = stocks[sym].loc[trade_date, "close"]
                    sell_price = apply_slippage(price, -1)
                    revenue = sell_price * holdings[sym]["shares"] - calc_commission(
                        sell_price * holdings[sym]["shares"]
                    )
                    cash += revenue
                    del holdings[sym]

        # 检查买入
        for sym in sorted(all_signals.keys()):
            if len(holdings) >= 5:
                break
            if sym in holdings:
                continue
            if trade_date not in all_signals.get(sym, set()):
                continue
            if sym not in stocks or trade_date not in stocks[sym].index:
                continue
            price = stocks[sym].loc[trade_date, "close"]
            buy_price = apply_slippage(price, 1)
            max_cost = (cash + hv) * 0.20
            shares = int(max_cost / buy_price / 100) * 100
            if shares < 100:
                continue
            cost = buy_price * shares + calc_commission(buy_price * shares)
            if cost > cash:
                shares = int((cash - 5) / buy_price / 100) * 100
                if shares < 100:
                    continue
                cost = buy_price * shares + calc_commission(buy_price * shares)
            cash -= cost
            holdings[sym] = {"shares": shares, "cost": buy_price}

        hvt = 0.0
        for sym, h in holdings.items():
            if sym in stocks and trade_date in stocks[sym].index:
                hvt += h["shares"] * stocks[sym].loc[trade_date, "close"]
            else:
                hvt += h["shares"] * h["cost"]
        nav.append({"nav": cash + hvt})

    nav_df = pd.DataFrame(nav)
    nav_df["daily_return"] = nav_df["nav"].pct_change()

    if len(nav_df) < 30:
        return {"sharpe_ratio": 0.0}

    excess = nav_df["daily_return"].dropna() - 0.03 / 252
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0.0

    return {"sharpe_ratio": float(sharpe)}


# ==============================================================================
# 2. Combinatorial Purged Cross-Validation
# ==============================================================================
def combinatorial_purged_cv(
    n_samples: int,
    n_splits: int = 10,
    purge_pct: float = 0.01,
    embargo_pct: float = 0.0,
) -> dict:
    """生成组合清洗交叉验证 (Combinatorial Purged CV) 路径。

    参考 López de Prado "Advances in Financial Machine Learning" 第 7 章。

    生成 45+ 条不同的训练/测试路径，每条路径:
    - 严格保持时间顺序（训练数据在测试数据之前）
    - 清洗 (purge) 训练/测试边界附近的观测值，防止信息泄漏
    - 隔离 (embargo) 测试集之后的数据

    Args:
        n_samples: 总样本数（交易日数）
        n_splits: 分组数（默认 10，生成 C(10,2)=45 条组合）
        purge_pct: 清洗比例（训练/测试边界两侧删除的观测比例）
        embargo_pct: 隔离比例（测试集之后禁止使用的观测比例）

    Returns:
        dict: {
            "paths": [[train_indices, test_indices], ...],
            "n_paths": int,
            "n_splits_avg": int,  # 平均每组样本数
        }
    """
    if n_splits > n_samples:
        n_splits = max(2, n_samples // 20)

    # 生成 C(n_splits, 2) 条路径（遍历所有可能的 (train_end_group, test_group) 组合）
    # 每条路径: train = groups[:i] (purged), test = group_j (isolated)
    paths = []
    split_size = n_samples // n_splits

    for test_group in range(1, n_splits):  # 测试组不能是第一个
        for train_end_group in range(test_group):  # 训练组必须在测试组之前
            # 训练索引: 从 0 到 (train_end_group+1)*split_size - purge
            # 测试索引: 从 test_group*split_size 到 (test_group+1)*split_size
            purge_n = int(split_size * purge_pct)
            embargo_n = int(split_size * embargo_pct)

            train_end = (train_end_group + 1) * split_size - purge_n
            test_start = test_group * split_size + embargo_n
            test_end = min((test_group + 1) * split_size, n_samples)

            if train_end <= 0 or test_start >= n_samples or train_end >= test_start:
                continue

            train_idx = list(range(0, max(1, train_end)))
            test_idx = list(range(test_start, test_end))

            if len(train_idx) > 10 and len(test_idx) > 5:
                paths.append((train_idx, test_idx))

    # 如果组合不够，补充生成更多路径
    while len(paths) < 45 and n_splits < n_samples // 10:
        n_splits += 2
        split_size = n_samples // n_splits
        for test_group in range(1, n_splits):
            for train_end_group in range(test_group):
                train_end = (train_end_group + 1) * split_size - int(split_size * purge_pct)
                test_start = test_group * split_size + int(split_size * embargo_pct)
                test_end = min((test_group + 1) * split_size, n_samples)
                if train_end <= 0 or test_start >= n_samples or train_end >= test_start:
                    continue
                train_idx = list(range(0, max(1, train_end)))
                test_idx = list(range(test_start, test_end))
                if len(train_idx) > 10 and len(test_idx) > 5:
                    paths.append((train_idx, test_idx))
            if len(paths) >= 45:
                break
        if len(paths) >= 45:
            break

    return {
        "n_paths": len(paths),
        "paths": paths,
        "avg_train_size": float(np.mean([len(p[0]) for p in paths])) if paths else 0,
        "avg_test_size": float(np.mean([len(p[1]) for p in paths])) if paths else 0,
    }


def compute_cv_sharpe_distribution(
    stocks: dict[str, pd.DataFrame],
    strategy_fn: Callable,
    cv_paths: list,
    verbose: bool = False,
    **strategy_params,
) -> dict:
    """计算给定 CV 路径上的夏普比率分布。

    Args:
        stocks: 股票数据
        strategy_fn: 策略函数
        cv_paths: [(train_idx, test_idx), ...] 来自 combinatorial_purged_cv
        verbose: 是否打印进度

    Returns:
        dict: {
            "oos_sharpes": [...],
            "mean": ..., "median": ..., "std": ...,
            "p5": ..., "p95": ..., "p25": ..., "p75": ...,
        }
    """
    # 构建全局日期索引
    all_dates = sorted(set().union(*(
        set(df.index) for df in stocks.values()
    )))

    oos_sharpes = []
    for i, (train_idx, test_idx) in enumerate(cv_paths):
        if len(train_idx) >= len(all_dates) or len(test_idx) >= len(all_dates):
            continue
        train_dates = [all_dates[j] for j in train_idx if j < len(all_dates)]
        test_dates = [all_dates[j] for j in test_idx if j < len(all_dates)]
        if not train_dates or not test_dates:
            continue

        train_start = str(min(train_dates).date()) if hasattr(train_dates[0], 'date') else str(train_dates[0])[:10]
        train_end = str(max(train_dates).date()) if hasattr(train_dates[0], 'date') else str(train_dates[-1])[:10]
        test_start = str(min(test_dates).date()) if hasattr(test_dates[0], 'date') else str(test_dates[0])[:10]
        test_end = str(max(test_dates).date()) if hasattr(test_dates[0], 'date') else str(test_dates[-1])[:10]

        oos_result = _run_backtest_segment(
            stocks, strategy_fn, test_start, test_end, 1_000_000, **strategy_params
        )
        oos_sharpes.append(oos_result.get("sharpe_ratio", 0))

        if verbose and (i + 1) % 10 == 0:
            print(f"  CV path {i+1}/{len(cv_paths)}")

    valid = [s for s in oos_sharpes if not np.isnan(s) and not np.isinf(s)]

    return {
        "n_tested": len(oos_sharpes),
        "oos_sharpes": oos_sharpes,
        "mean": round(float(np.mean(valid)), 4) if valid else 0.0,
        "median": round(float(np.median(valid)), 4) if valid else 0.0,
        "std": round(float(np.std(valid)), 4) if valid else 0.0,
        "p5": round(float(np.percentile(valid, 5)), 4) if valid else 0.0,
        "p25": round(float(np.percentile(valid, 25)), 4) if valid else 0.0,
        "p75": round(float(np.percentile(valid, 75)), 4) if valid else 0.0,
        "p95": round(float(np.percentile(valid, 95)), 4) if valid else 0.0,
        "min": round(float(np.min(valid)), 4) if valid else 0.0,
        "max": round(float(np.max(valid)), 4) if valid else 0.0,
    }


# ==============================================================================
# 3. Deflated Sharpe Ratio (DSR)
# ==============================================================================
def deflated_sharpe_ratio(
    daily_returns: pd.Series,
    n_trials: int = 100,
    significance_level: float = 0.95,
) -> dict:
    """计算 Deflated Sharpe Ratio (López de Prado 方法)。

    这是独立的 DSR 计算函数，供 validation 模块直接调用，
    也供 DSRGate 内部使用。

    Args:
        daily_returns: 日收益率序列
        n_trials: 多重测试次数（搜索的策略变体数）
        significance_level: 显著性水平阈值

    Returns:
        dict: {
            "sharpe_ratio": ..., "expected_max_sr": ...,
            "deflated_sr": ..., "dsr_pvalue": ...,
            "dsr_zscore": ..., "passed": bool,
            "n_observations": ..., "n_trials": ...,
        }
    """
    from alphapulse.pipeline.gates import DSRGate

    gate = DSRGate(n_trials=n_trials, significance_level=significance_level)
    result = gate.evaluate(daily_returns=daily_returns, n_trials=n_trials)

    return {
        "sharpe_ratio": result.evidence.get("sharpe_ratio", 0),
        "expected_max_sr": result.evidence.get("expected_max_sr", 0),
        "deflated_sr": result.evidence.get("deflated_sr", 0),
        "dsr_pvalue": result.score,
        "passed": result.passed,
        "n_observations": result.evidence.get("n_observations", 0),
        "n_trials": n_trials,
        "significance_level": significance_level,
    }


# ==============================================================================
# 4. 退化率便捷函数
# ==============================================================================
def compute_degradation_ratio(
    is_sharpe: float,
    oos_sharpe: float,
) -> dict:
    """计算退化率并给出解释。

    Args:
        is_sharpe: 样本内夏普比率
        oos_sharpe: 样本外夏普比率

    Returns:
        dict: {ratio, interpretation, is_healthy}
    """
    ratio = oos_sharpe / is_sharpe if abs(is_sharpe) > 1e-8 else 0.0

    if ratio >= 0.8:
        interpretation = "优异: OOS/IS >= 0.8"
        healthy = True
    elif ratio >= 0.6:
        interpretation = "健康: OOS/IS 0.6-0.8"
        healthy = True
    elif ratio >= 0.3:
        interpretation = "警告: OOS/IS 0.3-0.6, 可能过拟合"
        healthy = False
    else:
        interpretation = "严重: OOS/IS < 0.3, 严重过拟合"
        healthy = False

    return {
        "degradation_ratio": round(ratio, 4),
        "is_sharpe": round(is_sharpe, 4),
        "oos_sharpe": round(oos_sharpe, 4),
        "interpretation": interpretation,
        "is_healthy": healthy,
    }
