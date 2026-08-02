"""v5 P0-2/P0-3 对抗性检查：口径统一 + 闸门留痕。

- P0-2：夜间报告/晚间复盘主口径必须是追踪库 realized（实盘已实现收益），
  "曾触及+5%"只作对照，绝不能再当成功率主数字。
- P0-3：硬闸门关闭必须写 gate_closed_<date>.json 标记，流水线与夜场报告
  能读到并提示，杜绝"空头区间静默空转、last_run.json 记 ok:true"。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import daily_auto_run as dar  # noqa: E402
import eod_pipeline as ep  # noqa: E402
import daily_screener as ds  # noqa: E402


def test_gate_closed_writes_marker(monkeypatch, tmp_path):
    """闸门关闭 → daily_screener 返回空表且落盘 gate_closed_<date>.json。"""
    monkeypatch.setattr(ds, "REPORTS_DIR", tmp_path)

    def fake_gates(end_date):
        return False, ["零轴门:DIF=-60<0 空头区间", "大盘S1门:近5日无大盘S1"]

    import alphapulse.market.hard_gates as hg
    monkeypatch.setattr(hg, "evaluate_gates", fake_gates)

    out = ds.run(date="2026-07-01", top_n=10, data_dir=tmp_path, use_gates=True)
    assert out.empty, "闸门关闭时不应出票"
    marker = tmp_path / "gate_closed_2026-07-01.json"
    assert marker.exists(), "闸门关闭必须留痕"
    info = json.loads(marker.read_text(encoding="utf-8"))
    assert info["date"] == "2026-07-01"
    assert any("零轴门" in m for m in info["gates"])


def test_gate_open_removes_stale_marker(monkeypatch, tmp_path):
    """闸门重开 → 当日过期标记被清除（夜间报告不会引用过期状态）。"""
    monkeypatch.setattr(ds, "REPORTS_DIR", tmp_path)
    marker = tmp_path / "gate_closed_2026-07-01.json"
    marker.write_text(json.dumps({"date": "2026-07-01", "gates": ["旧"]}))

    # 闸门放行后 run() 会继续走全市场加载；用空目录 + 打桩 load_stock 快速短路。
    monkeypatch.setattr(ds, "load_stock", lambda *a, **k: None)

    def fake_gates(end_date):
        return True, ["零轴门:DIF>0 多头区间"]

    import alphapulse.market.hard_gates as hg
    monkeypatch.setattr(hg, "evaluate_gates", fake_gates)

    # 大盘/板块/排序依赖真实数据，这里只验证到标记清除为止：直接测 run 前置逻辑
    # 不可行（run 是全流程），改为验证 evaluate_gates 放行时调用方清除逻辑——
    # 该清除逻辑在 run() 内，故此处用最小桩数据走通空路径。
    import pandas as pd
    fake_df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=130, freq="B").astype(str),
        "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
        "volume": 1e6, "pct_change": 0.0, "amplitude": 1.0,
        "turn": 1.0, "turnover": 1.0, "market_cap": 2e9,
    })
    monkeypatch.setattr(ds, "load_stock", lambda *a, **k: fake_df)

    # 让大盘评分/板块/排序也短路，直接返回空 top → 函数正常返回
    monkeypatch.setattr(ds, "compute_market_score", lambda **k: {"level": "震荡", "score": 50, "advice": ""})
    monkeypatch.setattr(ds, "rank_sectors", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(ds, "symbol_sector_map", lambda: {})
    monkeypatch.setattr(ds, "build_stock_row", lambda *a, **k: None)
    monkeypatch.setattr(ds, "rank_all", lambda *a, **k: pd.DataFrame())

    out = ds.run(date="2026-07-01", top_n=10, data_dir=tmp_path, use_gates=True)
    assert out.empty
    assert not marker.exists(), "闸门放行后应清除当日过期标记"


def test_nightly_summary_uses_realized_and_gate_line(monkeypatch, tmp_path):
    """夜场报告主口径 = 已实现胜率；闸门关闭时提示"不开新仓"。"""
    (tmp_path / "gate_closed_2026-07-01.json").write_text(
        json.dumps({"date": "2026-07-01", "gates": ["零轴门:DIF<0 空头区间"]}),
        encoding="utf-8")
    text = dar.build_nightly_summary(reports_dir=tmp_path)
    assert "已实现胜率" in text
    assert "硬闸门关闭中" in text
    assert "不开新仓" in text


def test_read_gate_marker(tmp_path):
    assert ep._read_gate_marker("2026-07-02") == (False, [])
    marker = tmp_path / "gate_closed_2026-07-01.json"
    # 直接把 REPORTS_DIR 指到临时目录验证读取逻辑
    marker.write_text(json.dumps({"date": "2026-07-01", "gates": ["x", "y"]}),
                      encoding="utf-8")
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(ep, "REPORTS_DIR", tmp_path)
    try:
        gated, msgs = ep._read_gate_marker("2026-07-01")
        assert gated and msgs == ["x", "y"]
    finally:
        monkeypatch.undo()
