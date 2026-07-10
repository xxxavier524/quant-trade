"""统一信号协议聚合测试（路线图#8）。"""

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.ranking.signal_opinion import (  # noqa: E402
    SignalOpinion, aggregate, to_score_100, from_rule_ml)


def test_all_agree_bullish():
    ops = [SignalOpinion("rule", 0.8, 1.0), SignalOpinion("ml", 0.9, 0.8)]
    agg = aggregate(ops)
    assert 0.8 <= agg <= 0.9   # 加权在两者之间且偏高


def test_disagreement_cancels():
    ops = [SignalOpinion("rule", 0.8, 1.0), SignalOpinion("ml", -0.8, 1.0)]
    assert abs(aggregate(ops)) < 1e-9   # 等置信反向 → 抵消


def test_dead_zone_zeros_weak():
    ops = [SignalOpinion("rule", 0.1, 1.0), SignalOpinion("ml", 0.15, 1.0)]
    assert aggregate(ops, dead_zone=0.2) == 0.0   # 全在死区 → 0
    assert aggregate(ops, dead_zone=0.0) != 0.0   # 无死区 → 非0


def test_dead_zone_keeps_strong():
    ops = [SignalOpinion("rule", 0.05, 1.0), SignalOpinion("ml", 0.9, 1.0)]
    agg = aggregate(ops, dead_zone=0.2)
    assert abs(agg - 0.9) < 1e-9   # 弱的清零,只剩强的


def test_confidence_weighting():
    ops = [SignalOpinion("rule", 1.0, 0.9), SignalOpinion("ml", -1.0, 0.1)]
    agg = aggregate(ops)
    assert agg > 0.5   # 高置信看多主导


def test_ump_veto_caps():
    ops = [SignalOpinion("rule", 0.9, 1.0), SignalOpinion("ml", 0.9, 1.0),
           SignalOpinion("ump", -1.0, 1.0)]
    assert aggregate(ops) == -1.0   # UMP 否决封顶


def test_empty_is_neutral():
    assert aggregate([]) == 0.0


def test_to_score_100():
    assert to_score_100(0.0) == 50.0
    assert to_score_100(1.0) == 100.0
    assert to_score_100(-1.0) == 0.0


def test_from_rule_ml_ml_neutral():
    ops = from_rule_ml(rule_z=0.0, ml_prob=0.5)
    # ml 概率 0.5 → signed 0; rule z 0 → tanh 0
    assert aggregate(ops) == 0.0


def test_from_rule_ml_directions():
    ops = from_rule_ml(rule_z=2.0, ml_prob=0.9)
    assert aggregate(ops) > 0.5   # 都看多
    ml = next(o for o in ops if o.source == "ml")
    assert abs(ml.signed - 0.8) < 1e-9   # 2*(0.9-0.5)=0.8


def test_from_rule_ml_no_model():
    ops = from_rule_ml(rule_z=1.0, ml_prob=None)
    assert len(ops) == 1 and ops[0].source == "rule"
    assert abs(aggregate(ops) - math.tanh(1.0)) < 1e-9
