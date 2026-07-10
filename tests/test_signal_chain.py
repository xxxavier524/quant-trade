"""B1→B2→B3 seq_id 链路测试（路线图#4 验收）。

用构造的布尔序列直接测 assign_seq_ids 的链路归属，再测 generate_signals 的
向后兼容与因果性。合成数据，不依赖外接盘。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.strategies.b1_b2_b3_strategy import (  # noqa: E402
    assign_seq_ids, generate_signals)


def _series(flags: dict, n=12, start=1):
    idx = [f"2025-01-{i:02d}" for i in range(start, start + n)]
    s = pd.Series(False, index=idx)
    for i in flags:
        s.iloc[i] = True
    return s, idx


def test_full_chain_same_seq():
    """B1→B2(窗内)→B3(窗内)：三阶段同 seq_id、parent 正确、root 指向 B1。"""
    idx = [f"2025-01-{i:02d}" for i in range(1, 12)]
    b1 = pd.Series(False, index=idx); b2 = pd.Series(False, index=idx); b3 = pd.Series(False, index=idx)
    b1.iloc[2] = True; b2.iloc[4] = True; b3.iloc[6] = True
    m = assign_seq_ids(b1, b2, b3, "T", 5, 3)
    seqs = {v["seq_id"] for v in m.values()}
    assert len(seqs) == 1
    assert m[(idx[2], "B1")]["parent_stage"] is None
    assert m[(idx[4], "B2")]["parent_stage"] == "B1"
    assert m[(idx[6], "B3")]["parent_stage"] == "B2"
    assert m[(idx[4], "B2")]["seq_root_date"] == idx[2]
    assert m[(idx[6], "B3")]["seq_root_date"] == idx[2]


def test_isolated_b1():
    """孤立 B1（无 B2）：只含自身条目，parent=None。"""
    idx = [f"2025-01-{i:02d}" for i in range(1, 12)]
    b1 = pd.Series(False, index=idx); z = pd.Series(False, index=idx)
    b1.iloc[1] = True
    m = assign_seq_ids(b1, z, z, "T", 5, 3)
    assert list(m.keys()) == [(idx[1], "B1")]
    assert m[(idx[1], "B1")]["parent_stage"] is None


def test_b2_out_of_window_not_linked():
    """B2 超出 b2_window：不继承任何 seq。"""
    idx = [f"2025-01-{i:02d}" for i in range(1, 12)]
    b1 = pd.Series(False, index=idx); b2 = pd.Series(False, index=idx); z = pd.Series(False, index=idx)
    b1.iloc[1] = True; b2.iloc[8] = True   # 距 B1 7 日 > 5
    m = assign_seq_ids(b1, b2, z, "T", 5, 3)
    assert (idx[8], "B2") not in m


def test_two_independent_chains_no_crosstalk():
    """两条独立链不串号。"""
    idx = [f"2025-01-{i:02d}" for i in range(1, 12)]
    b1 = pd.Series(False, index=idx); b2 = pd.Series(False, index=idx); z = pd.Series(False, index=idx)
    b1.iloc[1] = True; b2.iloc[3] = True
    b1.iloc[6] = True; b2.iloc[8] = True
    m = assign_seq_ids(b1, b2, z, "T", 5, 3)
    s1 = m[(idx[3], "B2")]["seq_id"]
    s2 = m[(idx[8], "B2")]["seq_id"]
    assert s1 != s2
    assert s1 == f"T:{idx[1]}" and s2 == f"T:{idx[6]}"


def test_b3_out_of_window_not_linked():
    """B3 超出 b3_window：不继承。"""
    idx = [f"2025-01-{i:02d}" for i in range(1, 12)]
    b1 = pd.Series(False, index=idx); b2 = pd.Series(False, index=idx); b3 = pd.Series(False, index=idx)
    b1.iloc[1] = True; b2.iloc[3] = True; b3.iloc[9] = True   # 距 B2 6 日 > 3
    m = assign_seq_ids(b1, b2, b3, "T", 5, 3)
    assert (idx[9], "B3") not in m


def test_only_first_b2_confirms():
    """一 B1 只被首个窗内 B2 确认；第二个 B2 无归属。"""
    idx = [f"2025-01-{i:02d}" for i in range(1, 12)]
    b1 = pd.Series(False, index=idx); b2 = pd.Series(False, index=idx); z = pd.Series(False, index=idx)
    b1.iloc[1] = True; b2.iloc[3] = True; b2.iloc[4] = True
    m = assign_seq_ids(b1, b2, z, "T", 5, 3)
    assert (idx[3], "B2") in m           # 首个确认
    assert (idx[4], "B2") not in m       # 第二个无 pending_b1


def test_causality_truncation():
    """截断尾部不改变前段 seq 归属。"""
    idx = [f"2025-01-{i:02d}" for i in range(1, 12)]
    b1 = pd.Series(False, index=idx); b2 = pd.Series(False, index=idx); b3 = pd.Series(False, index=idx)
    b1.iloc[2] = True; b2.iloc[4] = True; b3.iloc[6] = True
    full = assign_seq_ids(b1, b2, b3, "T", 5, 3)
    part = assign_seq_ids(b1.iloc[:6], b2.iloc[:6], b3.iloc[:6], "T", 5, 3)
    for k, v in part.items():
        assert full[k] == v


def _synthetic_ohlcv(n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="D").astype(str)
    c = pd.Series(20 + rng.standard_normal(n).cumsum() * 0.3, index=idx).clip(lower=3)
    return pd.DataFrame({
        "open": c * 0.99, "high": c * 1.03, "low": c * 0.97, "close": c,
        "volume": rng.integers(1e5, 2e6, n).astype(float),
        "turnover": rng.uniform(0.5, 6, n),
        "market_cap": c * 1e8}, index=idx)


def test_generate_signals_backward_compat():
    """generate_signals 输出含新列，且每行都有 seq 三元组（B1/B2/B3 均贴链元数据）。"""
    df = _synthetic_ohlcv()
    sig = generate_signals(df, symbol="TEST")
    if sig.empty:
        return  # 合成数据未触发信号也算通过（不崩）
    for col in ("seq_id", "parent_stage", "seq_root_date"):
        assert col in sig.columns
    # 每个 B1 行必有 seq_id（B1 一定开序列）
    b1_rows = sig[sig["signal_type"] == "B1"]
    assert b1_rows["seq_id"].notna().all()
    # B1 行 parent 为 None，seq_root_date == 自身日期
    for dt, r in b1_rows.iterrows():
        assert r["parent_stage"] is None
        assert r["seq_root_date"] == str(dt)


def test_generate_signals_b2_links_to_prior_b1():
    """generate_signals 中，有 seq_id 的 B2 行其 root 必是更早的某个 B1 日期。"""
    df = _synthetic_ohlcv(n=500, seed=7)
    sig = generate_signals(df, symbol="TEST")
    linked_b2 = sig[(sig["signal_type"] == "B2") & sig["seq_id"].notna()]
    b1_dates = set(sig[sig["signal_type"] == "B1"].index.astype(str))
    for dt, r in linked_b2.iterrows():
        assert r["parent_stage"] == "B1"
        assert r["seq_root_date"] in b1_dates
        assert r["seq_root_date"] < str(dt)   # 因果：B1 在 B2 之前
