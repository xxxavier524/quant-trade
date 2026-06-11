"""vibe-trading Alpha Zoo 桥接 — 复用其 452 个面板因子（alpha101/gtja191/qlib158）。

vibe-trading 项目（~/cc/vibe-trading）的 zoo 因子为面板式：
compute(panel: dict[str, DataFrame(date×symbol)]) -> DataFrame(date×symbol)
其中 rank 等算子是截面（跨股票）操作——与本项目单股 Series 因子互补。

本模块提供：
- build_panel(stock_frames): 单股日线dict → 面板dict
- compute_alpha(alpha_id, panel): 按ID计算任意zoo因子
- CURATED_GTJA: 精选高IC短周期alpha清单（量价类，适配A股短线体系）

验证: Python 3.14 + pandas 2.x 桥接冒烟通过（2026-06-11）。
"""

import importlib
import sys
from pathlib import Path

import pandas as pd

VIBE_AGENT_PATH = Path("/Users/qiushixuan/cc/vibe-trading/agent")

# 精选GTJA短周期量价alpha（研报正向IC、无需板块/财务数据）
CURATED_GTJA = [1, 2, 3, 14, 18, 20, 34, 42, 46, 53, 65, 70, 88, 93, 95, 96, 106, 126, 139, 150]


def _ensure_path() -> bool:
    if not VIBE_AGENT_PATH.exists():
        return False
    p = str(VIBE_AGENT_PATH)
    if p not in sys.path:
        sys.path.insert(0, p)
    return True


def build_panel(stock_frames: dict[str, pd.DataFrame],
                lookback: int = 250) -> dict[str, pd.DataFrame]:
    """单股日线 dict → 面板 dict（date×symbol）。"""
    cols = ["open", "high", "low", "close", "volume"]
    series = {c: {} for c in cols}
    for sym, df in stock_frames.items():
        tail = df.tail(lookback)
        idx = pd.to_datetime(tail["date"]) if "date" in tail.columns else tail.index
        for c in cols:
            if c in tail.columns:
                series[c][sym] = pd.Series(tail[c].astype(float).values, index=idx)
    panel = {c: pd.DataFrame(series[c]) for c in cols}
    # vwap 近似（部分alpha需要）
    if "amount" in next(iter(stock_frames.values())).columns:
        amt = {}
        for sym, df in stock_frames.items():
            tail = df.tail(lookback)
            idx = pd.to_datetime(tail["date"]) if "date" in tail.columns else tail.index
            amt[sym] = pd.Series(tail["amount"].astype(float).values, index=idx)
        amount = pd.DataFrame(amt)
        vol = panel["volume"].replace(0, pd.NA)
        panel["vwap"] = (amount / vol).astype(float)
    return panel


def compute_alpha(alpha_id: str, panel: dict) -> pd.DataFrame | None:
    """计算zoo因子。alpha_id 如 'gtja191_001' / 'alpha101_005' / 'qlib158_xxx'。"""
    if not _ensure_path():
        return None
    family, num = alpha_id.rsplit("_", 1)
    mod = importlib.import_module(f"src.factors.zoo.{family}.alpha_{num}")
    return mod.compute(panel)


def curated_alpha_frame(stock_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """精选GTJA alpha 的最新截面值 → DataFrame[symbol, gtja_001, ...]。

    供评分/IC验证使用；失败的alpha静默跳过。
    """
    if not _ensure_path():
        return pd.DataFrame()
    panel = build_panel(stock_frames)
    out = {}
    for n in CURATED_GTJA:
        aid = f"gtja191_{n:03d}"
        try:
            df = compute_alpha(aid, panel)
            if df is not None and len(df):
                out[f"gtja_{n:03d}"] = df.iloc[-1]
        except Exception:
            continue
    if not out:
        return pd.DataFrame()
    result = pd.DataFrame(out)
    result.index.name = "symbol"
    return result.reset_index()
