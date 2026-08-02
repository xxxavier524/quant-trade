"""组合级绩效折算单测（P2/C7）——证明它与"逐信号等权"指标的差异。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.backtest.portfolio_eval import evaluate_portfolio  # noqa: E402


def _t(entry, exit_, r):
    return {"entry_date": entry, "exit_date": exit_, "net_return": r}


def test_empty_trades():
    r = evaluate_portfolio([])
    assert r["annual_return"] == 0.0 and r["n_taken"] == 0


def test_single_winning_trade_scales_by_position_size():
    """单票上限20%：+50%的交易只贡献约 20%×50% = 10% 的组合收益。"""
    r = evaluate_portfolio([_t("2024-01-01", "2024-12-31", 0.50)])
    assert r["n_taken"] == 1
    assert 0.09 < r["final_equity"] / 1_000_000 - 1 < 0.11


def test_concurrency_cap_skips_extra_signals():
    """同日6个信号、上限5并发 → 第6个被跳过（真实账户吃不下所有信号）。"""
    trades = [_t("2024-01-02", "2024-06-01", 0.10) for _ in range(6)]
    r = evaluate_portfolio(trades)
    assert r["n_taken"] == 5 and r["n_skipped"] == 1


def test_capital_recycles_after_exit():
    """先平后开：前一笔了结释放资金，后一笔仍能开仓。"""
    trades = [_t("2024-01-02", "2024-02-01", 0.10),
              _t("2024-03-01", "2024-04-01", 0.10)]
    r = evaluate_portfolio(trades)
    assert r["n_taken"] == 2 and r["final_equity"] > 1_000_000


def test_losses_reduce_equity_and_show_drawdown():
    trades = [_t("2024-01-02", "2024-03-01", -0.20),
              _t("2024-03-05", "2024-05-01", -0.20)]
    r = evaluate_portfolio(trades)
    assert r["final_equity"] < 1_000_000
    assert r["max_drawdown"] < 0
    assert r["annual_return"] < 0


def test_per_signal_average_can_be_positive_while_portfolio_is_flat():
    """核心论点：逐信号均值为正，不代表账户赚钱——信号过密时多数吃不进去。

    30 个同日信号里只有 5 个能进场；若能进场的恰好是亏的，账户就是亏的，
    而"逐信号等权均值"仍为正。这正是旧目标函数与 -12.4% 组合回测脱节的原因。
    """
    trades = [_t("2024-01-02", "2024-02-01", -0.10) for _ in range(5)]
    trades += [_t("2024-01-02", "2024-02-01", 0.30) for _ in range(25)]
    per_signal_mean = sum(t["net_return"] for t in trades) / len(trades)
    r = evaluate_portfolio(trades)
    assert per_signal_mean > 0                 # 逐信号看很美
    assert r["n_skipped"] == 25                # 但绝大多数根本进不去
    assert r["final_equity"] < 1_000_000       # 账户实际是亏的


def test_annualization_uses_calendar_span():
    r = evaluate_portfolio([_t("2024-01-01", "2025-01-01", 0.50)])
    assert 0.9 < r["years"] < 1.1
    assert 0.09 < r["annual_return"] < 0.11    # 约一年 → 年化≈总收益


def test_malformed_trades_are_skipped():
    bad = [{"entry_date": None, "exit_date": "2024-01-01", "net_return": 0.1},
           {"entry_date": "2024-02-01", "exit_date": "2024-01-01", "net_return": 0.1},
           {"entry_date": "2024-01-01"}]
    assert evaluate_portfolio(bad)["n_taken"] == 0


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
