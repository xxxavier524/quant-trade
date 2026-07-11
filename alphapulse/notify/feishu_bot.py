"""Feishu (Lark) bot notification for daily screening results."""
import requests
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# 单条文本上限（字符）。飞书自定义机器人 payload 上限约30KB（汉字3字节≈1万字），
# 取3800字/条既留足余量又避免客户端把超长消息折叠；超限自动分段多条发送。
MAX_TEXT_CHARS = 3800
# 分段消息间隔秒数：群机器人限流约5条/秒、100条/分（超限报 code 11232）
CHUNK_INTERVAL = 1.5


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


def _split_text(text, limit=MAX_TEXT_CHARS):
    """按换行边界把长文本切成 ≤limit 字符的段（单行超限时硬切兜底）。"""
    if len(text) <= limit:
        return [text]
    parts, cur, cur_len = [], [], 0
    for line in text.split("\n"):
        while len(line) > limit:  # 极端长行硬切
            if cur:
                parts.append("\n".join(cur))
                cur, cur_len = [], 0
            parts.append(line[:limit])
            line = line[limit:]
        if cur_len + len(line) + 1 > limit and cur:
            parts.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        parts.append("\n".join(cur))
    return parts


def _post_with_retry(webhook_url, payload, retries=3):
    """带退避重试的单条发送。频控(11232)与超时是历史上整条消息丢失的两大主因。"""
    for attempt in range(retries + 1):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=15)
            if resp.status_code == 200:
                j = resp.json()
                if j.get("code") == 0:
                    return True
                if j.get("code") == 11232:  # frequency limited：退避后重试
                    logger.warning(f"Feishu 频控，第{attempt + 1}次退避重试")
                    time.sleep(8 * (attempt + 1))
                    continue
                logger.error(f"Feishu error: {resp.text}")
                return False  # 其他业务错误（如关键词不匹配）重试无意义
            logger.error(f"Feishu http {resp.status_code}")
        except Exception as e:
            logger.warning(f"Feishu 发送异常(第{attempt + 1}次): {e}")
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    logger.error("Feishu push failed: 重试耗尽")
    return False


def send_feishu(webhook_url, content):
    """发送文本或卡片。文本超长自动分段为 (i/n) 多条，整体成功才返回 True。

    每段都保证含 [AlphaPulse] 关键词（机器人安全设置逐条校验）。
    """
    if isinstance(content, dict):
        ok = _post_with_retry(webhook_url, content)
        if ok:
            logger.info("Feishu push success")
        return ok

    chunks = _split_text(str(content))
    total = len(chunks)
    all_ok = True
    for i, chunk in enumerate(chunks, start=1):
        if "AlphaPulse" not in chunk:
            chunk = ("[AlphaPulse] " if total == 1
                     else f"[AlphaPulse]({i}/{total})\n") + chunk
        elif total > 1:
            chunk = f"({i}/{total})\n" + chunk
        all_ok &= _post_with_retry(webhook_url, {"msg_type": "text",
                                                 "content": {"text": chunk}})
        if i < total:
            time.sleep(CHUNK_INTERVAL)
    if all_ok:
        logger.info(f"Feishu push success ({total}条)")
    return all_ok


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
