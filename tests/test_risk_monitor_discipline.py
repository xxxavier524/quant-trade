"""risk_monitor 持仓纪律检查（Z哥应对层集成）测试。"""

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from risk_monitor import check_holding_discipline, load_positions  # noqa: E402
from alphapulse.utils.top_tax import top_tax_cut  # noqa: E402

DATA_DIR = PROJECT_ROOT / "temp_data"


@pytest.fixture
def positions(tmp_path):
    p = tmp_path / "positions.csv"
    p.write_text("symbol,shares,cost_price,entry_date\n"
                 "603618,1000,8.0,2025-10-22\n"
                 "002475,100,40.0,2025-11-01\n", encoding="utf-8")
    return load_positions(str(p))


def test_symbol_leading_zeros_preserved(positions):
    assert "002475" in positions["symbol"].tolist()


def test_discipline_alert_structure(positions):
    alerts = check_holding_discipline(positions, str(DATA_DIR))
    assert isinstance(alerts, list)
    for a in alerts:
        assert set(a) == {"symbol", "level", "rule", "message"}
        assert a["level"] in ("CRITICAL", "WARN", "INFO")


def test_every_holding_gets_sellscore_opinion(positions):
    """每只有数据的持仓必产生一条防卖飞评分意见（持有/减半/离场其一）。"""
    alerts = check_holding_discipline(positions, str(DATA_DIR))
    scored = {a["symbol"] for a in alerts if a["rule"].startswith("防卖飞评分")}
    assert {"603618", "002475"} <= scored


def test_top_tax_capped():
    assert top_tax_cut(3.0) == 0.5           # 极端浮盈封顶50%
    assert top_tax_cut(0.4) == pytest.approx(0.12)


def test_missing_data_symbol_skipped(tmp_path):
    p = tmp_path / "pos.csv"
    p.write_text("symbol,shares,cost_price\n999999,100,10.0\n", encoding="utf-8")
    alerts = check_holding_discipline(load_positions(str(p)), str(DATA_DIR))
    assert alerts == []                       # 无数据→静默跳过，不抛异常
