"""拉取大盘指数日线 → data/index/{code}.csv

修复历史bug：旧版把 data/day/000001.csv（平安银行）当上证指数用。
真实指数走新浪接口（不受东财代理问题影响），存项目内（不依赖外接盘）。

用法：python scripts/fetch_index_data.py
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

INDEX_DIR = PROJECT_ROOT / "data" / "index"

# 主要指数：上证/深成/创业板/科创50/沪深300/中证500
INDEXES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
    "sh000300": "沪深300",
    "sh000905": "中证500",
}


def main() -> int:
    # 新浪接口直连（本机代理7890经常没开，akshare会卡在代理上）
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"

    import socket
    socket.setdefaulttimeout(30)
    import akshare as ak

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for code, name in INDEXES.items():
        try:
            df = ak.stock_zh_index_daily(symbol=code)
            df = df[["date", "open", "high", "low", "close", "volume"]]
            tmp = INDEX_DIR / f"{code}.csv.tmp"
            df.to_csv(tmp, index=False)
            os.replace(tmp, INDEX_DIR / f"{code}.csv")
            print(f"{code} {name}: {len(df)} 行，至 {df['date'].iloc[-1]}")
            ok += 1
        except Exception as e:
            print(f"{code} {name}: FAIL {e}", file=sys.stderr)
    return 0 if ok == len(INDEXES) else 1


if __name__ == "__main__":
    sys.exit(main())
