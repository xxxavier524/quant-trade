"""筹码分布因子（CYQ 成本分布重建，路线图#5）。

从日线 OHLC+成交量+换手率逐日演化每个价位的持仓筹码，给"底部挖掘"补上持仓成本维度。
经典底部确认：B1买点 + 低位单峰密集(conc90低) + 获利盘<15%(profit_ratio低)。

模型（三角分布沉积 + 换手衰减）：
    chips_t = chips_{t-1}*(1-turnover_t) + deposit_t*turnover_t
    deposit_t = 当日成交量按三角分布摊到 [low,high]，峰在均价(H+L+C)/3

输出（compute_chips → DataFrame）:
    profit_ratio : 现价以下筹码占比（获利盘比例），越低=套牢盘越多=底部吸筹
    avg_cost     : 筹码加权平均成本
    conc90       : 中央90%筹码价格带宽/现价，越低=单峰越密集

因果：chips_t 只由 s≤t 数据构成，无未来泄漏。
向量化 exp-cumsum 为快路径，_compute_chips_sequential 为对拍金标准。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_BUCKETS = 200
MAX_TURNOVER = 0.5      # 换手率上限（防脏数据；A股极少>50%）
MIN_TURNOVER = 1e-4


def _prepare(data: pd.DataFrame, n_buckets: int, max_turnover: float):
    """公共预处理：价格网格 + 每日三角分布矩阵 D(T×B) + 换手率。"""
    high = data["high"].to_numpy(dtype=float)
    low = data["low"].to_numpy(dtype=float)
    close = data["close"].to_numpy(dtype=float)
    n = len(close)

    # 换手率（turnover 列为百分比）→ 比例；缺列时用 volume/流通股近似不可得，退化为等权
    if "turnover" in data.columns:
        turn = pd.to_numeric(data["turnover"], errors="coerce").to_numpy(dtype=float) / 100.0
    else:
        turn = np.full(n, np.nan)
    turn = np.clip(np.nan_to_num(turn, nan=0.05), MIN_TURNOVER, max_turnover)

    # 全历史价格网格（bucket 中心）
    p_min = np.nanmin(low)
    p_max = np.nanmax(high)
    if not np.isfinite(p_min) or not np.isfinite(p_max) or p_max <= p_min:
        p_max = p_min + 1.0
    edges = np.linspace(p_min, p_max, n_buckets + 1)
    grid = (edges[:-1] + edges[1:]) / 2.0          # (B,)
    width = edges[1] - edges[0]

    # 当日三角分布 D[t,b]：峰在 avg=(H+L+C)/3，底边 [low,high]，归一到 Σ_b=1
    avg = (high + low + close) / 3.0
    lo = low[:, None]
    hi = high[:, None]
    pk = np.clip(avg, low, high)[:, None]
    g = grid[None, :]
    # 三角形高度：在 [lo,pk] 线性升、[pk,hi] 线性降，端点为0
    left = (g - lo) / np.maximum(pk - lo, 1e-9)
    right = (hi - g) / np.maximum(hi - pk, 1e-9)
    tri = np.where(g < pk, left, right)
    tri = np.where((g >= lo) & (g <= hi), np.clip(tri, 0.0, None), 0.0)
    # 若某日 high==low（一字板），落到最近桶
    degenerate = (high - low) < width
    if degenerate.any():
        idx = np.clip(np.searchsorted(edges, close[degenerate]) - 1, 0, n_buckets - 1)
        tri[degenerate] = 0.0
        tri[np.where(degenerate)[0], idx] = 1.0
    row_sum = tri.sum(axis=1, keepdims=True)
    D = tri / np.where(row_sum > 0, row_sum, 1.0)   # (T,B) 每行 Σ=1

    return grid, D, turn, close


def _summaries(Ccum: np.ndarray, grid: np.ndarray, close: np.ndarray):
    """未归一筹码矩阵 Ccum(T×B) → profit_ratio / avg_cost / conc90 逐日。"""
    total = Ccum.sum(axis=1)
    total_safe = np.where(total > 0, total, np.nan)

    below = grid[None, :] < close[:, None]
    profit_ratio = (Ccum * below).sum(axis=1) / total_safe
    avg_cost = (Ccum * grid[None, :]).sum(axis=1) / total_safe

    cdf = np.cumsum(Ccum, axis=1) / total_safe[:, None]
    # 每行首个 cdf≥阈值 的桶索引（argmax 对布尔取首个 True）
    idx05 = (cdf >= 0.05).argmax(axis=1)
    idx95 = (cdf >= 0.95).argmax(axis=1)
    conc90 = (grid[idx95] - grid[idx05]) / np.where(close > 0, close, np.nan)

    return profit_ratio, avg_cost, conc90


def compute_chips(data: pd.DataFrame, n_buckets: int = DEFAULT_BUCKETS,
                  max_turnover: float = MAX_TURNOVER) -> pd.DataFrame:
    """向量化 CYQ：逐日 profit_ratio / avg_cost / conc90（快路径）。

    Returns:
        DataFrame[profit_ratio, avg_cost, conc90]，索引对齐 data
    """
    grid, D, turn, close = _prepare(data, n_buckets, max_turnover)

    decaylog = np.cumsum(np.log1p(-turn))               # (T,) ≤0 递减
    # 减 decaylog[-1] 使指数∈(0,1] 防溢出（全局常数，按日归一时抵消）
    inv = np.exp(decaylog[-1] - decaylog)               # (T,) ∈(0,1]
    A = D * (turn * inv)[:, None]                        # (T,B)
    Ccum = np.cumsum(A, axis=0)                          # (T,B) 未归一筹码（× exp(decaylog_t)）

    pr, ac, c90 = _summaries(Ccum, grid, close)
    return pd.DataFrame({"profit_ratio": pr, "avg_cost": ac, "conc90": c90},
                        index=data.index)


def _compute_chips_sequential(data: pd.DataFrame, n_buckets: int = DEFAULT_BUCKETS,
                              max_turnover: float = MAX_TURNOVER) -> pd.DataFrame:
    """逐日递归参考实现（对拍金标准；O(T) python，数值稳定）。"""
    grid, D, turn, close = _prepare(data, n_buckets, max_turnover)
    n, b = D.shape
    chips = np.zeros(b)
    Ccum = np.zeros((n, b))
    for t in range(n):
        chips = chips * (1.0 - turn[t]) + D[t] * turn[t]
        Ccum[t] = chips
    pr, ac, c90 = _summaries(Ccum, grid, close)
    return pd.DataFrame({"profit_ratio": pr, "avg_cost": ac, "conc90": c90},
                        index=data.index)


def compute(data: pd.DataFrame, profit_threshold: float = 0.15,
            n_buckets: int = DEFAULT_BUCKETS,
            max_turnover: float = MAX_TURNOVER) -> pd.Series:
    """CHIP_PROFIT_LOW：获利盘比例 < profit_threshold（底部吸筹完成信号）。"""
    chips = compute_chips(data, n_buckets, max_turnover)
    return (chips["profit_ratio"] < profit_threshold).fillna(False).astype(bool)


def compute_single_peak(data: pd.DataFrame, conc_threshold: float = 0.12,
                        n_buckets: int = DEFAULT_BUCKETS,
                        max_turnover: float = MAX_TURNOVER) -> pd.Series:
    """CHIP_SINGLE_PEAK：90%筹码集中度 < conc_threshold（单峰密集）。"""
    chips = compute_chips(data, n_buckets, max_turnover)
    return (chips["conc90"] < conc_threshold).fillna(False).astype(bool)


def compute_indicator(data: pd.DataFrame, n_buckets: int = DEFAULT_BUCKETS,
                      max_turnover: float = MAX_TURNOVER) -> pd.DataFrame:
    """CHIP_DISTRIBUTION：三列指标输出（profit_ratio/avg_cost/conc90）。"""
    return compute_chips(data, n_buckets, max_turnover)
