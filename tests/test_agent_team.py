"""agent team P0 单测：角色输出 / 聚合单调性 / 评级阈值 / 集成冒烟。

规格：docs/superpowers/specs/2026-06-21-agent-team-design.md
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.agent_team.contract import (
    StockOpinion, TeamVerdict, score_to_rating,
    SIGNAL_BULL, SIGNAL_BEAR, SIGNAL_NEUTRAL)
from alphapulse.agent_team.agents import (
    data_agent, factor_agent, pattern_agent, sector_agent)
from alphapulse.agent_team.portfolio import portfolio_agent
from alphapulse.agent_team.context import TeamContext
from alphapulse.agent_team import core


def _ohlcv(n=250, seed=7, start=20.0, drift=0.2):
    np.random.seed(seed)
    c = pd.Series(start + np.random.randn(n).cumsum() * drift).clip(lower=1.0)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n).astype(str),
        "open": c * 0.995, "high": c * 1.02, "low": c * 0.98, "close": c,
        "volume": np.random.randint(100000, 1000000, n).astype(float),
        "market_cap": c * 5e8,
    })


# ── contract ──
def test_signed_directions():
    assert StockOpinion("a", SIGNAL_BULL, 80).signed() == 80
    assert StockOpinion("a", SIGNAL_BEAR, 80).signed() == -80
    assert StockOpinion("a", SIGNAL_NEUTRAL, 80).signed() == 0


def test_score_to_rating_boundaries():
    assert score_to_rating(75) == "Buy"
    assert score_to_rating(74.9) == "增持"
    assert score_to_rating(60) == "增持"
    assert score_to_rating(45) == "持有"
    assert score_to_rating(30) == "减持"
    assert score_to_rating(29.9) == "Sell"
    assert score_to_rating(0) == "Sell"


# ── data_agent ──
def test_data_agent_healthy():
    op = data_agent(_ohlcv(200))
    assert op.signal == SIGNAL_NEUTRAL and op.confidence == 100.0


def test_data_agent_insufficient():
    op = data_agent(_ohlcv(50))
    assert op.signal == SIGNAL_BEAR and op.confidence == 0.0


def test_data_agent_none():
    assert data_agent(None).signal == SIGNAL_BEAR


def test_data_agent_nan_corrupt():
    df = _ohlcv(200)
    df.loc[df.index[-3:], "close"] = np.nan
    assert data_agent(df).signal == SIGNAL_BEAR


# ── factor_agent ──
def test_factor_agent_structure():
    op = factor_agent(_ohlcv(250))
    assert op.agent == "factor"
    assert op.signal in (SIGNAL_BULL, SIGNAL_BEAR, SIGNAL_NEUTRAL)
    assert 0.0 <= op.confidence <= 100.0
    assert "factor_score" in op.evidence and "sub_top" in op.evidence


def test_factor_agent_insufficient_history_neutral():
    op = factor_agent(_ohlcv(60))     # compute_sub_scores 返回空
    assert op.signal == SIGNAL_NEUTRAL and op.confidence == 0.0


# ── pattern_agent ──
def test_pattern_agent_structure():
    op = pattern_agent(_ohlcv(250))
    assert op.agent == "pattern"
    assert op.evidence["state"] in ("B1买点(新)", "B1候B2", "单针探底", "无明确战法态")
    assert 0.0 <= op.confidence <= 100.0


# ── sector_agent ──
def _ctx(sector="半导体", score=72.0, macro="偏多", concepts="AI算力/CPO"):
    return TeamContext(macro_level=macro, macro_score=55.0,
                       sector_scores={sector: score} if score is not None else {},
                       sector_map={"600000": sector}, concept_map={"600000": concepts})


def test_sector_agent_strong_bull():
    op = sector_agent("600000", _ctx(score=72.0, macro="偏多"))
    assert op.signal == SIGNAL_BULL and op.confidence == 72.0
    assert op.evidence["concepts"] == "AI算力/CPO"


def test_sector_agent_weak_bear():
    op = sector_agent("600000", _ctx(score=30.0, macro="偏多"))
    assert op.signal == SIGNAL_BEAR


def test_sector_agent_macro_bear_overrides():
    op = sector_agent("600000", _ctx(score=72.0, macro="偏空"))
    assert op.signal != SIGNAL_BULL   # 大盘空头不给多头


def test_sector_agent_unknown_symbol_falls_back():
    op = sector_agent("999999", _ctx())
    assert op.evidence["sector"] == "" and op.confidence == 55.0  # 回退大盘分


# ── portfolio 聚合 ──
def _op(agent, signal, conf):
    return StockOpinion(agent, signal, conf)


def test_portfolio_all_bull_high_score():
    ops = [_op("factor", SIGNAL_BULL, 90), _op("pattern", SIGNAL_BULL, 90),
           _op("sector", SIGNAL_BULL, 90)]
    p = portfolio_agent(ops)
    assert p.confidence >= 90 and p.evidence["rating"] == "Buy"


def test_portfolio_all_bear_low_score():
    ops = [_op("factor", SIGNAL_BEAR, 90), _op("pattern", SIGNAL_BEAR, 90),
           _op("sector", SIGNAL_BEAR, 90)]
    p = portfolio_agent(ops)
    assert p.confidence <= 10 and p.evidence["rating"] == "Sell"


def test_portfolio_neutral_mid():
    ops = [_op("factor", SIGNAL_NEUTRAL, 50), _op("pattern", SIGNAL_NEUTRAL, 50),
           _op("sector", SIGNAL_NEUTRAL, 50)]
    p = portfolio_agent(ops)
    assert p.confidence == 50.0 and p.evidence["rating"] == "持有"


def test_portfolio_monotonic_in_confidence():
    """factor 看多置信度升高（方向不变）→ 团队分不降。"""
    base = [_op("pattern", SIGNAL_NEUTRAL, 50), _op("sector", SIGNAL_NEUTRAL, 50)]
    lo = portfolio_agent([_op("factor", SIGNAL_BULL, 40)] + base).confidence
    hi = portfolio_agent([_op("factor", SIGNAL_BULL, 95)] + base).confidence
    assert hi >= lo


# ── core 编排 ──
def test_analyze_stock_healthy():
    v = core.analyze_stock(_ohlcv(250), "600000", "测试股", _ctx())
    assert isinstance(v, TeamVerdict) and v.ok
    assert v.rating in ("Buy", "增持", "持有", "减持", "Sell")
    assert len(v.opinions) == 5 and 0.0 <= v.score <= 100.0
    assert v.to_row()["symbol"] == "600000"


def test_analyze_stock_unhealthy_watch():
    v = core.analyze_stock(_ohlcv(50), "600000", "测试股", _ctx())
    assert not v.ok and v.rating == "观望"


def test_analyze_batch_robust():
    items = [("600000", "A", _ohlcv(250)), ("000001", "B", _ohlcv(40))]
    out = core.analyze_batch(items, _ctx())
    assert len(out) == 2 and out[0].ok and not out[1].ok


# ── 集成冒烟：本地真实日线（外接盘未挂载时跳过）──
@pytest.mark.parametrize("sym", ["000001", "600519"])
def test_integration_local_real_stock(sym):
    from alphapulse.config.settings import DATA_DIR
    local = Path(__file__).resolve().parent.parent / "data" / "day" / f"{sym}.csv"
    src = local if local.exists() else Path(DATA_DIR) / f"{sym}.csv"
    if not src.exists():
        pytest.skip(f"无本地日线 {sym}")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from replay_screen import load_stock
    df = load_stock(src, "9999-12-31", min_rows=120)
    if df is None:
        pytest.skip(f"{sym} 历史不足")
    v = core.analyze_stock(df, sym, "", _ctx())
    assert isinstance(v, TeamVerdict) and v.ok
    assert v.rating in ("Buy", "增持", "持有", "减持", "Sell")
    assert len(v.opinions) == 5
