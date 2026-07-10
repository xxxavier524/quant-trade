"""K线包含合并预处理测试（路线图#10）。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.utils.kline_merge import (  # noqa: E402
    merge_klines, map_merged_signal_to_original)


def _df(highs, lows, dates=None):
    n = len(highs)
    dates = dates or [f"2025-01-{i+1:02d}" for i in range(n)]
    return pd.DataFrame({"open": lows, "high": highs, "low": lows,
                         "close": highs, "volume": [1.0] * n, "date": dates})


def test_no_inclusion_passthrough():
    df = _df([10, 11, 12, 13, 14], [5, 6, 7, 8, 9])
    m, o2m = merge_klines(df)
    assert len(m) == 5
    assert (o2m == np.arange(5)).all()


def test_inclusion_up_takes_high_high():
    # bar0[10,8] bar1[11,9](向上) bar2[10.5,9.5]被bar1含 → 高高: high=11 low=9.5
    df = pd.DataFrame({"open": [9, 10, 10], "high": [10, 11, 10.5],
                       "low": [8, 9, 9.5], "close": [9, 10.5, 10],
                       "volume": [1, 1, 1], "date": ["a", "b", "c"]})
    m, _ = merge_klines(df)
    assert m.iloc[1]["high"] == 11 and m.iloc[1]["low"] == 9.5


def test_inclusion_down_takes_low_low():
    # bar0[12,8] bar1[10,6](向下) bar2[11,7]含bar1 → 低低: high=10 low=6
    df = pd.DataFrame({"open": [10, 9, 9], "high": [12, 10, 11],
                       "low": [8, 6, 7], "close": [9, 7, 8],
                       "volume": [1, 1, 1], "date": ["a", "b", "c"]})
    m, _ = merge_klines(df)
    assert m.iloc[1]["high"] == 10 and m.iloc[1]["low"] == 6


def test_merged_not_longer_than_raw():
    rng = np.random.default_rng(3)
    n = 200
    c = 20 + rng.standard_normal(n).cumsum() * 0.3
    df = pd.DataFrame({"open": c, "high": c + np.abs(rng.normal(0, 0.5, n)),
                       "low": c - np.abs(rng.normal(0, 0.5, n)), "close": c,
                       "volume": rng.integers(1e5, 1e6, n).astype(float),
                       "date": [f"d{i}" for i in range(n)]})
    m, o2m = merge_klines(df)
    assert len(m) <= n
    assert o2m[0] == 0 and o2m[-1] == len(m) - 1
    assert (np.diff(o2m) >= 0).all()          # 单调非降
    assert set(o2m) == set(range(len(m)))     # 覆盖全部合并段


def test_causality_truncation():
    rng = np.random.default_rng(7)
    n = 200
    c = 20 + rng.standard_normal(n).cumsum() * 0.3
    df = pd.DataFrame({"open": c, "high": c + np.abs(rng.normal(0, 0.6, n)),
                       "low": c - np.abs(rng.normal(0, 0.6, n)), "close": c,
                       "volume": np.ones(n), "date": [f"d{i}" for i in range(n)]})
    cut = 120
    _, full = merge_klines(df)
    _, part = merge_klines(df.iloc[:cut])
    assert (full[:cut] == part).all()          # 截断不改前段映射


def test_map_signal_to_original():
    df = pd.DataFrame({"open": [9, 10, 10], "high": [10, 11, 10.5],
                       "low": [8, 9, 9.5], "close": [9, 10.5, 10],
                       "volume": [1, 1, 1], "date": ["a", "b", "c"]})
    m, _ = merge_klines(df)              # 合并段1 = orig[1..2], orig_end=2
    sig = np.array([False, True] + [False] * (len(m) - 2))
    orig = map_merged_signal_to_original(sig, m, len(df))
    assert len(orig) == 3
    assert orig[2] and not orig[0] and not orig[1]   # 落在合并段末尾日 idx2


def test_volume_conserved():
    """合并段 volume = 段内原始 volume 之和。"""
    df = pd.DataFrame({"open": [9, 10, 10], "high": [10, 11, 10.5],
                       "low": [8, 9, 9.5], "close": [9, 10.5, 10],
                       "volume": [100, 200, 150], "date": ["a", "b", "c"]})
    m, _ = merge_klines(df)
    assert m["volume"].sum() == 450          # 总量守恒
    assert m.iloc[1]["volume"] == 350        # 段1 = 200+150


def test_empty():
    df = pd.DataFrame({"open": [], "high": [], "low": [], "close": [],
                       "volume": [], "date": []})
    m, o2m = merge_klines(df)
    assert len(m) == 0 and len(o2m) == 0
