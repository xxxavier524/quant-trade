import pytest
from alphapulse.notify.feishu_bot import build_daily_report


def test_build_report_empty():
    card = build_daily_report(65, "震荡偏多", ["电子"], [], [], [])
    assert card["msg_type"] == "interactive"
    assert "震荡偏多" in str(card)


def test_build_report_with_stocks():
    b1b2 = [{"symbol": "000001", "name": "平安银行", "score": 75, "grade": "A", "summary": "测试"}]
    card = build_daily_report(70, "震荡偏多", ["银行"], b1b2, [], [])
    assert "平安银行" in str(card)


def test_send_empty_webhook():
    from alphapulse.notify.feishu_bot import send_feishu
    assert send_feishu("", {}) is False
