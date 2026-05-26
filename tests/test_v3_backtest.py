import pandas as pd
import pytest
from alphapulse.backtest.bt_storage import init_db, insert_signal, insert_daily_track, insert_exit, query_strategy_stats, get_conn

def _clean_db():
    """Remove all rows from the test DB to ensure idempotent tests."""
    init_db()
    conn = get_conn()
    conn.execute("DELETE FROM daily_track")
    conn.execute("DELETE FROM exits")
    conn.execute("DELETE FROM signals")
    conn.commit()
    conn.close()

def test_init_db():
    init_db()
    # should not raise

def test_insert_and_query():
    _clean_db()
    sid = insert_signal("000001", "平安银行", "B1B2", "2026-01-01", "B1", 10.0, "银行", "震荡偏多", 75.0, "A")
    assert sid > 0
    insert_daily_track(sid, 1, "2026-01-02", 10.5, 10.8, 10.1, 5.0, -1.0)
    insert_exit(sid, "2026-01-10", 12.0, "take_profit", 20.0, 7)
    df = query_strategy_stats("B1B2")
    assert len(df) == 1
    assert df.iloc[0]["total_return"] == 20.0
