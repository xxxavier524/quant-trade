"""选股成功率跟踪测试 — 成功/止踪/过期/在跟踪四态 + 战法家族归属。"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from alphapulse.tracking import signal_tracker as tk


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(tk, "DB_PATH", tmp_path / "test_tracking.db")
    monkeypatch.setattr(tk, "REVIEWS_MD", tmp_path / "pick_reviews.md")
    return tmp_path / "test_tracking.db"


def _seed(conn, sig_id, date, close, path):
    """插入一条信号 + 逐日收盘序列（path 为相对信号日收盘的百分比列表）。"""
    conn.execute(
        "INSERT INTO signals(id,date,symbol,name,score,strict,sector,close,sub_scores,"
        "strategies,family) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (sig_id, date, f"{sig_id:06d}", f"股{sig_id}", 80.0, 1, "板块", close, "{}",
         "B1", "基本面法"))
    d0 = datetime.strptime(date, "%Y-%m-%d")
    for n, pct in enumerate(path, start=1):
        c = close * (1 + pct / 100)
        conn.execute("INSERT INTO performance VALUES(?,?,?,?,?)",
                     (sig_id, n, (d0 + timedelta(days=n)).strftime("%Y-%m-%d"), c, 0.0))


def test_family_of():
    assert tk.family_of("B1") == "基本面法"
    assert tk.family_of("B1+量能B1") == "基本面法"
    assert tk.family_of("知行超短") == "砖型图法"
    assert tk.family_of("单针下三十") == "基本面法"
    assert tk.family_of("B1+知行超短") == "基本面法+砖型图法"
    assert tk.family_of("综合评分") == ""
    assert tk.family_of("周线金叉") == ""
    assert tk.family_of("") == ""


def test_outcomes_four_states(tmp_db):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = tk._conn()
    _seed(conn, 1, today, 10.0, [1.0, 6.2, 3.0])          # 第2日+6.2% → success
    _seed(conn, 2, today, 10.0, [-2.0, -5.5])             # 第2日-5.5% → stopped_drop
    _seed(conn, 3, today, 10.0, [1.0, 2.0, -1.0, 0.5, 2.0])  # 5日满窗未达标 → expired
    _seed(conn, 4, today, 10.0, [1.0, 2.0])               # 仅2日数据 → 继续tracking
    conn.commit()
    conn.close()

    counts = tk.evaluate_outcomes()
    assert counts == {"success": 1, "stopped_drop": 1, "expired": 1}

    conn = sqlite3.connect(tk.DB_PATH)
    rows = dict(conn.execute("SELECT id, status FROM signals"))
    assert rows == {1: "success", 2: "stopped_drop", 3: "expired", 4: "tracking"}
    day, pct = conn.execute(
        "SELECT outcome_day, outcome_pct FROM signals WHERE id=1").fetchone()
    assert day == 2 and pct == pytest.approx(6.2)
    conn.close()

    # 幂等：再跑一遍不重复计数
    assert tk.evaluate_outcomes() == {"success": 0, "stopped_drop": 0, "expired": 0}


def test_success_beats_stop_when_first(tmp_db):
    """先触发哪个算哪个：先大跌后反弹超5%的按止踪算（已不再跟踪）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = tk._conn()
    _seed(conn, 1, today, 10.0, [-6.0, 8.0])
    conn.commit()
    conn.close()
    tk.evaluate_outcomes()
    conn = sqlite3.connect(tk.DB_PATH)
    status, day = conn.execute("SELECT status, outcome_day FROM signals WHERE id=1").fetchone()
    conn.close()
    assert status == "stopped_drop" and day == 1


def test_stale_signal_expires(tmp_db):
    """数据长期缺失的老信号兜底过期，不永久悬挂。"""
    old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    conn = tk._conn()
    _seed(conn, 1, old, 10.0, [1.0])  # 只有1天数据且信号已30天前
    conn.commit()
    conn.close()
    counts = tk.evaluate_outcomes()
    assert counts["expired"] == 1


def test_success_stats_by_family(tmp_db):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = tk._conn()
    _seed(conn, 1, today, 10.0, [6.0])   # 基本面法 success
    _seed(conn, 2, today, 10.0, [1, 1, 1, 1, 1])  # 基本面法 expired
    conn.execute("UPDATE signals SET strategies='知行超短', family='砖型图法' WHERE id=2")
    conn.commit()
    conn.close()
    tk.evaluate_outcomes()
    stats = tk.success_stats()
    assert stats["基本面法"]["success"] == 1 and stats["基本面法"]["rate"] == 100.0
    assert stats["砖型图法"]["resolved"] == 1 and stats["砖型图法"]["success"] == 0


def test_rule_based_review_no_llm(tmp_db):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = tk._conn()
    _seed(conn, 1, today, 10.0, [6.0])
    conn.commit()
    conn.close()
    tk.evaluate_outcomes()
    reviews = tk.distill_success(use_llm=False)
    assert len(reviews) == 1
    assert "选股过程" in reviews[0]["review"] and "脱离成本区" in reviews[0]["review"]
    # reviewed 标记后不重复复盘
    assert tk.distill_success(use_llm=False) == []


def test_nightly_review_text(tmp_db):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = tk._conn()
    _seed(conn, 1, today, 10.0, [6.0])
    conn.commit()
    conn.close()
    outcomes = tk.evaluate_outcomes()
    reviews = tk.distill_success(use_llm=False)
    text = tk.nightly_review_text(new_reviews=reviews, new_outcomes=outcomes)
    assert "夜间复盘" in text and "基本面法" in text and "脱离成本区" in text


def test_family_of_brick3():
    """砖型图(BRICK_THREE_TYPES严格信号)归砖型图法；与B1并发=双法共振。"""
    assert tk.family_of("砖型图") == "砖型图法"
    assert tk.family_of("知行超短+砖型图") == "砖型图法"
    assert tk.family_of("B1+砖型图") == "基本面法+砖型图法"


def test_brick3_badge_in_stock_row():
    """composite 第5严格信号 sig_brick3 存在且为 bool。"""
    from tests.test_factors import make_synthetic_data
    from alphapulse.ranking.composite import build_stock_row
    row = build_stock_row("000001", "测试", make_synthetic_data(500))
    assert row is not None
    assert isinstance(row.get("sig_brick3"), bool)
