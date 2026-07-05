#!/usr/bin/env python3
"""每日早报 — 券商早报的可自动化替代（原微信公众号需求 #5 的落地）。

数据源（2026-07-05 本机实测）：东财全球快讯 stock_info_global_em（约200条，
标题+摘要）+ 新浪7x24 stock_info_global_sina（20条）；财联社 cls 本机挂死不用。

流程：双源拉取(硬超时) → 近N小时过滤+去重 → DeepSeek v4-flash 券商早报式摘要
（宏观政策/行业题材[关联本系统概念库]/个股要闻/风险提示）→
reports/morning_brief_YYYY-MM-DD.md + 飞书推送（配置了 webhook 才发）。
LLM 不可用时输出规则版分组摘要（时间倒序前40条）。

用法：python scripts/morning_brief.py [--hours 18] [--no-llm]
launchd：每日 07:30（config/com.alphapulse.morning-brief.plist）
"""

import argparse
import logging
import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("morning_brief")
REPORTS_DIR = PROJECT_ROOT / "reports"

MAX_ITEMS_LLM = 120     # 喂给 LLM 的最大条数
ITEM_CLIP = 120         # 每条截断字数


def _strip_proxy():
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        os.environ.pop(v, None)
    os.environ["NO_PROXY"] = "*"
    socket.setdefaulttimeout(20)


def fetch_news(hours: int) -> pd.DataFrame:
    """双源拉取 → DataFrame[time, text]，近 hours 小时，按时间倒序去重。"""
    _strip_proxy()
    import akshare as ak

    rows = []
    try:
        em = ak.stock_info_global_em()
        for _, r in em.iterrows():
            rows.append({"time": str(r["发布时间"]),
                         "text": f"{r['标题']}：{str(r['摘要'])[:ITEM_CLIP]}"})
        logger.info(f"东财快讯 {len(em)} 条")
    except Exception as e:
        logger.warning(f"东财快讯失败: {e}")
    try:
        sina = ak.stock_info_global_sina()
        for _, r in sina.iterrows():
            rows.append({"time": str(r["时间"]), "text": str(r["内容"])[:ITEM_CLIP * 2]})
        logger.info(f"新浪7x24 {len(sina)} 条")
    except Exception as e:
        logger.warning(f"新浪7x24失败: {e}")

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    df = df[df["time"] >= cutoff]
    # 去重：文本前30字相同视为同一事件
    df["key"] = df["text"].str[:30]
    df = df.drop_duplicates("key").drop(columns="key")
    return df.sort_values("time", ascending=False).reset_index(drop=True)


def _concept_names() -> list[str]:
    try:
        import json
        d = json.loads((PROJECT_ROOT / "data" / "meta" / "concept_members.json")
                       .read_text())
        return list(d.get("sectors", {}))
    except Exception:
        return []


def llm_brief(news: pd.DataFrame, date: str) -> str | None:
    """DeepSeek v4-flash 券商早报式摘要。失败返回 None。"""
    try:
        from alphapulse.llm.client import chat, is_configured, MODEL_BATCH
        if not is_configured():
            return None
    except Exception:
        return None

    concepts = _concept_names()
    concept_hint = "、".join(concepts[:120])
    items = "\n".join(f"[{r['time'][11:16]}] {r['text']}"
                      for _, r in news.head(MAX_ITEMS_LLM).iterrows())
    prompt = f"""以下是过去一段时间的财经快讯（{date} 早间整理，倒序）：

{items}

请写一份 A股短线交易员的每日早报（Markdown），结构：
## 宏观与政策（3-5条，每条一句话+影响方向）
## 行业与题材（3-6条；若与下列概念板块相关请【标注概念名】：{concept_hint}）
## 个股要闻（3-5条，只留对短线情绪有影响的）
## 风险提示（1-3条）
要求：只基于给定快讯，不编造；短句；总长≤600字。"""
    try:
        return chat(prompt, system="你是券商晨会纪要撰写人，服务A股超短线交易。",
                    model=MODEL_BATCH, temperature=0.3, max_tokens=1200)
    except Exception as e:
        logger.warning(f"LLM 摘要失败: {e}")
        return None


def rule_brief(news: pd.DataFrame) -> str:
    lines = ["## 快讯速览（规则版，LLM未启用）"]
    for _, r in news.head(40).iterrows():
        lines.append(f"- `{r['time'][11:16]}` {r['text']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=18)
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    date = datetime.now().strftime("%Y-%m-%d")
    news = fetch_news(args.hours)
    if news.empty:
        logger.error("双源均无数据，退出")
        return 2
    logger.info(f"近{args.hours}h 快讯 {len(news)} 条（去重后）")

    body = None if args.no_llm else llm_brief(news, date)
    if body is None:
        body = rule_brief(news)

    md = (f"# 每日早报 {date}\n\n"
          f"> 源：东财快讯+新浪7x24 · {len(news)}条 · "
          f"生成 {datetime.now().strftime('%H:%M')}\n\n{body}\n")
    REPORTS_DIR.mkdir(exist_ok=True)
    out = REPORTS_DIR / f"morning_brief_{date}.md"
    out.write_text(md, encoding="utf-8")
    logger.info(f"→ {out}")
    print(md[:1500])

    try:
        from alphapulse.config.settings import FEISHU_WEBHOOK_URL
        if FEISHU_WEBHOOK_URL:
            from alphapulse.notify.feishu_bot import send_feishu
            send_feishu(FEISHU_WEBHOOK_URL, f"📰 早报 {date}\n" + body[:1800])
            logger.info("飞书已推送")
    except Exception as e:
        logger.warning(f"飞书推送失败: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
