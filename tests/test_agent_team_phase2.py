"""agent team 阶段二单测：辩论解析 / 贝叶斯融合 / 风控规则 / 批量接线（mock LLM）。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.agent_team.contract import StockOpinion, TeamVerdict
from alphapulse.agent_team.debate import parse_referee, run_debate, DebateOutcome
from alphapulse.agent_team.fusion import bayes_fuse, fuse_team_score
from alphapulse.agent_team.risk import apply_risk
from alphapulse.agent_team.context import TeamContext
from alphapulse.agent_team import core


# ── fusion ──
def test_bayes_agree_reinforces():
    assert bayes_fuse(0.7, 0.8, True) > 0.8          # 一致→强于两者

def test_bayes_disagree_weakens():
    assert bayes_fuse(0.7, 0.8, False) < 0.7         # 分歧→弱于量化侧

def test_bayes_neutral_identity():
    assert abs(bayes_fuse(0.7, 0.5, True) - 0.7) < 1e-9
    assert abs(bayes_fuse(0.7, 0.5, False) - 0.7) < 1e-9

def test_bayes_clamps_extremes():
    assert 0.0 < bayes_fuse(1.0, 0.0, True) < 1.0    # 不允许0/1退化

def test_fuse_team_score_directions():
    assert fuse_team_score(70, "bullish", 80) > 70   # 量化多+LLM多→更高
    assert fuse_team_score(70, "bearish", 80) < 70   # LLM唱反调→降
    assert fuse_team_score(70, "neutral", 80) == 70  # 中立→不变
    # 量化偏空 + LLM 看空 → 更空
    assert fuse_team_score(35, "bearish", 80) < 35

def test_fuse_monotonic_in_llm_conf():
    lo = fuse_team_score(70, "bullish", 55)
    hi = fuse_team_score(70, "bullish", 95)
    assert hi >= lo


# ── debate 解析 ──
def test_parse_referee_clean():
    r = parse_referee('{"signal": "bullish", "confidence": 72, "reasoning": "多方证据更实"}')
    assert r == {"signal": "bullish", "confidence": 72.0, "reasoning": "多方证据更实"}

def test_parse_referee_with_fence_and_prefix():
    txt = '好的，我的裁决：\n```json\n{"signal": "BEARISH", "confidence": "61", "reasoning": "板块太弱"}\n```'
    r = parse_referee(txt)
    assert r["signal"] == "bearish" and r["confidence"] == 61.0

def test_parse_referee_invalid():
    assert parse_referee("我认为看多，置信度80") is None
    assert parse_referee('{"signal": "long", "confidence": 80}') is None
    assert parse_referee('{"signal": "bullish", "confidence": 180}') is None
    assert parse_referee("") is None


def _verdict(score=70.0, rating=None, mv=None, ok=True):
    from alphapulse.agent_team.contract import score_to_rating
    v = TeamVerdict("600000", "测试", score, rating or score_to_rating(score),
                    [StockOpinion("portfolio", "bullish", score)], "r", ok=ok)
    if mv is not None:
        v.meta["float_mv_yi"] = mv
    return v


# ── run_debate（mock chat）──
def test_run_debate_mock_flow():
    calls = []
    def fake_chat(prompt):
        calls.append(prompt)
        if "做多研究员。基于以上证据" in prompt:
            return "看多：J超卖+板块强"
        if "唱反调" in prompt:
            return "看空：GBDT胜率低"
        return '{"signal": "bullish", "confidence": 66, "reasoning": "多方略胜"}'
    out = run_debate(_verdict(), chat_fn=fake_chat)
    assert isinstance(out, DebateOutcome)
    assert out.signal == "bullish" and out.confidence == 66.0
    assert len(calls) == 3                            # Bull→Bear→Referee 三轮
    assert "看多" in calls[1]                          # Bear 能看到 Bull 观点

def test_run_debate_bad_json_returns_none():
    assert run_debate(_verdict(), chat_fn=lambda p: "无法判断") is None

def test_run_debate_exception_returns_none():
    def boom(p):
        raise ConnectionError("timeout")
    assert run_debate(_verdict(), chat_fn=boom) is None


# ── risk ──
def test_risk_buy_full_position():
    v = _verdict(80, mv=50.0)
    apply_risk([v], "偏多")
    assert v.meta["position_pct"] == 20.0

def test_risk_smallcap_discount():
    v = _verdict(80, mv=8.0)
    apply_risk([v], "偏多")
    assert v.meta["position_pct"] == 10.0             # 20×0.5

def test_risk_macro_bear_discount():
    v = _verdict(80, mv=50.0)
    apply_risk([v], "偏空")
    assert v.meta["position_pct"] == 10.0

def test_risk_zengchi_coef():
    v = _verdict(65, mv=50.0)                          # 增持
    apply_risk([v], "震荡")
    assert v.meta["position_pct"] == 12.0             # 20×0.6

def test_risk_hold_no_position():
    v = _verdict(50, mv=50.0)                          # 持有
    apply_risk([v], "震荡")
    assert v.meta["position_pct"] == 0.0

def test_risk_max_positions_standby():
    vs = [_verdict(80 - i, mv=50.0) for i in range(7)]
    for i, v in enumerate(vs):
        v.symbol = f"60000{i}"
    apply_risk(vs, "震荡")
    with_pos = [v for v in vs if v.meta["position_pct"] > 0]
    standby = [v for v in vs if any(op.agent == "risk" and op.evidence.get("standby")
                                    for op in v.opinions)]
    assert len(with_pos) == 5 and len(standby) == 2   # 5只满员+2候补


# ── 批量接线（mock 辩论）──
def _ohlcv(n=250, seed=7):
    np.random.seed(seed)
    c = pd.Series(20 + np.random.randn(n).cumsum() * 0.2).clip(lower=1.0)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n).astype(str),
        "open": c * 0.995, "high": c * 1.02, "low": c * 0.98, "close": c,
        "volume": np.random.randint(100000, 1000000, n).astype(float),
        "market_cap": c * 5e8,
    })

def _ctx():
    return TeamContext(macro_level="偏多", macro_score=60,
                       sector_scores={"半导体": 75.0},
                       sector_map={"600000": "半导体"},
                       concept_map={"600000": "AI算力"})


def test_batch_no_debate_has_risk_opinion():
    out = core.analyze_batch([("600000", "A", _ohlcv())], _ctx())
    v = out[0]
    assert any(op.agent == "risk" for op in v.opinions)
    assert "position_pct" in v.meta

def test_batch_debate_only_above_threshold():
    debated = []
    def fake_chat(prompt):
        debated.append(1)
        return '{"signal": "bullish", "confidence": 70, "reasoning": "ok"}'
    out = core.analyze_batch([("600000", "A", _ohlcv())], _ctx(),
                             debate=True, debate_min=999.0, chat_fn=fake_chat)
    assert not debated                                # 阈值拦截，零调用
    assert not out[0].meta.get("debated")

def test_batch_debate_fuses_score():
    def fake_chat(prompt):
        return '{"signal": "bearish", "confidence": 85, "reasoning": "反方胜"}'
    v0 = core.analyze_batch([("600000", "A", _ohlcv())], _ctx())[0]
    v1 = core.analyze_batch([("600000", "A", _ohlcv())], _ctx(),
                            debate=True, debate_min=0.0, chat_fn=fake_chat)[0]
    assert v1.meta.get("debated") and v1.score < v0.score   # 看空仲裁拉低分数
    ref = [op for op in v1.opinions if op.agent == "referee"]
    assert ref and ref[0].evidence["p0_score"] == v0.score


# ── persona 人格角色（mock）──
def test_persona_opinions_from_skill_file(tmp_path, monkeypatch):
    from alphapulse.agent_team import persona as P
    pdir = tmp_path / "personas"
    pdir.mkdir()
    (pdir / "金渐成.md").write_text("你是金渐成，严守知行体系纪律。", encoding="utf-8")
    monkeypatch.setattr(P, "PERSONA_DIR", pdir)

    seen = {}
    def fake_chat(prompt, system):
        seen["system"] = system
        return '{"signal": "bullish", "confidence": 70, "reasoning": "白上黄，缩量回踩"}'
    ops = P.persona_opinions(_verdict(), chat_fn=fake_chat)
    assert len(ops) == 1 and ops[0].agent == "persona:金渐成"
    assert ops[0].signal == "bullish" and ops[0].confidence == 70.0
    assert "金渐成" in seen["system"]          # skill 内容进入 system prompt


def test_persona_views_injected_into_referee(tmp_path, monkeypatch):
    from alphapulse.agent_team import persona as P
    pdir = tmp_path / "personas"
    pdir.mkdir()
    (pdir / "金渐成.md").write_text("知行体系。", encoding="utf-8")
    monkeypatch.setattr(P, "PERSONA_DIR", pdir)

    prompts = []
    def fake_debate_chat(prompt):
        prompts.append(prompt)
        return '{"signal": "bullish", "confidence": 66, "reasoning": "ok"}'
    def fake_persona_chat(prompt, system):
        return '{"signal": "bearish", "confidence": 61, "reasoning": "破位"}'

    out = core.analyze_batch([("600000", "A", _ohlcv())], _ctx(),
                             debate=True, debate_min=0.0,
                             chat_fn=fake_debate_chat,
                             persona_chat_fn=fake_persona_chat)
    v = out[0]
    assert any(op.agent == "persona:金渐成" for op in v.opinions)
    # 仲裁 prompt（第3次调用）应包含人格观点
    assert "persona:金渐成的观点" in prompts[2] and "破位" in prompts[2]


def test_persona_absent_no_effect(monkeypatch):
    from alphapulse.agent_team import persona as P
    monkeypatch.setattr(P, "PERSONA_DIR", Path("/nonexistent"))
    assert P.persona_opinions(_verdict(), chat_fn=lambda p, s: "x") == []


# ── 决策日志闭环 ──
def test_decision_log_roundtrip(tmp_path):
    from alphapulse.agent_team import decision_log as DL
    p = tmp_path / "d.jsonl"
    v = _verdict(72.0, mv=50.0)
    v.meta["position_pct"] = 12.0
    n = DL.append_decisions([v, _verdict(ok=False)], "2026-07-03", path=p)
    assert n == 1                                  # 观望不入库
    # 同日重复研判 → 读取端只留最新
    v2 = _verdict(80.0, mv=50.0)
    DL.append_decisions([v2], "2026-07-03", path=p)
    df = DL.load_decisions(path=p)
    assert len(df) == 1 and df.iloc[0]["score"] == 80.0
    assert df.iloc[0]["position_pct"] == 0.0 or "portfolio_signal" in df.columns
