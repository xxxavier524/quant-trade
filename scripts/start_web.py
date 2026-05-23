#!/usr/bin/env python3
"""AlphaPulse-A Web UI Server.

Start: python scripts/start_web.py
Open:  http://localhost:8899
"""

import sys, json, io, random
from pathlib import Path
from datetime import date, datetime
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from alphapulse.factors.factor_registry import FACTOR_REGISTRY
from alphapulse.config.settings import DATA_DIR, INITIAL_CAPITAL

PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="AlphaPulse-A", version="2.0")

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
        "version": "2.0",
        "stocks": n_files,
        "factors": len(FACTOR_REGISTRY),
        "strategies": ["B1_FORMULA", "BRICK_ULTRA", "NEEDLE_ENHANCED", "B1_ENHANCED", "TWO_STAGE"],
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

# ── API: Run Screener (sample mode) ──
@app.get("/api/screen")
def api_screen(sample: int = Query(200, ge=10, le=500)):
    """Run daily screener on sampled stocks."""
    from scripts.run_backtest import load_stocks
    from alphapulse.strategies.b1_formula_strategy import generate_signals as b1
    from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick
    from alphapulse.strategies.needle_enhanced import generate_signals as needle

    data_path = Path(DATA_DIR)
    if not data_path.exists():
        return {"error": f"Data dir not found: {DATA_DIR}"}

    stocks = load_stocks(str(data_path), min_days=200)
    if len(stocks) > sample:
        random.seed(42)
        stocks = {k: stocks[k] for k in random.sample(list(stocks.keys()), sample)}

    results = {}
    for strat_name, strat_fn in [("B1_FORMULA", b1), ("BRICK_ULTRA", brick), ("NEEDLE_ENHANCED", needle)]:
        signals_list = []
        for sym, data in stocks.items():
            try:
                sigs = strat_fn(data, symbol=sym)
                n = len(sigs[sigs["signal"] == 1]) if "signal" in sigs.columns else len(sigs)
                if n > 0:
                    signals_list.append({"symbol": sym, "signals": n})
            except Exception:
                pass
        signals_list.sort(key=lambda x: -x["signals"])
        results[strat_name] = {
            "total_stocks_with_signals": len(signals_list),
            "top10": signals_list[:10],
        }

    return {"n_stocks": len(stocks), "strategies": results}

# ── API: Quick Backtest ──
@app.get("/api/backtest")
def api_backtest(
    strategy: str = Query("B1_FORMULA", enum=["B1_FORMULA", "BRICK_ULTRA", "NEEDLE_ENHANCED"]),
    sample: int = Query(100, ge=20, le=500),
):
    """Run quick backtest on sampled stocks."""
    from scripts.run_backtest import BacktestEngine, load_stocks
    from alphapulse.strategies.b1_formula_strategy import generate_signals as b1
    from alphapulse.strategies.brick_ultra_strategy import generate_signals as brick
    from alphapulse.strategies.needle_enhanced import generate_signals as needle

    strat_map = {"B1_FORMULA": b1, "BRICK_ULTRA": brick, "NEEDLE_ENHANCED": needle}

    data_path = Path(DATA_DIR)
    stocks = load_stocks(str(data_path), min_days=365)
    if len(stocks) > sample:
        random.seed(42)
        stocks = {k: stocks[k] for k in random.sample(list(stocks.keys()), sample)}

    engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
    results = engine.run(stocks, strat_map[strategy], "2022-01-01", str(date.today()))

    return {
        "strategy": strategy,
        "n_stocks": len(stocks),
        "metrics": results,
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

    from scripts.run_backtest import load_stocks
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

    return sorted(results, key=lambda x: x.get("annual_return", 0) or 0, reverse=True)


if __name__ == "__main__":
    print("=" * 50)
    print("  AlphaPulse-A Web Server")
    print("  http://localhost:8899")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8899, log_level="info")
