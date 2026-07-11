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


def test_split_text_short_passthrough():
    from alphapulse.notify.feishu_bot import _split_text
    assert _split_text("短消息") == ["短消息"]


def test_split_text_newline_boundary():
    from alphapulse.notify.feishu_bot import _split_text
    lines = [f"第{i}行" + "内容" * 50 for i in range(100)]  # 每行~104字符
    text = "\n".join(lines)
    parts = _split_text(text, limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "\n".join(parts) == text  # 无损：拼回原文


def test_split_text_hard_slice_long_line():
    from alphapulse.notify.feishu_bot import _split_text
    text = "超长" * 3000  # 单行6000字符
    parts = _split_text(text, limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(parts) == text


def test_send_feishu_chunks_and_keyword(monkeypatch):
    from alphapulse.notify import feishu_bot as fb
    sent = []
    monkeypatch.setattr(fb, "_post_with_retry", lambda url, payload, retries=3: (sent.append(payload), True)[1])
    monkeypatch.setattr(fb.time, "sleep", lambda s: None)
    long_text = "\n".join("行" * 100 for _ in range(200))  # ~2万字符 → 多段
    assert fb.send_feishu("http://fake", long_text) is True
    assert len(sent) > 1
    for i, p in enumerate(sent, start=1):
        t = p["content"]["text"]
        assert "AlphaPulse" in t          # 每段都带安全关键词
        assert f"({i}/{len(sent)})" in t  # 每段有序号
