"""N型结构因果化（v5 P0-1）对抗性测试。

核心判据：**截断不变性** —— 在 t 日做决策时只能看到 ≤t 的数据，
那么用 data[:t+1] 计算出的 t 日信号，必须与用更长数据（含未来）计算出的
t 日信号完全一致。任何依赖未来K线的实现（旧版 n_struct 阶段标记）都会在此失败。

本文件同时演示旧版确实存在泄漏（保证测试本身有杀伤力）。
"""

import numpy as np
import pandas as pd
import pytest

from alphapulse.factors import n_struct
from alphapulse.strategies.needle_washout import generate_signals as needle_washout_signals
from alphapulse.strategies.b1_b2_b3_strategy import generate_signals as b1b2b3_signals


def _make_n_shape(n: int = 320, seed: int = 7) -> pd.DataFrame:
    """构造含清晰 N 型结构（A→B→C→D）的合成日线。

    A(t=20) → B(t=80) → C(t=135, 回撤61.8%) → D(t=220)，腿长 ≫ 枢轴确认窗(5)。
    """
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    base = np.empty(n)

    # 起始下降段（让 A 成为数据内部的波谷，而非边界点）
    base[:21] = np.linspace(12.0, 10.0, 21)          # → A(t=20)
    base[21:81] = np.linspace(10.0, 20.0, 60)        # A→B 上升
    base[81:136] = np.linspace(20.0, 13.82, 55)      # B→C 回调至 61.8%
    base[136:221] = np.linspace(13.82, 21.0, 85)     # C→D 再上升（突破B）
    base[221:] = np.linspace(21.0, 19.5, n - 221)    # 尾段回落

    # 四个枢轴点打尖峰，保证 argrelextrema 在噪声下也能严格识别
    # （回撤 (20.5-13.0)/(20.5-9.5)=0.727 落在 0.618±0.15 容忍带内）
    base[20] = 9.5     # A：深谷
    base[80] = 20.5    # B：尖峰
    base[135] = 13.0   # C：深谷
    base[220] = 21.5   # D：尖峰（突破B）

    close = base + rng.normal(0, 0.02, n)
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) + rng.uniform(0, 0.05, n)
    low = np.minimum(open_, close) - rng.uniform(0, 0.05, n)
    volume = rng.uniform(5e5, 3e6, n) * (1 + 0.3 * np.sin(t / 7))

    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    }, index=pd.date_range("2022-01-03", periods=n, freq="B"))


def test_compute_causal_schema():
    data = _make_n_shape()
    ctx = n_struct.compute_causal(data)
    assert list(ctx.columns) == ["phase", "a_price", "b_price", "label"]
    assert len(ctx) == len(data)
    assert set(ctx["phase"].unique()) <= {0, 1, 2, 3}
    # 合成数据应至少识别出一段已确认结构
    assert (ctx["phase"] > 0).any(), "合成N型数据应产生已确认阶段"
    assert ctx["label"].notna().any(), "因果标签应出现在确认日"


def test_old_labels_leak_future_information():
    """演示旧版 compute() 泄漏：枢轴日即公布标签，而确认要到 +min_leg_len。"""
    data = _make_n_shape()
    old = n_struct.compute(data, min_leg_len=5, retrace_ratio=0.618)
    causal = n_struct.compute_causal(data, min_leg_len=5, retrace_ratio=0.618)
    assert old.notna().any(), "合成数据应产生旧版标签"
    leaked = old.notna() & causal["label"].isna()
    assert leaked.any(), (
        "旧版标签全部出现在确认日？若真如此说明实现有误——"
        "旧版在枢轴日公布标签，而枢轴日必然早于确认日，泄漏必存在"
    )
    assert leaked.sum() >= 4, "至少 A/B/C/D 四个枢轴都应提前泄漏"


@pytest.mark.parametrize("t", list(range(120, 220, 2)))
def test_causal_phase_truncation_invariance(t):
    """截断不变性：t 日可见的 phase/a/b 只取决于 ≤t 的数据。"""
    data = _make_n_shape()
    full = n_struct.compute_causal(data)
    prefix = n_struct.compute_causal(data.iloc[: t + 1])

    assert full["phase"].iloc[t] == prefix["phase"].iloc[t]
    a_full, a_pre = full["a_price"].iloc[t], prefix["a_price"].iloc[t]
    assert (pd.isna(a_full) and pd.isna(a_pre)) or np.isclose(a_full, a_pre)
    b_full, b_pre = full["b_price"].iloc[t], prefix["b_price"].iloc[t]
    assert (pd.isna(b_full) and pd.isna(b_pre)) or np.isclose(b_full, b_pre)


@pytest.mark.parametrize("t", list(range(120, 220, 2)))
def test_needle_washout_signal_truncation_invariance(t):
    """策略级截断不变性：追加未来数据不得改变 t 日是否出信号。"""
    data = _make_n_shape()
    dt = data.index[t]
    sig_prefix = set(needle_washout_signals(data.iloc[: t + 1], symbol="T").index)
    sig_extended = set(needle_washout_signals(data.iloc[: t + 1 + 12], symbol="T").index)
    assert (dt in sig_prefix) == (dt in sig_extended), (
        f"needle_washout 在 {dt} 的信号被未来数据改变——存在未来函数"
    )


@pytest.mark.parametrize("t", list(range(120, 220, 2)))
def test_b1b2b3_signal_truncation_invariance(t):
    """B1_B2_B3 截断不变性（N_STRUCT 过滤因果化后必须通过）。"""
    data = _make_n_shape()
    dt = data.index[t]
    sig_prefix = set(b1b2b3_signals(data.iloc[: t + 1], symbol="T").index)
    sig_extended = set(b1b2b3_signals(data.iloc[: t + 1 + 12], symbol="T").index)
    assert (dt in sig_prefix) == (dt in sig_extended), (
        f"b1_b2_b3 在 {dt} 的信号被未来数据改变——存在未来函数"
    )
