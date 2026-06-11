"""pytdx 直连通达信行情服务器 — baostock 的备援数据源。

融合自 daily_stock_analysis（docs/research_journal/01 精华#1：多数据源容错链）。
价值：baostock 限流/宕机时，增量更新仍可完成（pytdx 走通达信自有协议，
与 baostock 服务器、东财 HTTP 接口完全独立）。

口径校准（2026-06-12 实测 605318）：
- close 与 baostock 前复权完全一致（近期无除权时 raw=adj）
- volume 单位为手 → ×100 转股
- 不复权数据：调用方必须做重叠日 close 一致性检查，
  不一致说明该股近期有除权（pytdx裸价≠前复权），跳过等 baostock

仅支持沪深（920北交所不支持）。
"""

import socket

import pandas as pd

SERVERS = [
    ("123.125.108.14", 7709),
    ("119.147.212.81", 7709),
    ("114.80.63.12", 7709),
    ("180.153.18.170", 7709),
]

_api = None


def _market(symbol: str) -> int | None:
    """0=深圳 1=上海；北交所不支持返回 None。"""
    if symbol.startswith(("6", "9")) and not symbol.startswith("92"):
        return 1
    if symbol.startswith(("0", "3")):
        return 0
    return None


def get_api():
    """连接池（惰性单连接，故障自动换服务器）。"""
    global _api
    if _api is not None:
        return _api
    from pytdx.hq import TdxHq_API
    socket.setdefaulttimeout(10)
    api = TdxHq_API()
    for host, port in SERVERS:
        try:
            if api.connect(host, port):
                _api = api
                return _api
        except Exception:
            continue
    return None


def reset_api():
    global _api
    try:
        if _api:
            _api.disconnect()
    except Exception:
        pass
    _api = None


def fetch_recent_daily(symbol: str, n: int = 30) -> pd.DataFrame:
    """近 n 个交易日日线（与CSV同schema，turnover为NaN由调用方ffill兜底）。

    Returns:
        DataFrame[date, open, high, low, close, volume, amount, turnover]
        失败/不支持返回空表
    """
    market = _market(symbol)
    if market is None:
        return pd.DataFrame()
    api = get_api()
    if api is None:
        return pd.DataFrame()
    try:
        bars = api.get_security_bars(9, market, symbol, 0, min(n, 800))
    except Exception:
        reset_api()
        return pd.DataFrame()
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    out = pd.DataFrame({
        "date": df["datetime"].str[:10],
        "open": df["open"].astype(float),
        "high": df["high"].astype(float),
        "low": df["low"].astype(float),
        "close": df["close"].astype(float),
        "volume": (df["vol"].astype(float) * 100).round(0),  # 手→股
        "amount": df["amount"].astype(float),
        "turnover": float("nan"),  # pytdx无换手率；市值反推有ffill兜底
    })
    return out
