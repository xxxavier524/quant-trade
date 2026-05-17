"""B1增强选股策略 — 融合B1选股公式 + 知行超短 + 量能B1。

B1选股类型（三来源融合）：
  B1公式：    涨幅±3% + 振幅<9% + J<13 + DIF>-0.1 + 趋势>多空 + 市值>10亿
  知行超短：  趋势线>多空线 + 收盘>多空线 + 洗盘中长期>65 + DIF>0 + 砖型图超短
  量能B1：    阳阴量比 + 爆量阳 + 缩倍量 + 市值≥40亿 + 价格>QL线

输出统一信号DataFrame。
"""

import pandas as pd
from alphapulse.factors import b1_formula, zhixing_trend, zhixing_washout, brick_ultra, volume_b1


def generate_signals(data: pd.DataFrame, symbol: str = "", mode: str = "all", **params) -> pd.DataFrame:
    """B1选股信号生成。

    Args:
        data: 日线OHLCV
        symbol: 股票代码
        mode: "b1_formula" | "zhixing" | "volume_b1" | "all"（三源AND）
    """
    signals = []

    def _check(name, cond):
        if cond.any():
            for dt in data.index[cond]:
                signals.append({
                    "symbol": symbol, "date": dt, "signal": 1,
                    "strategy": f"B1_{name}",
                    "factor_snapshot": {"close": float(data.loc[dt, "close"])},
                })

    if mode in ("b1_formula", "all"):
        c = b1_formula.compute(data)
        _check("FORMULA", c)

    if mode in ("zhixing", "all"):
        c_t = zhixing_trend.compute(data)
        c_w = zhixing_washout.compute(data)
        c_b = brick_ultra.compute(data)
        c_z = c_t & c_w & c_b
        _check("ZHIXING", c_z)

    if mode in ("volume_b1", "all"):
        c = volume_b1.compute(data)
        _check("VOLUME", c)

    if not signals:
        return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])
    return pd.DataFrame(signals).set_index("date").sort_index()
