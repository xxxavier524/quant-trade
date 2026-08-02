#!/usr/bin/env python3
"""AlphaPulse-A Web UI Server.

Start: python scripts/start_web.py
Open:  http://localhost:8899
"""

import sys, json, io, random, re, types, hashlib
from pathlib import Path
from datetime import date, datetime
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from alphapulse.factors.factor_registry import FACTOR_REGISTRY, compute_factor
from alphapulse.config.settings import DATA_DIR
from alphapulse.utils.filters import filter_universe

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_stocks(data_dir: str | Path, min_days: int = 200) -> dict[str, pd.DataFrame]:
    """本地日线加载器（v5 2026-08-02：run_backtest 已移除，内联替代）。"""
    stocks = {}
    for f in sorted(Path(data_dir).glob("*.csv")):
        try:
            df = pd.read_csv(f, dtype={"date": str})
            if len(df) >= min_days:
                stocks[f.stem] = df
        except Exception:
            continue
    return stocks


def _screen_metrics(stocks: dict, signal_fn, horizon: int = 5,
                    success_pct: float = 5.0) -> dict:
    """纯选股成功率评估（v5：替代原交易回测引擎，见 alphapulse.screening）。"""
    from alphapulse.screening.evaluator import evaluate_strategy, signal_dates_of
    closes_map = {s: d.set_index("date")["close"].astype(float)
                  for s, d in stocks.items()}
    dates_by_symbol: dict[str, list[str]] = {}
    for sym, df in stocks.items():
        try:
            dates = signal_dates_of(signal_fn(df, symbol=sym), df)
            if dates:
                dates_by_symbol[sym] = dates
        except Exception:
            continue
    return evaluate_strategy(dates_by_symbol, closes_map, horizon, success_pct)


app = FastAPI(title="AlphaPulse-A", version="2.1")

# ── Pydantic models ──
class NLPFactorRequest(BaseModel):
    description: str

class URLFactorRequest(BaseModel):
    url: str

# ── Strategy names & mapping ──
ALL_STRATEGY_NAMES = [
    "B1_FORMULA", "BRICK_ULTRA", "NEEDLE_ENHANCED",
    "B1_ENHANCED", "TWO_STAGE", "B1_B2_B3", "BRICK_THREE_TYPES",
]

def _get_strategy_fn(name: str):
    """Return (strategy_fn, display_name) for a strategy name."""
    mapping = {}
    # Import on demand
    from alphapulse.strategies.b1_formula_strategy import generate_signals as b1
    from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick
    from alphapulse.strategies.needle_enhanced import generate_signals as needle
    from alphapulse.strategies.b1_enhanced import generate_signals as b1e
    from alphapulse.strategies.two_stage_selection import generate_signals as ts
    from alphapulse.strategies.b1_b2_b3_strategy import generate_signals as b1b2b3
    from alphapulse.strategies.brick_three_types import generate_signals as btt
    mapping = {
        "B1_FORMULA": b1, "BRICK_ULTRA": brick, "NEEDLE_ENHANCED": needle,
        "B1_ENHANCED": b1e, "TWO_STAGE": ts, "B1_B2_B3": b1b2b3,
        "BRICK_THREE_TYPES": btt,
    }
    return mapping.get(name)

# ── Serve frontend ──
@app.get("/", response_class=HTMLResponse)
def index():
    return (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

# ── API: System Info ──
@app.get("/api/info")
def api_info():
    data_dir = Path(DATA_DIR)
    n_files = len(list(data_dir.glob("*.csv"))) if data_dir.exists() else 0
    return {
        "name": "AlphaPulse-A",
        "version": "2.1",
        "stocks": n_files,
        "factors": len(FACTOR_REGISTRY),
        "strategies": ALL_STRATEGY_NAMES,
        "date": date.today().isoformat(),
    }

# ── API: Factor Registry ──
@app.get("/api/factors")
def api_factors():
    result = []
    for name, entry in FACTOR_REGISTRY.items():
        result.append({
            "name": name,
            "type": entry.get("type", "core"),
            "desc": entry.get("description", ""),
            "source": entry.get("source", ""),
            "params": entry.get("default_params", {}),
        })
    return result

# ── API: Run Screener (enhanced: date, universe, strategies) ──
@app.get("/api/screen")
def api_screen(
    sample: int = Query(200, ge=10, le=500),
    date: str = Query(None, description="Target date YYYY-MM-DD, defaults to latest"),
    universe: str = Query("sample", description="'sample' or 'all'"),
    strategies: str = Query(None, description="Comma-separated strategy names"),
):
    """Run daily screener with full filtering and strategy selection."""
    data_path = Path(DATA_DIR)
    if not data_path.exists():
        return {"error": f"Data dir not found: {DATA_DIR}"}

    # Load and filter stocks
    stocks = load_stocks(str(data_path), min_days=200)
    stocks = filter_universe(stocks)

    # Determine target date
    target_date = None
    if date:
        try:
            target_date = pd.Timestamp(date)
        except Exception:
            return {"error": f"Invalid date format: {date}. Use YYYY-MM-DD."}

    # Filter stocks that have data on target_date
    if target_date:
        valid_stocks = {}
        for sym, data in stocks.items():
            if target_date in data.index:
                valid_stocks[sym] = data
        stocks = valid_stocks

    # Auto-detect latest common date if no date specified
    if not target_date and stocks:
        all_dates = set()
        for df in stocks.values():
            all_dates.update(df.index)
        if all_dates:
            target_date = max(all_dates)

    # Universe selection
    total_loaded = len(stocks)
    filtered_out = 0
    if universe == 'all':
        # Use all stocks (respect max 2000 for performance)
        if len(stocks) > 2000:
            keys = sorted(stocks.keys())
            random.seed(42)
            stocks = {k: stocks[k] for k in random.sample(keys, 2000)}
    else:
        # Sample mode
        if len(stocks) > sample:
            random.seed(42)
            keys = sorted(stocks.keys())
            stocks = {k: stocks[k] for k in random.sample(keys, sample)}

    # Determine which strategies to run
    if strategies:
        requested = set(s.strip() for s in strategies.split(",") if s.strip())
    else:
        requested = set(ALL_STRATEGY_NAMES)

    # Filter to available strategies
    strat_list = []
    for sn in ALL_STRATEGY_NAMES:
        if sn in requested:
            fn = _get_strategy_fn(sn)
            if fn:
                strat_list.append((sn, fn))

    # Run screening
    # Count ST/delisted/limit-up filtered
    from alphapulse.utils.filters import get_st_stocks, get_delisted_stocks, is_at_limit_up
    st_set = get_st_stocks()
    dl_set = get_delisted_stocks()

    filter_stats = {"st_filtered": 0, "delisted_filtered": 0, "limit_up_filtered": 0}

    results = {}
    for strat_name, strat_fn in strat_list:
        signals_list = []
        signal_types_summary = {}

        for sym, data in stocks.items():
            # Filter stats (count once per unique stock)
            if strat_name == strat_list[0][0]:
                if sym in st_set:
                    filter_stats["st_filtered"] += 1
                    continue
                if sym in dl_set:
                    filter_stats["delisted_filtered"] += 1
                    continue

            try:
                sigs = strat_fn(data, symbol=sym)

                # If target_date, filter to that date only
                if target_date and target_date in sigs.index:
                    sigs = sigs.loc[[target_date]]
                elif target_date:
                    sigs = sigs.iloc[0:0]  # empty

                signal_rows = sigs[sigs["signal"] == 1] if "signal" in sigs.columns else sigs
                n = len(signal_rows)

                # Check limit-up for the latest signal date
                if n > 0 and target_date:
                    if is_at_limit_up(data, sym, date=str(target_date.date())):
                        filter_stats["limit_up_filtered"] += 1
                        continue

                if n > 0:
                    entry = {"symbol": sym, "signals": n}

                    if "signal_type" in signal_rows.columns:
                        type_counts = signal_rows["signal_type"].value_counts().to_dict()
                        entry["signal_types"] = type_counts
                        for t, c in type_counts.items():
                            signal_types_summary[t] = signal_types_summary.get(t, 0) + c

                    if "brick_type" in signal_rows.columns:
                        brick_counts = signal_rows["brick_type"].value_counts().to_dict()
                        entry["brick_types"] = brick_counts
                        for t, c in brick_counts.items():
                            signal_types_summary[t] = signal_types_summary.get(t, 0) + c

                    if "confidence" in signal_rows.columns:
                        entry["confidence"] = round(float(signal_rows["confidence"].max()), 3)

                    signals_list.append(entry)
            except Exception:
                pass

        signals_list.sort(key=lambda x: -x["signals"])
        results[strat_name] = {
            "total_stocks_with_signals": len(signals_list),
            "top10": signals_list[:10],
            "signal_types_summary": signal_types_summary if signal_types_summary else None,
        }

    return {
        "n_stocks": len(stocks),
        "total_loaded": total_loaded,
        "target_date": str(target_date.date()) if target_date else None,
        "universe": universe,
        "filter_stats": filter_stats,
        "strategies": results,
    }

# ── API: Quick Backtest ──
@app.get("/api/backtest")
def api_backtest(
    strategy: str = Query("B1_FORMULA", enum=["B1_FORMULA", "BRICK_ULTRA", "NEEDLE_ENHANCED"]),
    sample: int = Query(100, ge=20, le=500),
):
    """Run quick backtest on sampled stocks."""
    strat_fn = _get_strategy_fn(strategy)
    if not strat_fn:
        return {"error": f"Unknown strategy: {strategy}"}

    data_path = Path(DATA_DIR)
    stocks = load_stocks(str(data_path), min_days=365)
    stocks = filter_universe(stocks)
    if len(stocks) > sample:
        random.seed(42)
        stocks = {k: stocks[k] for k in random.sample(list(stocks.keys()), sample)}

    bt_results = _screen_metrics(stocks, strat_fn)

    return {
        "strategy": strategy,
        "n_stocks": len(stocks),
        "metrics": bt_results,
        "metric": "选股机会命中（5日内收盘≥+5%，无交易模拟）",
    }


# ── API: Factor Quick Backtest ──
@app.get("/api/factors/backtest")
def api_factor_backtest(
    factor_name: str = Query(..., description="Factor name from registry or NLP_ prefix"),
    sample: int = Query(500, ge=50, le=1000),
):
    """Run quick backtest for a single factor (or NLP-generated factor)."""
    data_path = Path(DATA_DIR)
    stocks = load_stocks(str(data_path), min_days=365)
    stocks = filter_universe(stocks)
    if len(stocks) > sample:
        random.seed(42)
        stocks = {k: stocks[k] for k in random.sample(list(stocks.keys()), sample)}

    # Build a signal generator from the factor
    def factor_signal_fn(data, symbol="", **params):
        results = []
        try:
            if factor_name in FACTOR_REGISTRY:
                factor_series = compute_factor(factor_name, data, **params)
            elif factor_name.startswith("NLP_"):
                # Dynamically compiled NLP factor
                factor_series = _run_nlp_factor(data, factor_name)
            else:
                return pd.DataFrame()

            if factor_series is None or len(factor_series) == 0:
                return pd.DataFrame()

            if isinstance(factor_series, pd.Series) and factor_series.dtype == bool:
                signal_dates = data.index[factor_series]
            else:
                # Numeric factor: signal when z-score > 1.5
                threshold = factor_series.quantile(0.9)
                signal_dates = data.index[factor_series > threshold]

            for dt in signal_dates:
                if dt in data.index:
                    results.append({
                        "symbol": symbol,
                        "date": dt,
                        "signal": 1,
                        "strategy": factor_name,
                        "factor_snapshot": {"value": float(data.loc[dt, "close"])},
                    })
        except Exception:
            pass

        if not results:
            return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])
        return pd.DataFrame(results).set_index("date").sort_index()

    bt_results = _screen_metrics(stocks, factor_signal_fn)

    return {
        "factor_name": factor_name,
        "n_stocks": len(stocks),
        "metrics": bt_results,
        "metric": "选股机会命中（5日内收盘≥+5%，无交易模拟）",
    }


# ── NLP factor runtime cache ──
_NLP_FACTOR_CACHE = {}  # name -> code string


def _run_nlp_factor(data, factor_name):
    """Execute a cached NLP factor against data."""
    code = _NLP_FACTOR_CACHE.get(factor_name)
    if not code:
        return pd.Series(False, index=data.index)

    # Compile and execute
    local_ns = {}
    exec(code, {"pd": pd, "np": np}, local_ns)
    compute_fn = local_ns.get("compute")
    if compute_fn:
        result = compute_fn(data)
        return result
    return pd.Series(False, index=data.index)


# ── API: NLP to Factor ──
@app.post("/api/nlp_factor")
def api_nlp_factor(req: NLPFactorRequest):
    """Convert Chinese description to factor, register, and backtest."""
    from alphapulse.utils.nlp_factor import parse_description

    parsed = parse_description(req.description)

    if not parsed["conditions"]:
        return {
            "error": "无法从描述中提取量化条件",
            "factor_name": parsed["name"],
            "factor_code": parsed["code"],
            "backtest_results": None,
            "description": req.description,
        }

    factor_name = parsed["name"]
    factor_code = parsed["code"]

    # Cache the code
    _NLP_FACTOR_CACHE[factor_name] = factor_code

    # Temporarily register in FACTOR_REGISTRY so it appears in lists
    FACTOR_REGISTRY[factor_name] = {
        "module": types.ModuleType("nlp_dynamic"),
        "type": "nlp",
        "description": f"NLP生成: {req.description[:80]}",
        "source": "nlp_factor",
        "default_params": {},
    }

    # Run backtest on 500 stocks
    try:
        data_path = Path(DATA_DIR)
        stocks = load_stocks(str(data_path), min_days=365)
        stocks = filter_universe(stocks)
        if len(stocks) > 500:
            random.seed(42)
            keys = sorted(stocks.keys())
            stocks = {k: stocks[k] for k in random.sample(keys, 500)}

        def factor_signal_fn(data, symbol="", **params):
            results = []
            try:
                factor_series = _run_nlp_factor(data, factor_name)
                if factor_series is None or len(factor_series) == 0:
                    return pd.DataFrame()

                if isinstance(factor_series, pd.Series) and factor_series.dtype == bool:
                    signal_dates = data.index[factor_series]
                else:
                    threshold = factor_series.quantile(0.9) if len(factor_series) > 0 else 0
                    signal_dates = data.index[factor_series > threshold]

                for dt in signal_dates:
                    if dt in data.index:
                        results.append({
                            "symbol": symbol, "date": dt, "signal": 1,
                            "strategy": factor_name,
                            "factor_snapshot": {},
                        })
            except Exception:
                pass
            if not results:
                return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])
            return pd.DataFrame(results).set_index("date").sort_index()

        bt_results = _screen_metrics(stocks, factor_signal_fn)
    except Exception as e:
        bt_results = {"error": str(e)}

    return {
        "factor_name": factor_name,
        "factor_code": factor_code,
        "backtest_results": bt_results,
        "conditions": parsed["conditions"],
        "connector": parsed["connector"],
        "description": req.description,
    }


# ── API: URL to Factor ──
@app.post("/api/url_factor")
def api_url_factor(req: URLFactorRequest):
    """Fetch URL content, attempt to extract factor description, generate factor, backtest."""
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return {"error": "URL必须以http://或https://开头", "url": url}

    # Fetch content
    try:
        from urllib.request import urlopen, Request
        from urllib.error import URLError, HTTPError

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AlphaPulse-A/2.1"
        }
        http_req = Request(url, headers=headers)
        with urlopen(http_req, timeout=15) as resp:
            html_bytes = resp.read()
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            html = html_bytes.decode(charset, errors="replace")
    except HTTPError as e:
        return {"error": f"HTTP错误 {e.code}: {e.reason}", "url": url}
    except URLError as e:
        return {"error": f"网络错误: {e.reason}", "url": url}
    except Exception as e:
        return {"error": f"获取URL失败: {str(e)}", "url": url}

    # Parse content
    title = ""
    text_content = ""
    indicators_found = []

    try:
        from html.parser import HTMLParser

        class TitleTextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_title = False
                self.in_script = False
                self.in_style = False
                self.title = ""
                self.text_parts = []
                self._tag_stack = []

            def handle_starttag(self, tag, attrs):
                self._tag_stack.append(tag)
                if tag == "title":
                    self.in_title = True
                if tag in ("script", "style"):
                    self.in_script = True

            def handle_endtag(self, tag):
                if self._tag_stack and self._tag_stack[-1] == tag:
                    self._tag_stack.pop()
                if tag == "title":
                    self.in_title = False
                if tag in ("script", "style"):
                    self.in_script = False

            def handle_data(self, data):
                if self.in_title:
                    self.title += data.strip()
                if not self.in_script and not self.in_style:
                    clean = data.strip()
                    if clean and len(clean) > 10:
                        self.text_parts.append(clean)

        parser = TitleTextExtractor()
        parser.feed(html[:200000])  # Limit to 200KB
        title = parser.title
        text_content = " ".join(parser.text_parts[:50])  # First 50 text segments

    except Exception:
        # Fallback: regex extraction
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

        # Remove scripts/styles
        clean = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean)
        text_content = clean[:5000]

    # Extract indicators from text
    # Look for numbers with context suggesting trading indicators
    number_patterns = re.findall(
        r'(MA\d+|均线\d+|KDJ|MACD|RSI|布林|成交量|量比|换手率|涨幅|跌幅|振幅|市盈率|市净率)'
        r'\s*[:：=]?\s*([\d.]+%?)',
        text_content[:5000]
    )
    for label, val in number_patterns:
        indicators_found.append({"indicator": label, "value": val})

    # Try to extract a factor description from title/text
    extracted_desc = ""
    factor_code = ""
    factor_name = ""
    backtest_results = None

    if title:
        # Clean title
        extracted_desc = re.sub(r'[-_|].*$', '', title).strip()
        # Try to find trading-related content
        trading_keywords = ['均线', 'MACD', 'KDJ', '量', '突破', '选股', '策略', '因子',
                           '上穿', '下穿', '金叉', '死叉', '放量', '缩量', '阳线', '阴线',
                           'MA', 'EMA', 'RSI', 'boll', 'VOL']
        if any(kw in text_content for kw in trading_keywords):
            # Extract sentences with trading keywords
            sentences = re.split(r'[。！？\n]', text_content)
            relevant = [s.strip() for s in sentences if any(kw in s for kw in trading_keywords)]
            if relevant:
                extracted_desc = relevant[0][:200]

    # Try NLP factor generation if we have a description
    if extracted_desc and len(extracted_desc) >= 5:
        try:
            from alphapulse.utils.nlp_factor import parse_description
            parsed = parse_description(extracted_desc)
            if parsed["conditions"]:
                factor_name = parsed["name"]
                factor_code = parsed["code"]

                # Cache and backtest (same as nlp_factor)
                _NLP_FACTOR_CACHE[factor_name] = factor_code
                FACTOR_REGISTRY[factor_name] = {
                    "module": types.ModuleType("url_dynamic"),
                    "type": "url",
                    "description": f"URL提取: {extracted_desc[:80]}",
                    "source": url,
                    "default_params": {},
                }

                try:
                    data_path = Path(DATA_DIR)
                    stocks = load_stocks(str(data_path), min_days=365)
                    stocks = filter_universe(stocks)
                    if len(stocks) > 500:
                        random.seed(42)
                        keys = sorted(stocks.keys())
                        stocks = {k: stocks[k] for k in random.sample(keys, 500)}

                    def factor_signal_fn(data, symbol="", **params):
                        results = []
                        try:
                            factor_series = _run_nlp_factor(data, factor_name)
                            if factor_series is None or len(factor_series) == 0:
                                return pd.DataFrame()
                            if isinstance(factor_series, pd.Series) and factor_series.dtype == bool:
                                signal_dates = data.index[factor_series]
                            else:
                                threshold = factor_series.quantile(0.9) if len(factor_series) > 0 else 0
                                signal_dates = data.index[factor_series > threshold]
                            for dt in signal_dates:
                                if dt in data.index:
                                    results.append({
                                        "symbol": symbol, "date": dt, "signal": 1,
                                        "strategy": factor_name,
                                        "factor_snapshot": {},
                                    })
                        except Exception:
                            pass
                        if not results:
                            return pd.DataFrame(columns=["symbol", "date", "signal", "strategy", "factor_snapshot"])
                        return pd.DataFrame(results).set_index("date").sort_index()

                    backtest_results = _screen_metrics(stocks, factor_signal_fn)
                except Exception as e:
                    backtest_results = {"error": str(e)}
        except Exception:
            pass

    return {
        "url": url,
        "title": title,
        "extracted_text": text_content[:1000],
        "indicators_found": indicators_found[:20],
        "extracted_description": extracted_desc,
        "factor_name": factor_name,
        "factor_code": factor_code if factor_code else (extracted_desc if extracted_desc else "未提取到因子描述"),
        "backtest_results": backtest_results,
    }


# ── API: Case Detection ──
@app.get("/api/cases")
def api_cases():
    """Run case stock detection."""
    cases_path = PROJECT_ROOT / "cases" / "case_stocks.csv"
    if not cases_path.exists():
        return {"error": "cases/case_stocks.csv not found"}

    cases = pd.read_csv(cases_path)
    cases["symbol"] = cases["symbol"].astype(str).str.zfill(6)
    case_symbols = set(cases["symbol"].tolist())

    stocks = load_stocks(str(Path(DATA_DIR)), min_days=200)
    case_stocks = {s: stocks[s] for s in case_symbols if s in stocks}
    missing = sorted(case_symbols - set(case_stocks.keys()))

    from alphapulse.strategies.b1_formula_strategy import generate_signals as b1
    from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick

    detections = {}
    for sym, data in sorted(case_stocks.items()):
        found = []
        for sn, fn in [("B1", b1), ("BRICK", brick)]:
            try:
                sigs = fn(data, symbol=sym)
                n = len(sigs[sigs["signal"] == 1]) if "signal" in sigs.columns else len(sigs)
                if n > 0:
                    found.append(sn)
            except Exception:
                pass
        detections[sym] = found

    detected = [s for s, v in detections.items() if v]
    return {
        "total_cases": len(case_symbols),
        "with_data": len(case_stocks),
        "missing_data": missing,
        "detected": len(detected),
        "rate": round(len(detected) / max(len(case_stocks), 1) * 100, 1),
        "details": detections,
    }

# ── API: Risk Check ──
@app.get("/api/risk")
def api_risk():
    """Run risk monitor checks (read-only, no positions file needed)."""
    checks = [
        {"check": "factor_registry", "status": "OK" if len(FACTOR_REGISTRY) >= 15 else "WARN", "detail": f"{len(FACTOR_REGISTRY)} factors registered"},
        {"check": "data_available", "status": "OK" if Path(DATA_DIR).exists() else "CRITICAL", "detail": str(DATA_DIR)},
        {"check": "n_stocks", "status": "OK", "detail": f"{len(list(Path(DATA_DIR).glob('*.csv')))} stocks" if Path(DATA_DIR).exists() else "N/A"},
        {"check": "reports_exist", "status": "OK" if list((PROJECT_ROOT / "reports").glob("*.json")) else "WARN", "detail": "backtest results available"},
    ]
    critical = sum(1 for c in checks if c["status"] == "CRITICAL")
    return {"timestamp": datetime.now().isoformat(), "checks": checks, "critical": critical}


# ── API: Backtest History ──
@app.get("/api/backtest_history")
def api_backtest_history():
    """Return past backtest results."""
    bt_dir = PROJECT_ROOT / "backtest_results"
    reports_dir = PROJECT_ROOT / "reports"
    results = []

    for f in sorted(bt_dir.glob("backtest_*.json")):
        try:
            d = json.loads(f.read_text())
            for strat, metrics in d.items():
                if isinstance(metrics, dict) and "annual_return" in metrics:
                    results.append({
                        "file": f.name,
                        "strategy": strat,
                        "annual_return": metrics.get("annual_return"),
                        "max_drawdown": metrics.get("max_drawdown"),
                        "sharpe": metrics.get("sharpe_ratio"),
                        "trades": metrics.get("total_trades"),
                    })
        except Exception:
            pass

    # Add two-stage results if available
    ts_path = reports_dir / "two_stage_opt_results.json"
    if ts_path.exists():
        try:
            d = json.loads(ts_path.read_text())
            if d.get("best_score") is not None:
                results.append({
                    "file": "two_stage_opt",
                    "strategy": "TWO_STAGE_AI",
                    "annual_return": d.get("best_metrics", {}).get("annual_return", "N/A"),
                    "max_drawdown": d.get("best_metrics", {}).get("max_drawdown", "N/A"),
                    "sharpe": d.get("best_metrics", {}).get("sharpe_ratio", "N/A"),
                    "trades": d.get("best_metrics", {}).get("total_trades", "N/A"),
                })
        except Exception:
            pass

    # Add case detection v2 summary
    cd_path = reports_dir / "case_detection_v2.json"
    if cd_path.exists():
        try:
            cd = json.loads(cd_path.read_text())
            cd_summary = cd.get("summary", {})
            for strat_name, strat_data in cd_summary.items():
                if isinstance(strat_data, dict):
                    results.append({
                        "file": "case_detection_v2",
                        "strategy": f"{strat_name} (案例命中)",
                        "annual_return": f"{strat_data.get('rate', 'N/A')}%",
                        "max_drawdown": "N/A",
                        "sharpe": f"{strat_data.get('hit', 'N/A')}/{strat_data.get('total', 'N/A')}",
                        "trades": "案例检测",
                    })
        except Exception:
            pass

    return sorted(results, key=lambda x: x.get("annual_return", 0) if isinstance(x.get("annual_return"), (int, float)) else 0, reverse=True)


if __name__ == "__main__":
    print("=" * 50)
    print("  AlphaPulse-A Web Server")
    print("  http://localhost:8899")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8899, log_level="info")
