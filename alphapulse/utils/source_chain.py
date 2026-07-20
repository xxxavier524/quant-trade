"""多数据源故障切换取数层 — baostock/akshare/pytdx/腾讯，逐源尝试，超时或异常自动切换。

设计目标（2026-07-20 用户需求）：单一数据源（baostock）顺序查询慢、限流/宕机时
整条流水线卡死。本层把日线增量取数抽象成一条「源链」：

    源1 → (超时/异常/空) → 源2 → ... → 全失败返回空

每个源：
- 独立超时（`per_source_timeout` 秒），用线程包裹，超时即放弃切下一个（不阻塞全局）
- 包未安装 / 连接失败 → 捕获并切下一个（graceful degrade）
- 标注 `adjusted`（前复权可直接信）vs 裸价（调用方须做重叠日 close 一致性校验）

标准输出 schema：DataFrame[date, open, high, low, close, volume, amount, turnover?]
volume 单位统一为「股」，date 为 'YYYY-MM-DD' 字符串。

源优先级（可靠性/复权正确性排序）：
1. baostock  前复权，需外部传入已登录 handle（无 handle 时跳过）
2. akshare   前复权（东财），~3 req/s
3. pytdx     裸价（通达信自有协议，与前两者独立），需重叠校验
4. 腾讯      裸价 HTTP（最后兜底），需重叠校验
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from dataclasses import dataclass
from typing import Callable

import pandas as pd

logger = logging.getLogger("source_chain")

STD_COLS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]


@dataclass
class SourceResult:
    df: pd.DataFrame
    source: str
    adjusted: bool           # True=前复权可直接采信；False=裸价需重叠校验


def _std(df: pd.DataFrame) -> pd.DataFrame:
    """裁剪/排序为标准列，date 归一为 10 位字符串，数值化。"""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=STD_COLS)
    df = df.copy()
    if "turn" in df.columns and "turnover" not in df.columns:
        df = df.rename(columns={"turn": "turnover"})
    df["date"] = df["date"].astype(str).str[:10]
    for c in ("open", "high", "low", "close", "volume", "amount", "turnover"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    keep = [c for c in STD_COLS if c in df.columns]
    return df[keep].dropna(subset=["date", "close"]).reset_index(drop=True)


# ------------------------------------------------------------------ 各源适配器
# 每个适配器签名: fetch(symbol, start, end, ctx) -> DataFrame(原始列)
# ctx 携带可选的外部句柄（如已登录的 baostock）。

def _src_baostock(symbol: str, start: str, end: str, ctx: dict) -> pd.DataFrame:
    bs = ctx.get("bs")
    if bs is None:
        raise RuntimeError("no baostock handle")
    code = f"sh.{symbol}" if symbol.startswith(("6", "9")) else f"sz.{symbol}"
    rs = bs.query_history_k_data_plus(
        code, "date,open,high,low,close,volume,amount,turn",
        start_date=start, end_date=end, frequency="d", adjustflag="2")
    rows = []
    while (rs.error_code == "0") and rs.next():
        r = rs.get_row_data()
        if r[0]:
            rows.append(r)
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close",
                                       "volume", "amount", "turn"])


def _src_akshare(symbol: str, start: str, end: str, ctx: dict) -> pd.DataFrame:
    import os
    os.environ.setdefault("no_proxy", "*")
    import akshare as ak
    first = symbol[0]
    ak_code = (f"sh{symbol}" if first in ("6", "9")
               else f"bj{symbol}" if first in ("4", "8") else f"sz{symbol}")
    df = ak.stock_zh_a_daily(symbol=ak_code, start_date=start.replace("-", ""),
                             end_date=end.replace("-", ""), adjust="qfq")
    return df if df is not None else pd.DataFrame()


def _src_pytdx(symbol: str, start: str, end: str, ctx: dict) -> pd.DataFrame:
    from alphapulse.utils.tdx_source import fetch_recent_daily
    df = fetch_recent_daily(symbol, n=40)
    if len(df):
        df = df[df["date"].astype(str) >= start]
    return df


def _src_tencent(symbol: str, start: str, end: str, ctx: dict) -> pd.DataFrame:
    """腾讯日线 HTTP（裸价，最后兜底）。web.ifzq.gtimg.cn 返回前复权/不复权 K 线。"""
    import requests
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    url = ("https://web.ifzq.gtimg.cn/appstuff/hq/kline/get"
           f"?param={prefix}{symbol},day,{start},{end},640,qfq")
    r = requests.get(url, timeout=10)
    j = r.json()["data"][f"{prefix}{symbol}"]
    kline = j.get("qfqday") or j.get("day") or []
    rows = [{"date": k[0], "open": k[1], "close": k[2], "high": k[3],
             "low": k[4], "volume": float(k[5]) * 100} for k in kline]
    return pd.DataFrame(rows)


# 源链：(名称, 适配器, 是否前复权)
DEFAULT_CHAIN: list[tuple[str, Callable, bool]] = [
    ("baostock", _src_baostock, True),
    ("akshare", _src_akshare, True),
    ("pytdx", _src_pytdx, False),
    ("tencent", _src_tencent, False),
]


def fetch_daily(
    symbol: str,
    start: str,
    end: str,
    ctx: dict | None = None,
    per_source_timeout: float = 15.0,
    chain: list[tuple[str, Callable, bool]] | None = None,
    stats: dict | None = None,
) -> SourceResult:
    """逐源尝试取日线，返回首个非空结果。全失败返回空 df（source='none'）。

    Args:
        symbol: 6位代码
        start/end: 'YYYY-MM-DD'
        ctx: 携带 {'bs': 已登录baostock}，可为空
        per_source_timeout: 每个源的超时秒数（超时即切下一个）
        chain: 覆盖默认源链（测试/定制用）
        stats: 若传入，累加各源命中次数 stats[f'src_{name}'] 与超时 stats['timeout']
    """
    ctx = ctx or {}
    chain = chain or DEFAULT_CHAIN
    for name, fn, adjusted in chain:
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(fn, symbol, start, end, ctx)
                raw = fut.result(timeout=per_source_timeout)
        except FutTimeout:
            logger.debug(f"{symbol} 源[{name}] 超时({per_source_timeout}s)，切换")
            if stats is not None:
                stats["timeout"] = stats.get("timeout", 0) + 1
            continue
        except Exception as e:
            logger.debug(f"{symbol} 源[{name}] 异常: {e}，切换")
            continue
        df = _std(raw)
        if len(df):
            if stats is not None:
                stats[f"src_{name}"] = stats.get(f"src_{name}", 0) + 1
            return SourceResult(df, name, adjusted)
    return SourceResult(pd.DataFrame(columns=STD_COLS), "none", True)
