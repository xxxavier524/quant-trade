"""黄金案例回归测试 — 公式翻译的正确性之锚。

任何对 b1_formula / volume_b1 / zhixing_trend / zhixing_washout / brick_ultra
的改动都必须通过本测试：案例股在其时间窗口内必须能被对应公式选中。

- golden_20260517.csv（33只）：B1选股公式 + 量能B1 的多日案例集
- golden_2604.csv（14只）：2026年4月前后的超短案例（B1∪量能B1∪知行超短）

数据依赖外接硬盘日线CSV；未挂载时跳过（CI环境不阻塞）。
基准（2026-06-11 测定）：B1案例 31/32=96.9%，超短案例 14/14=100%。
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402

GOLDEN_DIR = Path(__file__).parent

pytestmark = pytest.mark.skipif(
    not Path(DATA_DIR).exists(),
    reason="数据目录未挂载（外接硬盘）",
)


def _hit_rate(golden_csv: str, start: str, end: str, formula: str) -> tuple[int, int, list[str]]:
    """返回 (命中数, 有数据股票数, 漏选清单)。"""
    from replay_screen import load_stock, compute_signal_frame

    golden = pd.read_csv(GOLDEN_DIR / golden_csv, dtype={"symbol": str})
    syms = golden["symbol"].str.zfill(6).tolist()
    names = dict(zip(golden["symbol"].str.zfill(6), golden["name"]))

    n_data, n_hit, missed = 0, 0, []
    for sym in syms:
        df = load_stock(Path(DATA_DIR) / f"{sym}.csv", end)
        if df is None:
            continue
        n_data += 1
        frame = compute_signal_frame(df, formula)
        in_range = (df["date"] >= start) & (df["date"] <= end)
        if bool((frame["hit"] & in_range).any()):
            n_hit += 1
        else:
            missed.append(f"{sym}{names.get(sym, '')}")
    return n_hit, n_data, missed


def test_b1_cases_hit_rate():
    """33只B1案例：2025-12 ~ 2026-05-15 窗口内 B1∪量能B1 命中率 ≥ 90%。"""
    n_hit, n_data, missed = _hit_rate(
        "golden_20260517.csv", "2025-12-01", "2026-05-15", "union")
    rate = n_hit / n_data
    assert rate >= 0.90, f"命中率 {n_hit}/{n_data}={rate:.1%} < 90%，漏选: {missed}"


def test_ultra_cases_hit_rate():
    """14只超短案例：2026-01 ~ 2026-05-15 窗口内三公式并集命中率 ≥ 90%。"""
    n_hit, n_data, missed = _hit_rate(
        "golden_2604.csv", "2026-01-01", "2026-05-15", "all")
    rate = n_hit / n_data
    assert rate >= 0.90, f"命中率 {n_hit}/{n_data}={rate:.1%} < 90%，漏选: {missed}"


def test_known_signal_spotchecks():
    """锁定若干已人工核实的（股票, 信号日, 公式）组合，防止公式漂移。"""
    from replay_screen import load_stock, compute_signal_frame

    spotchecks = [
        ("605318", "2026-05-15", "b1"),        # 法狮龙
        ("688799", "2026-04-15", "volume_b1"),  # 华纳药厂
        ("002475", "2026-04-20", "zhixing"),   # 立讯精密（超短）
        ("000547", "2026-02-11", "b1"),        # 航天发展（turn列修复）
    ]
    for sym, date, col in spotchecks:
        df = load_stock(Path(DATA_DIR) / f"{sym}.csv", date)
        assert df is not None, f"{sym} 无数据"
        frame = compute_signal_frame(df, "all")
        row = frame.iloc[-1]
        assert df.iloc[-1]["date"] == date, f"{sym} 当日无交易"
        assert bool(row[col]), f"{sym} @ {date} 应触发 {col} 信号"
