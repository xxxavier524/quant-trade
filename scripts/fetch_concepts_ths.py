#!/usr/bin/env python3
"""同花顺概念板块成员表抓取 → data/meta/concept_members.json（+ 催化事件 sidecar）。

为什么换同花顺（2026-06-17 实测对比）：
- 新浪概念仅 126 个，12 个近期热点只命中 2 个（固态电池/机器人）。
- 东财(EM)接口本机被封（ConnectionError），不可用。
- 同花顺 `stock_board_concept_name_ths` 373 个概念，12 热点命中 10 个
  （固态电池/低空经济/人形机器人/算力/液冷/CPO/减肥药/可控核聚变/脑机接口…）。

成员抓取：同花顺概念详情页 q.10jqka.com.cn/gn/detail 分页（每页10只）。
该站有 hexin-v 反爬节流（akshare 已因此移除 *_cons_ths），故用
会话+重试退避绕过间歇性空响应，空页=到尾页。成员表变化缓慢，每周刷新即可。

输出格式与旧版一致（sector_score.symbol_concept_map 直接复用）：
    {"fetch_date": "...", "source": "ths",
     "sectors": {概念名: {"label": 概念code, "symbols": ["000070", ...]}}}
另存 data/meta/concept_catalysts.json：{概念名: {"驱动事件":..., "龙头股":..., "成分股数量":...}}

用法：
    python scripts/fetch_concepts_ths.py            # 全量 373 概念（约30-50分钟）
    python scripts/fetch_concepts_ths.py --limit 20 # 只抓前20个（验证用）
    python scripts/fetch_concepts_ths.py --new-only # 只补新浪没有的新概念（快）
"""

import argparse
import json
import os
import re
import socket
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
META_DIR = PROJECT_ROOT / "data" / "meta"
CONCEPT_PATH = META_DIR / "concept_members.json"
CATALYST_PATH = META_DIR / "concept_catalysts.json"

UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"),
    "Referer": "https://q.10jqka.com.cn/",
}
_CODE_RE = re.compile(r"stockpage\.10jqka\.com\.cn/(\d{6})")


def _clean_proxy():
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(v, None)
    os.environ["NO_PROXY"] = "*"
    socket.setdefaulttimeout(25)


def fetch_members(session, code: str, max_pages: int = 60) -> list[str]:
    """抓单个概念的全部成员代码（分页，重试绕节流，空页=尾页）。"""
    members: set[str] = set()
    for page in range(1, max_pages + 1):
        url = (f"https://q.10jqka.com.cn/gn/detail/field/199112/order/desc/"
               f"page/{page}/ajax/1/code/{code}")
        text = ""
        for attempt in range(4):
            try:
                r = session.get(url, timeout=15)
            except Exception:
                time.sleep(1.2 * (attempt + 1))
                continue
            if len(r.text) > 600 and "stockpage" in r.text:
                text = r.text
                break
            time.sleep(1.2 * (attempt + 1))  # 节流→退避重试
        found = {c for c in _CODE_RE.findall(text) if c[0] in "036859"}
        if not found:
            break  # 连续重试仍空 → 到尾页
        members |= found
        time.sleep(0.6)
    return sorted(members)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只抓前N个概念（验证用，0=全量）")
    ap.add_argument("--new-only", action="store_true", help="只补新浪现有JSON里没有的概念")
    args = ap.parse_args()

    _clean_proxy()
    import requests
    import akshare as ak

    print("拉取同花顺概念列表 ...", file=sys.stderr)
    names = ak.stock_board_concept_name_ths()
    code_of = {str(r["name"]): str(r["code"]) for _, r in names.iterrows()}
    print(f"同花顺概念 {len(code_of)} 个", file=sys.stderr)

    # 催化事件 sidecar（best-effort，不阻塞主流程）
    try:
        summ = ak.stock_board_concept_summary_ths()
        ncol = next((c for c in summ.columns if "概念" in str(c) or "名称" in str(c)), None)
        catalysts = {}
        for _, row in summ.iterrows():
            nm = str(row.get(ncol, "")).strip()
            if nm:
                catalysts[nm] = {k: str(row[k]) for k in summ.columns if k != ncol}
        META_DIR.mkdir(parents=True, exist_ok=True)
        CATALYST_PATH.write_text(json.dumps(
            {"fetch_date": date.today().isoformat(), "catalysts": catalysts},
            ensure_ascii=False, indent=1))
        print(f"催化事件 {len(catalysts)} 条 → {CATALYST_PATH}", file=sys.stderr)
    except Exception as e:
        print(f"催化事件抓取失败（忽略）: {e}", file=sys.stderr)

    # 增量合并：保留旧文件中本次未刷新/失败的概念
    boards: dict = {}
    try:
        boards = json.loads(CONCEPT_PATH.read_text())["sectors"]
    except Exception:
        pass
    existing = set(boards)

    targets = list(code_of.items())
    if args.new_only:
        targets = [(n, c) for n, c in targets if n not in existing]
        print(f"--new-only：{len(targets)} 个新概念待补", file=sys.stderr)
    if args.limit:
        targets = targets[:args.limit]

    session = requests.Session()
    session.headers.update(UA)
    try:
        session.get("https://q.10jqka.com.cn/", timeout=15)  # 预热cookie
    except Exception:
        pass

    n_ok, n_fail_streak = 0, 0
    for i, (name, code) in enumerate(targets, 1):
        try:
            syms = fetch_members(session, code)
            if syms:
                boards[name] = {"label": code, "symbols": syms}
                n_ok += 1
                n_fail_streak = 0
            else:
                n_fail_streak += 1
            if i % 10 == 0 or syms:
                print(f"  [{i}/{len(targets)}] {name}: {len(syms)} 只 "
                      f"(累计OK {n_ok})", file=sys.stderr)
        except Exception as e:
            n_fail_streak += 1
            print(f"  [{i}/{len(targets)}] {name}: FAIL {str(e)[:60]}", file=sys.stderr)
        if n_fail_streak >= 8:
            print("  连续失败≥8，疑似封禁，退避90秒 ...", file=sys.stderr)
            time.sleep(90)
            n_fail_streak = 0

    if len(boards) < 50:
        print(f"累计仅 {len(boards)} 个概念，不保存（疑似抓取失败）", file=sys.stderr)
        return 1
    META_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"fetch_date": date.today().isoformat(), "source": "ths", "sectors": boards}
    tmp = CONCEPT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, CONCEPT_PATH)
    print(f"已保存 {len(boards)} 个概念成员表（本次新抓 {n_ok}）→ {CONCEPT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
