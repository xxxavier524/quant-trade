"""Alpha158 因子库（qlib Alpha158DL 原版表达式，经 expr_engine 求值）。

组成：KBAR 9 + 价格比值 4 + 滚动算子 29 × 窗口{5,10,20,30,60} = 158。
全部为单股时序因子（多数以 /close 归一为比值，天然可跨股票比较）。

用法：
    from alphapulse.factors.alpha158 import ALPHA158, compute_alpha158
    frame = compute_alpha158(df)   # DataFrame(158列)，索引对齐 df
"""

from __future__ import annotations

import pandas as pd

from alphapulse.factors import expr_engine

WINDOWS = (5, 10, 20, 30, 60)

_KBAR = {
    "KMID": "($close-$open)/$open",
    "KLEN": "($high-$low)/$open",
    "KMID2": "($close-$open)/($high-$low+1e-12)",
    "KUP": "($high-Greater($open, $close))/$open",
    "KUP2": "($high-Greater($open, $close))/($high-$low+1e-12)",
    "KLOW": "(Less($open, $close)-$low)/$open",
    "KLOW2": "(Less($open, $close)-$low)/($high-$low+1e-12)",
    "KSFT": "(2*$close-$high-$low)/$open",
    "KSFT2": "(2*$close-$high-$low)/($high-$low+1e-12)",
}

_PRICE = {
    "OPEN0": "$open/$close",
    "HIGH0": "$high/$close",
    "LOW0": "$low/$close",
    "VWAP0": "$vwap/$close",
}

# 滚动算子模板（d = 窗口），与 qlib Alpha158DL 逐条对应
_ROLLING = {
    "ROC": "Ref($close, {d})/$close",
    "MA": "Mean($close, {d})/$close",
    "STD": "Std($close, {d})/$close",
    "BETA": "Slope($close, {d})/$close",
    "RSQR": "Rsquare($close, {d})",
    "RESI": "Resi($close, {d})/$close",
    "MAX": "Max($high, {d})/$close",
    "MIN": "Min($low, {d})/$close",
    "QTLU": "Quantile($close, {d}, 0.8)/$close",
    "QTLD": "Quantile($close, {d}, 0.2)/$close",
    "RANK": "Rank($close, {d})",
    "RSV": "($close-Min($low, {d}))/(Max($high, {d})-Min($low, {d})+1e-12)",
    "IMAX": "IdxMax($high, {d})/{d}",
    "IMIN": "IdxMin($low, {d})/{d}",
    "IMXD": "(IdxMax($high, {d})-IdxMin($low, {d}))/{d}",
    "CORR": "Corr($close, Log($volume+1), {d})",
    "CORD": "Corr($close/Ref($close,1), Log($volume/Ref($volume, 1)+1), {d})",
    "CNTP": "Mean($close>Ref($close, 1), {d})",
    "CNTN": "Mean($close<Ref($close, 1), {d})",
    "CNTD": "Mean($close>Ref($close, 1), {d})-Mean($close<Ref($close, 1), {d})",
    "SUMP": ("Sum(Greater($close-Ref($close, 1), 0), {d})"
             "/(Sum(Abs($close-Ref($close, 1)), {d})+1e-12)"),
    "SUMN": ("Sum(Greater(Ref($close, 1)-$close, 0), {d})"
             "/(Sum(Abs($close-Ref($close, 1)), {d})+1e-12)"),
    "SUMD": ("(Sum(Greater($close-Ref($close, 1), 0), {d})"
             "-Sum(Greater(Ref($close, 1)-$close, 0), {d}))"
             "/(Sum(Abs($close-Ref($close, 1)), {d})+1e-12)"),
    "VMA": "Mean($volume, {d})/($volume+1e-12)",
    "VSTD": "Std($volume, {d})/($volume+1e-12)",
    "WVMA": ("Std(Abs($close/Ref($close, 1)-1)*$volume, {d})"
             "/(Mean(Abs($close/Ref($close, 1)-1)*$volume, {d})+1e-12)"),
    "VSUMP": ("Sum(Greater($volume-Ref($volume, 1), 0), {d})"
              "/(Sum(Abs($volume-Ref($volume, 1)), {d})+1e-12)"),
    "VSUMN": ("Sum(Greater(Ref($volume, 1)-$volume, 0), {d})"
              "/(Sum(Abs($volume-Ref($volume, 1)), {d})+1e-12)"),
    "VSUMD": ("(Sum(Greater($volume-Ref($volume, 1), 0), {d})"
              "-Sum(Greater(Ref($volume, 1)-$volume, 0), {d}))"
              "/(Sum(Abs($volume-Ref($volume, 1)), {d})+1e-12)"),
}


def _build() -> dict[str, str]:
    exprs = dict(_KBAR)
    exprs.update(_PRICE)
    for op, template in _ROLLING.items():
        for d in WINDOWS:
            exprs[f"{op}{d}"] = template.format(d=d)
    return exprs


ALPHA158: dict[str, str] = _build()
assert len(ALPHA158) == 158, f"Alpha158 因子数 {len(ALPHA158)} != 158"


def compute_alpha158(data: pd.DataFrame,
                     names: list[str] | None = None) -> pd.DataFrame:
    """对单股日线计算 Alpha158 因子帧。

    Args:
        data: OHLCV DataFrame（缺 amount 时 vwap 回退 (H+L+C)/3）
        names: 只算子集（默认全量158）

    Returns:
        DataFrame: 列=因子名，索引对齐 data
    """
    out = {}
    for name in (names or ALPHA158):
        out[name] = expr_engine.compute(data, ALPHA158[name])
    return pd.DataFrame(out, index=data.index)
