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
