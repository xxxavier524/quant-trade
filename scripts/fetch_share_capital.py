"""拉取全市场股本数据 → data/meta/share_capital.csv

用途：B1选股公式条件3（总市值>10亿）和量能B1（流通市值≥40亿，
TDX MV:=C*CAPITAL，CAPITAL=流通股本）需要股本数据，日线CSV中没有。

数据源：akshare 东财实时快照（含总市值/流通市值/最新价），
反推股本数 = 市值/最新价。股本短期内基本稳定，可用于近期历史回放；
历史久远日期的市值用当时收盘价 × 当前股本近似。

用法：
    python scripts/fetch_share_capital.py
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT_PATH = PROJECT_ROOT / "data" / "meta" / "share_capital.csv"


def fetch() -> pd.DataFrame:
    import akshare as ak

    spot = ak.stock_zh_a_spot_em()
    # 北交所股票不在 stock_zh_a_spot_em 中，单独拉取
    frames = [spot]
    try:
        bj = ak.stock_bj_a_spot_em()
        frames.append(bj)
    except Exception as e:  # 北交所接口失败不阻塞主流程
        print(f"[warn] 北交所快照拉取失败: {e}")

    df = pd.concat(frames, ignore_index=True)
    df = df[["代码", "名称", "最新价", "总市值", "流通市值"]].copy()
    df.columns = ["symbol", "name", "price", "total_mv", "float_mv"]
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    for col in ["price", "total_mv", "float_mv"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["price", "float_mv"])
    df = df[df["price"] > 0]
    # 股本（股）= 市值（元）/ 现价
    df["float_shares"] = (df["float_mv"] / df["price"]).round(0)
    df["total_shares"] = (df["total_mv"] / df["price"]).round(0)
    df["fetch_date"] = date.today().isoformat()
    return df[["symbol", "name", "float_shares", "total_shares", "fetch_date"]]


def main():
    df = fetch()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(OUT_PATH)
    print(f"已保存 {len(df)} 只股票股本数据 → {OUT_PATH}")


if __name__ == "__main__":
    main()
