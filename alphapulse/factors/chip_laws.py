"""筹码分布引擎 + Z哥筹码理论四法则（P1 #21）。

来源：zettaranc indicators 3.13「筹码理论」（陈浩/杨新宇一脉）。
引擎：换手率衰减法——每日按换手率衰减存量筹码，当日成交量按 [low,high]
三角权重（收盘附近权重高）注入价格网格。需要 `turnover` 列；缺失时用
volume/volume.rolling(250).max() 粗略代理。

四法则（对当日筹码分布判定）：
- 低位密集（行情起点）：峰值±10%价区集中≥70% 且 上方套牢盘≤30%
- 锁仓拉升（牛股基因）：价格上行且低位筹码留存≥40%
- 高位密集禁买（终局）：低位筹码消失80%+ 且当前价远离主力成本
- 获利盘比例 / 主力平均成本（筹码三问的数值基础）

注意：日线近似实现，与真实 Level-2 筹码有偏差；先过事件研究再用。
"""

import numpy as np
import pandas as pd

N_BINS = 80


def _turnover_frac(data: pd.DataFrame) -> np.ndarray:
    for col in ("turnover", "turn"):
        if col in data.columns:
            t = pd.to_numeric(data[col], errors="coerce").fillna(0).to_numpy() / 100.0
            return np.clip(t, 0.0, 0.9)
    v = data["volume"].astype(float)
    proxy = (v / v.rolling(250, min_periods=20).max()).fillna(0.05).to_numpy() * 0.15
    return np.clip(proxy, 0.0, 0.9)


def compute_chip_matrix(data: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """返回 (dist[n_days, N_BINS] 归一化筹码分布, price_grid[N_BINS])。"""
    high = data["high"].astype(float).to_numpy()
    low = data["low"].astype(float).to_numpy()
    close = data["close"].astype(float).to_numpy()
    turn = _turnover_frac(data)
    n = len(data)

    p_min, p_max = np.nanmin(low) * 0.98, np.nanmax(high) * 1.02
    grid = np.linspace(p_min, p_max, N_BINS)

    dist = np.zeros((n, N_BINS))
    cur = np.zeros(N_BINS)
    for i in range(n):
        t = turn[i]
        cur *= (1.0 - t)
        lo_idx = np.searchsorted(grid, low[i])
        hi_idx = max(np.searchsorted(grid, high[i]), lo_idx + 1)
        c_idx = np.clip(np.searchsorted(grid, close[i]), lo_idx, hi_idx - 1)
        span = np.arange(lo_idx, min(hi_idx, N_BINS))
        if len(span) == 0:
            span = np.array([min(c_idx, N_BINS - 1)])
        w = 1.0 / (1.0 + np.abs(span - c_idx))          # 收盘附近权重高
        w = w / w.sum()
        cur[span] += t * w
        s = cur.sum()
        dist[i] = cur / s if s > 0 else cur
    return dist, grid


def compute_detail(data: pd.DataFrame) -> pd.DataFrame:
    """每日筹码指标：获利盘比例/主力成本/峰值集中度/上方套牢/低位留存。"""
    dist, grid = compute_chip_matrix(data)
    close = data["close"].astype(float).to_numpy()
    n = len(data)

    profit = np.zeros(n)
    avg_cost = np.zeros(n)
    peak_conc = np.zeros(n)
    above = np.zeros(n)
    low_retain = np.zeros(n)

    for i in range(n):
        d = dist[i]
        total = d.sum()
        if total <= 0:
            continue
        below_mask = grid <= close[i]
        profit[i] = d[below_mask].sum() / total
        avg_cost[i] = float((d * grid).sum() / total)
        peak = grid[int(d.argmax())]
        conc_mask = (grid >= peak * 0.9) & (grid <= peak * 1.1)
        peak_conc[i] = d[conc_mask].sum() / total
        above[i] = d[grid > close[i]].sum() / total
        # 低位留存：60日前低位30%价区的筹码 vs 现在同价区
        if i >= 60:
            ref = dist[i - 60]
            low_zone = grid <= np.quantile(grid[ref > 0], 0.35) if (ref > 0).any() else grid < np.inf
            base = ref[low_zone].sum()
            low_retain[i] = d[low_zone].sum() / base if base > 1e-6 else 1.0
        else:
            low_retain[i] = 1.0

    return pd.DataFrame({
        "profit_ratio": np.clip(profit, 0, 1),
        "avg_cost": avg_cost,
        "peak_concentration": np.clip(peak_conc, 0, 1),
        "above_ratio": np.clip(above, 0, 1),
        "low_zone_retention": np.clip(low_retain, 0, 2),
    }, index=data.index)


def compute_low_density(data: pd.DataFrame, conc_min: float = 0.70,
                        above_max: float = 0.30) -> pd.Series:
    """法则一·低位密集（行情起点）：峰值±10%集中≥70% 且 上方套牢≤30%。"""
    d = compute_detail(data)
    sig = (d["peak_concentration"] >= conc_min) & (d["above_ratio"] <= above_max)
    return sig.fillna(False).astype(bool)


def compute_locked_lift(data: pd.DataFrame, retention_min: float = 0.40,
                        gain_window: int = 20, gain_min: float = 0.05) -> pd.Series:
    """法则二·锁仓拉升（慢牛基因）：20日涨幅≥5% 且 低位筹码留存≥40%。"""
    close = data["close"].astype(float)
    d = compute_detail(data)
    gain = close / close.shift(gain_window) - 1
    sig = (gain >= gain_min) & (d["low_zone_retention"] >= retention_min)
    return sig.fillna(False).astype(bool)


def compute_high_density_forbid(data: pd.DataFrame, retention_max: float = 0.20,
                                cost_mult: float = 1.5) -> pd.Series:
    """法则四·高位密集禁买：低位筹码消失80%+（留存≤20%）且现价≥主力成本1.5倍 → True=禁买。"""
    close = data["close"].astype(float)
    d = compute_detail(data)
    sig = (d["low_zone_retention"] <= retention_max) & (close >= d["avg_cost"] * cost_mult)
    return sig.fillna(False).astype(bool)


def compute(data: pd.DataFrame, **params) -> pd.Series:
    """registry 默认入口 = 低位密集。"""
    return compute_low_density(data, **params)
