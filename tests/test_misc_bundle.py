"""Hurst分流(#12) + CSRankNorm标签(#12) 测试。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.factors import hurst  # noqa: E402
from alphapulse.ml.label_transform import csrank_norm  # noqa: E402


def _mk(p):
    p = np.asarray(p, dtype=float)
    return pd.DataFrame({"open": p, "high": p * 1.01, "low": p * 0.99,
                         "close": p, "volume": np.ones(len(p))})


# ---------------------------------------------------------------- Hurst

def test_hurst_mean_reversion_below_random_walk():
    """均值回归序列 H 显著低于随机游走（估计器可靠捕捉的均值回归轴）。"""
    rng = np.random.default_rng(1)
    n = 2000
    rw = np.cumsum(rng.normal(0, 1, n)) + 100
    mr = np.zeros(n); mr[0] = 100
    for i in range(1, n):
        mr[i] = mr[i - 1] - 0.5 * (mr[i - 1] - 100) + rng.normal(0, 1)
    h_rw = hurst.compute(_mk(rw)).dropna().mean()
    h_mr = hurst.compute(_mk(mr)).dropna().mean()
    assert h_mr < h_rw - 0.15, f"MR {h_mr:.3f} 未显著低于 RW {h_rw:.3f}"


def test_hurst_causal():
    rng = np.random.default_rng(3)
    n = 400
    p = np.cumsum(rng.normal(0, 1, n)) + 100
    df = _mk(p)
    full = hurst.compute(df)
    part = hurst.compute(df.iloc[:300])
    m = ~(full.iloc[:300].isna() | part.isna())
    assert np.allclose(full.iloc[:300][m], part[m])


def test_hurst_warmup_nan():
    p = np.cumsum(np.random.default_rng(0).normal(0, 1, 200)) + 100
    h = hurst.compute(_mk(p), window=120)
    assert h.iloc[:119].isna().all()
    assert h.iloc[120:].notna().any()


def test_hurst_regime_labels():
    p = np.cumsum(np.random.default_rng(0).normal(0, 1, 300)) + 100
    reg = hurst.compute_regime(_mk(p))
    assert set(reg.unique()) <= {-1, 0, 1}


# ---------------------------------------------------------------- CSRankNorm

def _panel_down_market():
    """构造下跌市：某日大多数股 fwd<0（beta 污染），少数相对强。"""
    rows = []
    rng = np.random.default_rng(5)
    for d in ["2025-01-01", "2025-01-02"]:
        drift = -0.05 if d == "2025-01-01" else -0.03   # 下跌市
        for s in range(200):
            rows.append({"date": d, "symbol": f"{s:03d}",
                         "fwd5": drift + rng.normal(0, 0.02)})
    return pd.DataFrame(rows)


def test_csranknorm_removes_beta():
    """去 beta：下跌市日 raw 正样本率低，CSRankNorm 恒≈50%。"""
    panel = _panel_down_market()
    raw_pos = (panel["fwd5"] > 0).mean()
    cs = csrank_norm(panel, "fwd5", "date", "binary")
    cs_pos = cs.mean()
    assert raw_pos < 0.3, f"构造的下跌市 raw 正样本率应低，实际 {raw_pos:.2f}"
    assert abs(cs_pos - 0.5) < 0.05, f"CSRankNorm 正样本率应≈0.5，实际 {cs_pos:.2f}"


def test_csranknorm_per_day_median_split():
    """每日截面各≈一半为1。"""
    panel = _panel_down_market()
    cs = csrank_norm(panel, "fwd5", "date", "binary")
    for d, g in panel.assign(label=cs).groupby("date"):
        assert abs(g["label"].mean() - 0.5) < 0.05


def test_csranknorm_pct_and_zscore():
    panel = _panel_down_market()
    pct = csrank_norm(panel, "fwd5", "date", "pct")
    assert pct.min() > 0 and pct.max() <= 1.0
    z = csrank_norm(panel, "fwd5", "date", "zscore")
    assert abs(z.mean()) < 0.1   # 居中


def test_csranknorm_ranks_correctly():
    """同日 fwd 最高的股 → pct 最高。"""
    df = pd.DataFrame({"date": ["d"] * 5, "symbol": list("abcde"),
                       "fwd5": [0.1, -0.2, 0.3, -0.1, 0.0]})
    pct = csrank_norm(df, "fwd5", "date", "pct")
    assert pct.iloc[2] == 1.0   # fwd 0.3 最高
    assert pct.iloc[1] == 0.2   # fwd -0.2 最低
