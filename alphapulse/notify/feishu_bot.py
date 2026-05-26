"""Feishu (Lark) bot notification for daily screening results."""
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def build_daily_report(macro_score, macro_level, strong_sectors, b1b2_top5, brick_top5, needle_top5, web_url="http://localhost:8501"):
    date_str = datetime.now().strftime("%Y-%m-%d")

    def fmt_section(title, stocks):
        if not stocks:
            return f"**{title}**: 无信号\n"
        emoji_map = {"S": "\U0001f7e2", "A": "\U0001f7e2", "B": "\U0001f7e1", "C": "\U0001f7e0", "D": "\U0001f534"}
        lines = [f"**{title}**:"]
        for s in stocks[:5]:
            emoji = emoji_map.get(s.get("grade", ""), "\u26aa")
            lines.append(f"- {s.get('symbol','')} {s.get('name','')} {emoji}{s.get('grade','')}({s.get('score',0)}) {s.get('summary','')}")
        return "\n".join(lines) + "\n"

    sectors_str = ", ".join(strong_sectors[:5]) if strong_sectors else "无数据"
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"\U0001f4ca AlphaPulse 选股日报 ({date_str})"
                },
                "template": "blue"
            },
            "elements": [
                {"tag": "markdown", "content": f"**大盘**: {macro_score}/100 {macro_level} | **强势板块**: {sectors_str}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": fmt_section("\U0001f3af B1B2 低位潜力", b1b2_top5)},
                {"tag": "markdown", "content": fmt_section("\U0001f9f1 砖型图超短", brick_top5)},
                {"tag": "markdown", "content": fmt_section("\U0001f4cc 单针洗盘", needle_top5)},
                {"tag": "hr"},
                {"tag": "action", "actions": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "\U0001f4ce 查看详情"},
                    "url": web_url,
                    "type": "default"
                }]}
            ]
        }
    }
    return card


def send_feishu(webhook_url, content):
    payload = content if isinstance(content, dict) else {"msg_type": "text", "content": {"text": str(content)}}
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200 and resp.json().get("code") == 0:
            logger.info("Feishu push success")
            return True
        logger.error(f"Feishu error: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Feishu push failed: {e}")
        return False


def push_daily_screening(webhook_url, macro_result, sector_data, b1b2_results, brick_results, needle_results, web_url="http://localhost:8501"):
    if not webhook_url:
        logger.warning("No webhook URL")
        return False
    card = build_daily_report(
        macro_result.get("score", 0),
        macro_result.get("level", "未知"),
        sector_data.get("strong_sectors", []),
        b1b2_results,
        brick_results,
        needle_results,
        web_url,
    )
    return send_feishu(webhook_url, card)
