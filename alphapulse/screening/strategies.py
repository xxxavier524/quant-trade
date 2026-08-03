"""纯选股系统策略注册表（v5，2026-08-02）。

只登记"选股信号生成器"（输出 signal==1 的 DataFrame，索引=源帧行标签），
不含任何交易模拟。全部策略共用同一评价口径（alphapulse.screening.evaluator）。

说明：B1_B2_B3 / BRICK_THREE_TYPES 默认套用 config/best_params.json 中
walk-forward 稳健参数（screen_optimize 写入）；其余用策略自身默认参数。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

from alphapulse.strategies import (  # noqa: E402
    b1_formula_strategy,
    b1_b2_b3_strategy,
    brick_three_types,
    needle_washout,
    brick_ultra_strategy,
    needle,
    b1_enhanced,
    zg_b1_brick,
)
from alphapulse.factors import volume_b1, zhixing_trend  # noqa: E402


def _best_params(name: str) -> dict:
    try:
        cfg = json.loads((PROJECT_ROOT / "config" / "best_params.json").read_text())
        return {k: v for k, v in cfg.get(name, {}).items()
                if not k.startswith("_")}
    except Exception:
        return {}


def _series_frame(compute_fn, data: pd.DataFrame, **kw) -> pd.DataFrame:
    """把返回 bool Series 的因子/公式包装成统一信号帧（索引=输入行标签）。"""
    s = compute_fn(data, **kw)
    return pd.DataFrame({"signal": s.fillna(False).astype(int)}, index=data.index)


# (generate_signals, 默认参数覆盖)
SCREENING_STRATEGIES: dict[str, tuple] = {
    "B1_FORMULA": (b1_formula_strategy.generate_signals, {}),
    "B1_B2_B3": (b1_b2_b3_strategy.generate_signals, _best_params("B1_B2_B3")),
    "BRICK_THREE_TYPES": (brick_three_types.generate_signals,
                          _best_params("BRICK_THREE_TYPES")),
    "NEEDLE_WASHOUT": (needle_washout.generate_signals, {}),
    "BRICK_ULTRA": (brick_ultra_strategy.generate_signals, {}),
    "NEEDLE": (needle.generate_signals, {}),
    "B1_ENHANCED": (b1_enhanced.generate_signals, {"mode": "all"}),
    "ZG_B1_BRICK": (zg_b1_brick.generate_signals, {}),
    "VOLUME_B1": (lambda df, **kw: _series_frame(volume_b1.compute, df, **kw), {}),
    "ZHIXING_ULTRA": (lambda df, **kw: _series_frame(
        zhixing_trend.compute_ultra, df, **kw), {}),
}


def run_strategy(name: str, data: pd.DataFrame, subtype: str | None = None,
                 **overrides) -> pd.DataFrame:
    """运行指定选股策略，返回统一信号帧（空帧安全）。

    subtype: 可选子类型过滤（B1_B2_B3 的 signal_type B1/B2/B3，
    BRICK_THREE_TYPES 的 brick_type）。用于验证"分级确认"是否提升命中率。
    """
    if name not in SCREENING_STRATEGIES:
        raise KeyError(f"未知选股策略: {name}，可选: {list(SCREENING_STRATEGIES)}")
    fn, defaults = SCREENING_STRATEGIES[name]
    params = {**defaults, **overrides}
    try:
        frame = fn(data, symbol="", **params)
    except TypeError as e:
        # 部分生成器不接受 symbol/params（如 _series_frame 包装）；
        # 只在"未知关键字"时报错重试，避免把策略内部 TypeError 误吞。
        if "symbol" not in str(e) and "unexpected keyword" not in str(e) \
                and "argument" not in str(e):
            raise
        frame = fn(data, **params)
    if frame is None or len(frame.columns) == 0:
        # 注意：有列的空帧（0 行）必须保留原 schema（signal_type/brick_type 等），
        # 否则子类型过滤会丢列（2026-08-03 修复）
        cols = ["symbol", "date", "signal", "strategy", "factor_snapshot"]
        return pd.DataFrame(columns=cols)
    if "signal" not in frame.columns:
        frame = frame.assign(signal=1)
    if subtype:
        col = ("signal_type" if "signal_type" in frame.columns
               else "brick_type" if "brick_type" in frame.columns else None)
        if col is None:
            raise ValueError(f"{name} 无子类型列，无法过滤 subtype={subtype}")
        frame = frame[frame[col] == subtype]
    return frame
