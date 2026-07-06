"""洗盘段量化模板（路线图#6，Sequoia 涨停洗盘三段式本地化）。

母题：主力行为确认（爆量阳）→ 洗盘段（缩量、不破锚定位）→ 再确认（阳线）。
= 用户"缩量阴/3/4阴量线"+"不破锚"的通用化，统一服务 B3 锁仓与单针下三十。

- washout_ok(df, anchor_idx, ...) : 标量，锚点后洗盘段是否有效（spec 签名）
- compute(df, ...)                 : 向量化，surge→washout→reconfirm 完成日信号
全因果：锚点在过去，洗盘段只用锚后≤t 的数据。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def washout_ok(df: pd.DataFrame, anchor_idx: int, max_vol_ratio: float = 0.5,
               anchor_price_col: str = "open", min_days: int = 1,
               max_days: int = 10) -> bool:
    """锚定 anchor_idx 后的洗盘段是否有效。

    有效 = 锚后 [1, max_days] 里存在长度≥min_days 的连续洗盘段，段内每日：
      volume < anchor日volume × max_vol_ratio（缩量）
      且 low > df[anchor_price_col].iloc[anchor_idx]（不破锚定位）
    段一旦被"放量或破锚"打断即结束。返回是否达到 min_days。
    """
    n = len(df)
    if anchor_idx < 0 or anchor_idx >= n - 1:
        return False
    anchor_vol = float(df["volume"].iloc[anchor_idx])
    anchor_price = float(df[anchor_price_col].iloc[anchor_idx])
    vol = df["volume"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)

    run = 0
    end = min(anchor_idx + max_days, n - 1)
    for j in range(anchor_idx + 1, end + 1):
        if vol[j] < max_vol_ratio * anchor_vol and low[j] > anchor_price:
            run += 1
            if run >= min_days:
                return True
        else:
            break
    return False


def compute(data: pd.DataFrame, max_vol_ratio: float = 0.5,
            surge_vol_mult: float = 2.0, vol_ma: int = 5,
            min_washout: int = 1, max_wait: int = 10,
            anchor_price_col: str = "open") -> pd.Series:
    """洗盘再确认信号（向量化，全因果）。

    三段式：
      1. 锚 = 爆量阳：volume > surge_vol_mult × MA(volume, vol_ma) 且 close > open
      2. 洗盘段：锚后连续 ≥min_washout 日 缩量(vol<max_vol_ratio×锚量) 且 不破锚(low>锚open)
      3. 再确认：洗盘段后首个阳线(close>open)日 = True（该日入场）

    Returns:
        pd.Series[bool]
    """
    n = len(data)
    close = data["close"].to_numpy(dtype=float)
    open_ = data["open"].to_numpy(dtype=float)
    low = data["low"].to_numpy(dtype=float)
    vol = data["volume"].to_numpy(dtype=float)
    anchor_price = data[anchor_price_col].to_numpy(dtype=float)

    vol_ma_arr = pd.Series(vol).rolling(vol_ma).mean().to_numpy()
    surge = (vol > surge_vol_mult * vol_ma_arr) & (close > open_)
    yang = close > open_

    out = np.zeros(n, dtype=bool)
    # 对每个爆量阳锚点，向后找"洗盘达标后首个阳线"（因果：只看锚后）
    anchor_idxs = np.flatnonzero(surge)
    for a in anchor_idxs:
        a_vol = vol[a]
        a_price = anchor_price[a]
        run = 0
        washed = False
        end = min(a + max_wait, n - 1)
        for j in range(a + 1, end + 1):
            calm = vol[j] < max_vol_ratio * a_vol and low[j] > a_price
            if not washed:
                if calm:
                    run += 1
                    if run >= min_washout:
                        washed = True
                elif not (low[j] > a_price):   # 破锚 → 本锚作废
                    break
                else:
                    run = 0                    # 放量但未破锚 → 洗盘中断，重计
            else:
                # 洗盘达标后：首个阳线且不破锚 = 再确认
                if low[j] <= a_price:
                    break
                if yang[j]:
                    out[j] = True
                    break
    return pd.Series(out, index=data.index)


def compute_detail(data: pd.DataFrame, **params) -> pd.DataFrame:
    """明细：信号 + 爆量阳锚标记 + 缩量比。"""
    surge_vol_mult = params.get("surge_vol_mult", 2.0)
    vol_ma = params.get("vol_ma", 5)
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    vol = data["volume"].astype(float)
    vma = vol.rolling(vol_ma).mean()
    return pd.DataFrame({
        "surge_anchor": ((vol > surge_vol_mult * vma) & (close > open_)),
        "vol_vs_ma": (vol / vma).round(3),
        "signal": compute(data, **params),
    }, index=data.index)
