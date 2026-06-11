"""拉取新浪行业板块 + 概念板块成员表 → data/meta/{sector,concept}_members.json

板块历史指数不依赖外部API：成员表确定后，板块指数由本地日线CSV等权聚合
（见 alphapulse/market/sector_score.py），彻底摆脱东财接口被封的问题。

成员表变化缓慢，每周刷新一次即可。

用法：
    python scripts/fetch_sector_data.py              # 行业（49个）
    python scripts/fetch_sector_data.py --concepts   # 行业 + 概念（175个，较慢）
"""

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT_PATH = PROJECT_ROOT / "data" / "meta" / "sector_members.json"
CONCEPT_PATH = PROJECT_ROOT / "data" / "meta" / "concept_members.json"


def _fetch_boards(ak, indicator: str, min_ok: int, out_path: Path) -> int:
    spot = ak.stock_sector_spot(indicator=indicator)
    # 增量合并：保留旧文件中本次失败板块的数据
    boards = {}
    try:
        boards = json.loads(out_path.read_text())["sectors"]
    except Exception:
        pass
    n_ok, n_fail_streak = 0, 0
    for _, row in spot.iterrows():
        label, name = row["label"], row["板块"]
        try:
            detail = ak.stock_sector_detail(sector=label)
            symbols = sorted({str(c)[-6:] for c in detail["code"].astype(str)})
            boards[name] = {"label": label, "symbols": symbols}
            n_ok += 1
            n_fail_streak = 0
            print(f"  {name}: {len(symbols)} 只")
        except Exception as e:
            n_fail_streak += 1
            print(f"  {name}: FAIL {str(e)[:60]}", file=sys.stderr)
            if n_fail_streak >= 5:
                print("  连续失败≥5，疑似限流，退避60秒...", file=sys.stderr)
                time.sleep(60)
                n_fail_streak = 0
        time.sleep(0.8)

    if len(boards) < min_ok:
        print(f"累计仅 {len(boards)} 个（本次成功{n_ok}），不保存", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetch_date": date.today().isoformat(), "sectors": boards}
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, out_path)
    print(f"已保存 {len(boards)} 个板块成员表（本次成功{n_ok}）→ {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concepts", action="store_true", help="同时拉取概念板块（175个，较慢）")
    ap.add_argument("--concepts-only", action="store_true")
    args = ap.parse_args()

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"
    import socket
    socket.setdefaulttimeout(30)
    import akshare as ak

    rc = 0
    if not args.concepts_only:
        rc |= _fetch_boards(ak, "新浪行业", 30, OUT_PATH)
    if args.concepts or args.concepts_only:
        rc |= _fetch_boards(ak, "概念", 50, CONCEPT_PATH)
    return rc


if __name__ == "__main__":
    sys.exit(main())
