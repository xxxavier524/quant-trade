"""Tests for IC-IR factor weighter with exponential decay."""
import json

import numpy as np
import pandas as pd
import pytest

from alphapulse.ranking.factor_weighter import (
    compute_ic_ir,
    compute_rank_ic,
    exponential_decay_weight,
    FactorWeighter,
)


def test_rank_ic_perfect():
    """Perfect positive correlation should give IC = 1.0."""
    n = 50
    vals = np.arange(n, dtype=float)
    ic = compute_rank_ic(vals, vals)
    assert ic == pytest.approx(1.0, abs=1e-10)


def test_rank_ic_negative():
    """Perfect negative correlation should give IC = -1.0."""
    n = 50
    vals = np.arange(n, dtype=float)
    ic = compute_rank_ic(vals, -vals)
    assert ic == pytest.approx(-1.0, abs=1e-10)


def test_rank_ic_small_sample():
    """Fewer than 30 valid samples should return 0.0."""
    vals = np.arange(29, dtype=float)
    ic = compute_rank_ic(vals, vals)
    assert ic == 0.0


def test_ic_ir():
    """Constant IC series (zero std) should return 0.0 IR."""
    ics = [0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
    ir = compute_ic_ir(ics)
    assert ir == pytest.approx(0.0, abs=1e-10)


def test_ic_ir_positive():
    """Varying IC series should return a positive IR."""
    ics = [0.02, 0.07, 0.04, 0.06, 0.03, 0.08, 0.05, 0.04, 0.07, 0.03]
    ir = compute_ic_ir(ics)
    assert ir > 0.0


def test_exponential_decay():
    """Stable IC series with exponential decay should return approximately the mean."""
    ics = [0.05] * 30
    w_mean = exponential_decay_weight(ics, half_life=30)
    assert w_mean == pytest.approx(0.05, abs=1e-10)


def test_factor_weighter_save_load(tmp_path):
    """Save then reload should preserve weights and IC history."""
    config_file = tmp_path / "factor_weights.json"

    # Create and populate
    fw1 = FactorWeighter(config_path=str(config_file))
    fw1.weights = {"stratA": {"f1": 0.6, "f2": 0.4}}
    fw1.ic_history = {"stratA": {"f1": [0.05, 0.07, 0.03], "f2": [0.02, 0.04, 0.01]}}
    fw1.save()

    # Verify file exists
    assert config_file.exists()

    # Load into new instance
    fw2 = FactorWeighter(config_path=str(config_file))
    assert fw2.weights == {"stratA": {"f1": 0.6, "f2": 0.4}}
    assert fw2.ic_history == {"stratA": {"f1": [0.05, 0.07, 0.03], "f2": [0.02, 0.04, 0.01]}}


# ---- 有符号 IC 加权（2026-07-28 修正 abs(IC) 反指当正指）----

def test_negative_ic_factor_gets_zero_weight(tmp_path):
    """稳定反向预测的因子（IC 显著为负）不应拿到正权重。

    旧实现 raw_w = abs(decay_ic)*boost 会给它与同强度正向因子相同的权重。
    """
    from alphapulse.ranking.factor_weighter import FactorWeighter
    cfg = tmp_path / "w.json"
    fw = FactorWeighter(config_path=str(cfg))
    fw.ic_history = {"s": {"good": [0.06, 0.05, 0.07],
                           "bad": [-0.06, -0.05, -0.07]}}
    w = fw.compute_weights("s")
    assert w["bad"] == 0.0, f"负IC因子权重应为0，实际 {w['bad']}"
    assert w["good"] > 0.99, f"唯一正IC因子应拿到几乎全部权重，实际 {w['good']}"


def test_all_negative_ic_returns_empty_and_preserves_existing(tmp_path):
    """全为负IC时返回空字典（不写权重），避免把既有权重清空或全置反。"""
    from alphapulse.ranking.factor_weighter import FactorWeighter
    fw = FactorWeighter(config_path=str(tmp_path / "w.json"))
    fw.ic_history = {"s": {"a": [-0.05, -0.04], "b": [-0.03, -0.02]}}
    assert fw.compute_weights("s") == {}
