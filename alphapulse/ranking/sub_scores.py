"""连续子分数 — 把通达信布尔条件转为 0-1 连续评分（Phase 2 核心）。

设计原则（docs/trading_system.md §1）：
- 每个子分数向量化计算，返回与输入同长的 Series，取值 [0,1]
- 布尔条件的"满足程度"连续化：恰好达标≈0.6，远超达标→1，远不达标→0
- 评分仅用于排序筛选；原始布尔信号（全条件AND）另行保留为"严格信号"徽章

所有函数只依赖 ≤t 的数据（rolling/ewm 因果），无未来函数。
"""

import numpy as np
import pandas as pd

from alphapulse.factors.b1_formula import compute_kdj_j, compute_macd_dif
from alphapulse.factors.zhixing_trend import compute_short_trend, compute_bull_bear_line


def _clip01(s: pd.Series) -> pd.Series:
    return s.clip(0.0, 1.0)


def score_j_low(j: pd.Series, threshold: float = 13.0) -> pd.Series:
    """J值越低分越高。J=threshold≈0.6，J≤-15→1，J≥45→0。"""
    return _clip01(0.6 + (threshold - j) / 45.0)


def score_pct_calm(pct: pd.Series, limit: float = 3.0) -> pd.Series:
    """当日涨跌幅温和（|pct|≤limit 满分区间，超出线性衰减至3倍limit归零）。"""
    excess = (pct.abs() - limit).clip(lower=0)
    return _clip01(1.0 - excess / (2 * limit))


def score_amplitude(amp: pd.Series, limit: float = 9.0) -> pd.Series:
    """振幅越小越好。amp=0→1，amp=limit→0.4，amp≥2*limit→0。"""
    return _clip01(1.0 - 0.6 * amp / limit)


def score_trend_gap(white: pd.Series, yellow: pd.Series) -> pd.Series:
    """白线相对黄线的强度。贴线(0%)→0.5，白高于黄5%→1，白低于黄5%→0。"""
    gap = (white - yellow) / yellow.replace(0, np.nan)
    return _clip01(0.5 + gap * 10.0)


def score_dif(dif: pd.Series, close: pd.Series) -> pd.Series:
    """MACD DIF 归一到价格（跨股票可比）。DIF/价=-1%→0，0→0.6，+1.5%→1。"""
    dif_pct = dif / close.replace(0, np.nan)
    return _clip01(0.6 + dif_pct * 40.0)


def score_vol_shrink(volume: pd.Series, window: int = 40) -> pd.Series:
    """缩量程度。量/MA40=0.25→1（缩至1/4），=1→0.4，≥1.8→0。"""
    ratio = volume / volume.rolling(window).mean().replace(0, np.nan)
    return _clip01(1.0 - 0.5 * (ratio - 0.25) / 0.75)


def score_yangyin_ratio(open_: pd.Series, close: pd.Series, volume: pd.Series,
                        window: int = 28) -> pd.Series:
    """红肥绿瘦：28日真阳量/真阴量。1.0→0.3，1.65→0.6，≥3→1。"""
    prev_close = close.shift(1)
    real_yang = (close > open_) & ~(close < prev_close)
    real_yin = (close < open_) & ~(close > prev_close)
    vol_yang = (volume * real_yang).rolling(window).sum()
    vol_yin = (volume * real_yin).rolling(window).sum().replace(0, np.nan)
    ratio = vol_yang / vol_yin
    return _clip01(0.3 + (ratio - 1.0) / 4.0 * 1.4)


def score_surge_count(open_: pd.Series, close: pd.Series, volume: pd.Series,
                      surge_ratio: float = 1.85, window: int = 28) -> pd.Series:
    """爆量阳次数（28日）。0次→0，2次→0.6，≥4次→1。"""
    avg40 = volume.rolling(40).mean()
    plry = (volume > surge_ratio * volume.shift(1)) & (close > open_) & (volume > avg40)
    cnt = plry.rolling(window).sum()
    return _clip01(cnt * 0.3 - 0.0)


def score_ql_position(close: pd.Series) -> pd.Series:
    """价格相对QL线（0.4*MA20+0.3*MA60+0.2*MA120+0.1*MA250）。
    =0.99QL→0.5，高5%→0.85，低10%→0。"""
    ql = (0.4 * close.rolling(20).mean() + 0.3 * close.rolling(60).mean()
          + 0.2 * close.rolling(120).mean() + 0.1 * close.rolling(250).mean())
    rel = close / ql.replace(0, np.nan) - 0.99
    return _clip01(0.5 + rel * 7.0)


def score_bowl(close: pd.Series, white: pd.Series, yellow: pd.Series) -> pd.Series:
    """掉进碗里（增强因子，docs/trading_system.md §5）：
    股价处于白线之下、黄线之上 = 1，否则 0。"""
    in_bowl = (close < white) & (close > yellow)
    return in_bowl.astype(float)


def score_washout_recover(data: pd.DataFrame, low_th: float = 30.0,
                          high_th: float = 80.0, lookback: int = 3) -> pd.Series:
    """单针下三十回收（洗盘短线短期线近期下插≤30且当前≥80）。"""
    from alphapulse.factors.zhixing_washout import compute_lines
    short = compute_lines(data)["short"]
    recent_low = short.rolling(lookback).min()
    sig = (recent_low <= low_th) & (short >= high_th)
    return sig.astype(float)


def compute_sub_scores(data: pd.DataFrame) -> dict[str, float]:
    """对单只股票计算所有子分数的最新值。

    Returns:
        dict: 子分数名 -> 最新值（0-1）；历史不足时返回空 dict
    """
    if len(data) < 120:
        return {}

    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)
    prev_close = close.shift(1)

    pct = (close - prev_close) / prev_close.replace(0, np.nan) * 100
    amp = (high - low) / prev_close.replace(0, np.nan) * 100
    j = compute_kdj_j(high, low, close)
    white = compute_short_trend(close)
    yellow = compute_bull_bear_line(close)
    dif = compute_macd_dif(close)

    scores = {
        "j_low": score_j_low(j),
        "pct_calm": score_pct_calm(pct),
        "amplitude": score_amplitude(amp),
        "trend_gap": score_trend_gap(white, yellow),
        "dif": score_dif(dif, close),
        "vol_shrink": score_vol_shrink(volume),
        "yangyin": score_yangyin_ratio(open_, close, volume),
        "surge": score_surge_count(open_, close, volume),
        "ql_pos": score_ql_position(close),
        "bowl": score_bowl(close, white, yellow),
        "washout_recover": score_washout_recover(data),
    }
    out = {}
    for name, s in scores.items():
        v = s.iloc[-1]
        out[name] = round(float(v), 4) if pd.notna(v) else 0.0
    return out
