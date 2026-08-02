"""v5 P1 批次对抗性检查（2026-08-02）。

覆盖：
1. risk_monitor 三个假规则修复（近60日高点回撤 / 浮亏规则名 / 组合亏损占总资金）
2. run_backtest 不再静默吞错（错误率>10% 中止，低错误率告警后继续）
3. export_qmt_csv 能消费 daily_screener 的 screen_*.csv（无 date/signal 列）
4. knowledge_points / filters 改用因果 n_struct（不再有未来函数调用路径）
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from risk_monitor import check_positions, load_positions  # noqa: E402
from export_qmt_csv import load_signals, generate_qmt_orders  # noqa: E402


# ─────────────────────────── 1. risk_monitor ───────────────────────────

def _write_stock(tmp_path, symbol: str, closes, highs=None, lows=None):
    n = len(closes)
    highs = highs if highs is not None else np.array(closes) * 1.02
    lows = lows if lows is not None else np.array(closes) * 0.98
    df = pd.DataFrame({
        "date": pd.bdate_range("2026-01-02", periods=n).strftime("%Y-%m-%d"),
        "open": closes, "high": highs, "low": lows, "close": closes,
        "volume": 1e6,
    })
    df.to_csv(tmp_path / f"{symbol}.csv", index=False)


def test_recent_60d_high_rule_not_alltime(tmp_path):
    """旧假警报：全历史最高价回撤永远触发；新规则只认近60日高点。"""
    _write_stock(tmp_path, "600001",
                 closes=np.concatenate([
                     np.linspace(10, 100, 100),   # 早年大牛
                     np.full(60, 50.0),           # 近60日横盘
                 ]))
    p = tmp_path / "pos.csv"
    p.write_text("symbol,shares,cost_price\n600001,1000,50.0\n", encoding="utf-8")
    alerts = check_positions(load_positions(str(p)), str(tmp_path), total_capital=1e6)
    rules = [a["rule"] for a in alerts]
    assert "近60日高点回撤 > 15%" not in rules, "近60日横盘不应触发回撤警报"

    _write_stock(tmp_path, "600002",
                 closes=np.concatenate([np.linspace(10, 100, 100), np.linspace(100, 70, 60)]))
    p2 = tmp_path / "pos2.csv"
    p2.write_text("symbol,shares,cost_price\n600002,1000,50.0\n", encoding="utf-8")
    alerts2 = check_positions(load_positions(str(p2)), str(tmp_path), total_capital=1e6)
    assert any("近60日高点回撤 > 15%" in a["rule"] for a in alerts2)


def test_portfolio_loss_uses_total_capital(tmp_path):
    """旧死规则：分母只有持仓成本；新规则分母=总资金（含现金）。"""
    _write_stock(tmp_path, "600003", np.full(80, 8.0))   # 成本10 → 浮亏20%
    _write_stock(tmp_path, "600004", np.full(80, 8.0))
    p = tmp_path / "pos.csv"
    p.write_text("symbol,shares,cost_price\n"
                 "600003,5000,10.0\n600004,5000,10.0\n", encoding="utf-8")
    # 成本10万、市值8万 → 亏2万 = 总资金(100万)的2% → 不应触发 CRITICAL
    alerts = check_positions(load_positions(str(p)), str(tmp_path), total_capital=1e6)
    assert not any(a["rule"] == "组合浮亏 > 10%（占总资金）" for a in alerts)
    # 同样持仓但总资金只报 15 万 → 亏2万 = 13.3% → 触发
    alerts2 = check_positions(load_positions(str(p)), str(tmp_path), total_capital=150_000)
    assert any(a["rule"] == "组合浮亏 > 10%（占总资金）" for a in alerts2)


def test_float_loss_rule_name(tmp_path):
    _write_stock(tmp_path, "600005", np.full(80, 9.0))
    p = tmp_path / "pos.csv"
    p.write_text("symbol,shares,cost_price\n600005,1000,10.0\n", encoding="utf-8")
    alerts = check_positions(load_positions(str(p)), str(tmp_path), total_capital=1e6)
    assert any(a["rule"] == "个股浮亏 > 5%" for a in alerts)
    assert not any("单日亏损" in a["rule"] for a in alerts), "旧规则名与实现不符"


# ─────────────────────────── 2. run_backtest 静默吞错 ───────────────────────────

def _mk_bt_stocks(n=15, n_days=80):
    idx = pd.bdate_range("2026-01-02", periods=n_days)
    out = {}
    for i in range(n):
        close = 10 + np.sin(np.arange(n_days) / 5 + i) * 0.5
        out[f"s{i:02d}"] = pd.DataFrame({
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": np.full(n_days, 1e6),
        }, index=idx)
    return out


def test_run_backtest_raises_on_high_error_rate():
    """错误率>10% 必须中止，而不是静默输出'零信号回测成功'。"""
    from run_backtest import BacktestEngine
    stocks = _mk_bt_stocks(15)
    bad = {"s00", "s01", "s02"}   # 3/15 = 20% > 10%

    def boom(data, symbol="", **kw):
        if symbol in bad:
            raise ValueError("simulated systemic failure")
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])

    engine = BacktestEngine()
    with pytest.raises(RuntimeError, match="错误率过高"):
        engine.run(stocks, boom, "2026-01-01", "2026-12-31")


def test_run_backtest_warns_but_continues_on_low_error_rate(capsys):
    from run_backtest import BacktestEngine
    stocks = _mk_bt_stocks(15)

    def mostly_ok(data, symbol="", **kw):
        if symbol == "s00":     # 1/15 = 6.7% < 10%
            raise ValueError("one-off")
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])

    engine = BacktestEngine()
    res = engine.run(stocks, mostly_ok, "2026-01-01", "2026-12-31")
    assert "error" not in res
    err = capsys.readouterr().err
    assert "信号预计算失败 1/15" in err


# ─────────────────────────── 3. export_qmt_csv ───────────────────────────

def test_export_qmt_consumes_screen_csv(tmp_path):
    """screen_*.csv（无 date/signal 列）→ 正常生成 QMT 买单。"""
    screen = tmp_path / "screen_2026-07-16.csv"
    screen.write_text(
        "rank,symbol,name,score,close\n"
        "1,600519,贵州茅台,90.0,1500.0\n"
        "2,000001,平安银行,88.0,12.0\n"
        "3,300750,宁德时代,86.0,180.0\n"
        "4,002475,立讯精密,84.0,30.0\n"
        "5,601888,中国中免,82.0,70.0\n"
        "6,600036,招商银行,80.0,35.0\n",
        encoding="utf-8")
    df = load_signals(str(screen))
    assert "date" in df.columns and (df["date"] == "2026-07-16").all()
    assert (df["signal"] == 1).all()
    orders = generate_qmt_orders(df, total_capital=1e6)
    assert len(orders) == 5                      # min(6, MAX_HOLDINGS=5)
    assert (orders["direction"] == 1).all()
    assert (orders["quantity"] > 0).all()
    assert orders["code"].iloc[0] == "600519.SH"
    assert orders["code"].iloc[1] == "000001.SZ"
    assert orders["code"].iloc[2] == "300750.SZ"


def test_export_qmt_legacy_signals_with_sell():
    df = pd.DataFrame({
        "date": ["2026-07-16"] * 3,
        "symbol": ["600519", "000001", "600036"],
        "signal": [1, -1, 1],
        "factor_snapshot": ['{"close": 1500.0}', "", ""],
        "close": [1500.0, 12.0, 35.0],
    })
    orders = generate_qmt_orders(df, total_capital=1e6)
    sells = orders[orders["direction"] == 2]
    assert len(sells) == 1 and sells["code"].iloc[0] == "000001.SZ"
    assert len(orders[orders["direction"] == 1]) == 2


# ─────────────────────────── 4. 因果化路径冒烟 ───────────────────────────

def test_key_support_causal_smoke():
    from alphapulse.factors.knowledge_points import compute_key_support
    try:
        from test_n_struct_causal import _make_n_shape
    except ModuleNotFoundError:
        from tests.test_n_struct_causal import _make_n_shape
    data = _make_n_shape()
    out = compute_key_support(data)
    assert set(out.columns) == {"n_pattern_support", "range_support", "sb1_support"}
    # 因果版：结构确认后才出现支撑价，且不抛异常
    assert out["n_pattern_support"].notna().any()


def test_has_n_structure_causal_smoke():
    from alphapulse.utils.filters import has_n_structure
    try:
        from test_n_struct_causal import _make_n_shape
    except ModuleNotFoundError:
        from tests.test_n_struct_causal import _make_n_shape
    data = _make_n_shape()
    assert isinstance(has_n_structure(data, lookback=20), bool)
