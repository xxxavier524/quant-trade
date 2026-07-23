"""数据新鲜度统一判定（2026-07-23 用户定）。

铁律：选股、复盘及一切下游操作，必须在"数据已是最新"的前提下执行。
单一事实源：基准交易日 = 独立更新的上证指数最新bar；
新鲜 = 已到基准交易日的个股占比 ≥ 阈值（默认 75%，与 daily_update 健康线一致）。
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_CSV = PROJECT_ROOT / "data" / "index" / "sh000001.csv"
FRESH_MIN_COVERAGE = 0.75   # 已到基准交易日的个股占比达此值即视为"数据已最新可操作"


def _tail_last_date(fpath: Path) -> str | None:
    """高效读CSV末行日期（只读尾部，不载全文件）。"""
    try:
        with open(fpath, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", "ignore")
        d = tail.strip().splitlines()[-1].split(",")[0]
        return d if len(d) == 10 and d[4] == "-" else None
    except Exception:
        return None


def index_latest_date(index_csv: Path | None = None) -> str | None:
    """基准最新交易日 = 上证指数最新bar日期（独立于个股取数，不受其失败影响）。"""
    return _tail_last_date(index_csv or INDEX_CSV)


def market_coverage(data_dir, target: str) -> float:
    """已到 target 交易日的个股占比（与 daily_update._coverage 同口径）。"""
    files = list(Path(data_dir).glob("*.csv"))
    if not files:
        return 0.0
    n = sum(1 for f in files if (_tail_last_date(f) or "") >= target)
    return n / len(files)


def check_freshness(data_dir, min_coverage: float = FRESH_MIN_COVERAGE) -> dict:
    """确认数据是否已最新。返回 {ok, target, coverage, reason}。

    - 无指数基准（sh000001.csv 缺失/损坏）→ ok=False：无法确认即视为不满足铁律，
      调用方应先跑 fetch_index_data 再重试（宁可拦，不在不可确认时盲跑）。
    - 有基准：ok = 已到基准日的个股占比 ≥ min_coverage。
    """
    target = index_latest_date()
    if not target:
        return {"ok": False, "target": None, "coverage": None,
                "reason": "缺指数基准(data/index/sh000001.csv)，无法确认数据最新——先跑 fetch_index_data"}
    cov = market_coverage(data_dir, target)
    ok = cov >= min_coverage
    reason = (f"数据已最新：{cov*100:.0f}% 个股已到基准日 {target}" if ok
              else f"数据未最新：仅 {cov*100:.0f}% 个股到基准日 {target}（<{min_coverage*100:.0f}% 阈值）")
    return {"ok": ok, "target": target, "coverage": cov, "reason": reason}
