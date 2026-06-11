"""拉取新浪行业板块成员表 → data/meta/sector_members.json

板块历史指数不依赖外部API：成员表确定后，板块指数由本地日线CSV等权聚合
（见 alphapulse/market/sector_score.py），彻底摆脱东财接口被封的问题。

成员表变化缓慢，每周刷新一次即可。

用法：python scripts/fetch_sector_data.py
"""

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT_PATH = PROJECT_ROOT / "data" / "meta" / "sector_members.json"


def main() -> int:
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"
    import socket
    socket.setdefaulttimeout(30)
    import akshare as ak

    spot = ak.stock_sector_spot(indicator="新浪行业")
    sectors = {}
    for _, row in spot.iterrows():
        label, name = row["label"], row["板块"]
        try:
            detail = ak.stock_sector_detail(sector=label)
            symbols = sorted({str(c)[-6:] for c in detail["code"].astype(str)})
            sectors[name] = {"label": label, "symbols": symbols}
            print(f"  {name}: {len(symbols)} 只")
        except Exception as e:
            print(f"  {name}: FAIL {str(e)[:60]}", file=sys.stderr)
        time.sleep(0.5)

    if len(sectors) < 30:
        print(f"仅成功 {len(sectors)} 个板块，可能接口异常，不覆盖旧文件", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetch_date": date.today().isoformat(), "sectors": sectors}
    tmp = OUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, OUT_PATH)
    print(f"已保存 {len(sectors)} 个板块成员表 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
