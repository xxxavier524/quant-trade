"""3/4阴量线因子（docs/trading_system.md §3 多头因子，用户清单中缺失项）。

定义（量学口径，保守默认，参数可调）：
- 前日为放量阳线（真阳，量 > MA5量）
- 当日为阴线（C < O）
- 当日量 ≤ ratio × 前日量（默认 3/4）

含义：拉升后的阴线缩量到前日阳量的3/4以内 = 卖压不足、主力未出货，
是回调中的多头确认信号。

模糊量处理：ratio 默认 0.75；"放量阳"以量>MA5为保守判定，
Phase 3 网格扫描后与用户复盘定值。
"""

import pandas as pd


def compute(
    data: pd.DataFrame,
    ratio: float = 0.75,
    vol_ma_window: int = 5,
) -> pd.Series:
    """3/4阴量线：True = 当日满足缩量阴确认。

    Args:
        data: 含 open/close/volume
        ratio: 阴量/前日阳量上限（默认3/4）
        vol_ma_window: 前日放量判定的均量窗口

    Returns:
        pd.Series[bool]
    """
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)
    prev_close = close.shift(1)

    # 前日：真阳线且放量
    prev_yang = (close.shift(1) > open_.shift(1)) & ~(close.shift(1) < close.shift(2))
    prev_heavy = volume.shift(1) > volume.rolling(vol_ma_window).mean().shift(1)

    # 当日：阴线且量缩到前日的 ratio 以内
    today_yin = close < open_
    vol_shrunk = volume <= ratio * volume.shift(1)

    result = prev_yang & prev_heavy & today_yin & vol_shrunk
    return result.fillna(False).astype(bool)


def compute_detail(data: pd.DataFrame, **params) -> pd.DataFrame:
    """明细：阴量比例与各子条件。"""
    ratio = params.get("ratio", 0.75)
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)

    vol_ratio = volume / volume.shift(1)
    return pd.DataFrame({
        "vol_ratio": vol_ratio.round(3),
        "today_yin": close < open_,
        "ratio_ok": vol_ratio <= ratio,
        "signal": compute(data, **params),
    }, index=data.index)
