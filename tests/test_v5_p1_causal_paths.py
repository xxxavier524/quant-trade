"""v5 P1 收尾：因果化路径冒烟（2026-08-02）。

交易侧（run_backtest / risk_monitor / export_qmt / playbook 等）已整体移除，
本文件只保留与选股信号相关的因果化验证。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_key_support_causal_smoke():
    from alphapulse.factors.knowledge_points import compute_key_support
    try:
        from test_n_struct_causal import _make_n_shape
    except ModuleNotFoundError:
        from tests.test_n_struct_causal import _make_n_shape
    data = _make_n_shape()
    out = compute_key_support(data)
    assert set(out.columns) == {"n_pattern_support", "range_support", "sb1_support"}
    assert out["n_pattern_support"].notna().any()


def test_has_n_structure_causal_smoke():
    from alphapulse.utils.filters import has_n_structure
    try:
        from test_n_struct_causal import _make_n_shape
    except ModuleNotFoundError:
        from tests.test_n_struct_causal import _make_n_shape
    data = _make_n_shape()
    assert isinstance(has_n_structure(data, lookback=20), bool)
