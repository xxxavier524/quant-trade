"""P1 度量诚实性单测（signal_tracker）。

核心：证明"曾触及+5%"口径会把先涨后崩的票判成永久赢家，而新的固定可成交退出
（持有5日/破-5%止损、扣费）口径正确判其为亏损；success_stats 同时给出两口径。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.tracking import signal_tracker as tk  # noqa: E402


# ---- 纯函数 realized_return ----

def test_hold_to_horizon_up():
    val, day = tk.realized_return(10.0, [10.1, 10.2, 10.3, 10.4, 10.8])  # +8% @day5，无止损
    assert day == 5
    assert abs(val - (8.0 - tk.ROUND_TRIP_COST_PCT)) < 1e-6


def test_touch_then_crash_is_loss():
    # 触及+6%(day2)后 day3 跌到 -10% 破止损 → 实盘判亏，出场 day3（关键诚实性）
    val, day = tk.realized_return(10.0, [10.3, 10.6, 9.0, 9.2, 9.5])
    assert day == 3
    assert val < 0


def test_stop_on_first_day():
    val, day = tk.realized_return(10.0, [9.4])  # -6% ≤ -5%
    assert day == 1 and val < 0


def test_not_enough_data_returns_none():
    assert tk.realized_return(10.0, [10.1, 10.2]) is None  # <5日且未止损


def test_zero_base_guard():
    assert tk.realized_return(0.0, [1, 2, 3, 4, 5]) is None


# ---- 集成：touch_rate 高估 vs realized 诚实 ----

def _insert_signal(conn, symbol, status, closes):
    conn.execute(
        "INSERT INTO signals(date,symbol,name,score,strict,sector,close,sub_scores,"
        "strategies,family,status) VALUES('2026-07-01',?,?,90,1,'x',10.0,'{}','B1','基本面法',?)",
        (symbol, symbol, status))
    sid = conn.execute("SELECT id FROM signals WHERE symbol=?", (symbol,)).fetchone()[0]
    for i, c in enumerate(closes, 1):
        conn.execute("INSERT INTO performance VALUES(?,?,?,?,?)", (sid, i, f"d{i}", c, 0.0))
    return sid


def test_touch_vs_realized_integration(tmp_path, monkeypatch):
    monkeypatch.setattr(tk, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tk, "REVIEWS_MD", tmp_path / "reviews.md")
    conn = tk._conn()
    _insert_signal(conn, "000001", "success", [10.3, 10.6, 9.0, 9.2, 9.5])   # 触及后崩 → 实盘亏
    _insert_signal(conn, "000002", "success", [10.2, 10.4, 10.6, 10.8, 11.0])  # 稳涨 → 实盘赢
    conn.commit()
    conn.close()

    assert tk.update_realized() == 2
    s = tk.success_stats(window_days=3650)["基本面法"]
    assert s["touch_rate"] == 100.0     # 旧口径：两只都算"成功"
    assert s["n_realized"] == 2
    assert s["realized_win"] == 50.0    # 诚实口径：一亏一赢
    assert s["realized_mean"] < 5.0     # 均值远低于旧口径暗示的水平


def test_distill_failures_logs_losers(tmp_path, monkeypatch):
    md = tmp_path / "reviews.md"
    monkeypatch.setattr(tk, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tk, "REVIEWS_MD", md)
    conn = tk._conn()
    _insert_signal(conn, "000003", "stopped_drop", [9.4, 9.0, 8.5, 8.0, 7.5])
    conn.commit()
    conn.close()
    tk.update_realized()
    out = tk.distill_failures()
    assert len(out) == 1 and out[0]["symbol"] == "000003"
    assert md.exists() and "stopped_drop" in md.read_text()
    # 幂等：再跑不重复写
    assert tk.distill_failures() == []


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
