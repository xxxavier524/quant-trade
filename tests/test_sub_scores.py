"""子分数单调性与边界测试（Phase 2）。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.ranking import sub_scores as ss


def _series(vals):
    return pd.Series(vals, dtype=float)


def test_j_low_monotonic_decreasing():
    j = _series([-20, 0, 13, 30, 50])
    s = ss.score_j_low(j)
    assert (s.diff().dropna() <= 0).all(), "J越高分应越低"
    assert s.iloc[0] == 1.0 and s.iloc[-1] == 0.0
    # J恰好在阈值13时应得中高分
    assert 0.55 <= s.iloc[2] <= 0.65


def test_pct_calm():
    pct = _series([0, 2.9, 3.0, 6.0, 9.0, 12.0])
    s = ss.score_pct_calm(pct)
    assert s.iloc[0] == s.iloc[1] == s.iloc[2] == 1.0, "±3%以内满分"
    assert (s.diff().dropna() <= 0).all()
    assert s.iloc[-1] == 0.0


def test_amplitude_monotonic():
    amp = _series([0, 4.5, 9.0, 18.0])
    s = ss.score_amplitude(amp)
    assert (s.diff().dropna() < 0).all()
    assert s.iloc[0] == 1.0 and s.iloc[-1] == 0.0


def test_trend_gap_centered():
    white = _series([95, 100, 105])
    yellow = _series([100, 100, 100])
    s = ss.score_trend_gap(white, yellow)
    assert s.iloc[0] == 0.0          # 白低于黄5%
    assert abs(s.iloc[1] - 0.5) < 1e-9  # 贴线
    assert s.iloc[2] == 1.0          # 白高于黄5%


def test_vol_shrink_rewards_shrink():
    # 40日均量1000，今日量从2000缩到250
    vol = _series([1000.0] * 40 + [2000.0])
    s_high = ss.score_vol_shrink(vol).iloc[-1]
    vol2 = _series([1000.0] * 40 + [250.0])
    s_low = ss.score_vol_shrink(vol2).iloc[-1]
    assert s_low > s_high, "缩量应得分更高"
    assert s_low > 0.95


def test_bowl_binary():
    close = _series([10, 12, 9])
    white = _series([11, 11, 11])
    yellow = _series([9.5, 9.5, 9.5])
    s = ss.score_bowl(close, white, yellow)
    assert list(s) == [1.0, 0.0, 0.0], "白下黄上=碗里"


def test_compute_sub_scores_smoke():
    np.random.seed(7)
    n = 300
    c = pd.Series(20 + np.random.randn(n).cumsum() * 0.2).clip(lower=1)
    df = pd.DataFrame({
        "open": c * 0.995, "high": c * 1.02, "low": c * 0.98, "close": c,
        "volume": np.random.randint(100000, 1000000, n).astype(float),
    })
    out = ss.compute_sub_scores(df)
    assert len(out) == 13  # 11原始 + ma_bull + weekly_cross
    for k, v in out.items():
        assert 0.0 <= v <= 1.0, f"{k}={v} 超出[0,1]"


def test_insufficient_history_returns_empty():
    df = pd.DataFrame({"open": [1] * 50, "high": [1] * 50,
                       "low": [1] * 50, "close": [1] * 50, "volume": [1] * 50})
    assert ss.compute_sub_scores(df) == {}
