# Open-Source Project Integration Plan for AlphaPulse-A

> Generated: 2026-05-16 | Target System: AlphaPulse-A | Python: 3.14.3

---

## 0. Python 3.14 Compatibility Summary

| Project | pip Package | Latest Version | Python 3.14 pip? | Notes |
|---------|------------|---------------|-------------------|-------|
| Microsoft Qlib | `pyqlib` | 0.9.7 | **NO** | Wheels only for cp38-cp312. Requires Python <=3.12 |
| Backtrader | `backtrader` | 1.9.78.123 | **YES** | Pure Python wheel (py2.py3-none-any) |
| FinRL | `finrl` | 0.3.7 | **YES** | Pure Python wheel |
| OpenBB | `openbb` | 4.7.1 | **YES** | Pure Python, but heavy dependency tree (arch, quandl, etc.) |
| yfinance | `yfinance` | 1.3.0 | **YES** | Has cp314 wheels for deps (websockets-16.0-cp314) |
| ML for Trading | N/A (git clone) | 2nd Ed. | **N/A** | Source only, no pip package |

**Key blocker**: `pyqlib` has no cp313 or cp314 wheels. Pre-built wheels exist only for Python 3.8-3.12 (cp38 through cp312). Installing from source on 3.14 is untested and likely fails due to Cython/C extension C API changes.

---

## 1. Microsoft Qlib -- AI-Oriented Quant Platform

### Can pip install?
**NO** on Python 3.14. `pyqlib` 0.9.7 publishes wheels only for cp38, cp39, cp310, cp311, cp312. On Python 3.14, pip returns "No matching distribution found."

**Workaround**: Create a Python 3.12 virtual environment alongside the main 3.14 venv:
```bash
# Requires having Python 3.12 installed separately
python3.12 -m venv /Users/qiushixuan/cc/quantan-trade/.venv-312
source .venv-312/bin/activate
pip install pyqlib
```

### Can we use just a subset (factor library only)?
**YES**. The Alpha158 and Alpha360 factor loaders can be used standalone without the full Qlib pipeline.

Minimal usage -- import just the factor DataLoader classes:

```python
from qlib.contrib.data.loader import Alpha158DL, Alpha360DL

# Option 1: Alpha158 -- 158 handcrafted technical factors
loader_158 = Alpha158DL(
    instruments="csi300",
    start_time="2020-01-01",
    end_time="2025-12-31",
    freq="day"
)
features_158 = loader_158.load()  # DataFrame with 158 factor columns

# Option 2: Alpha360 -- 360 raw OHLCV sequence features (60d x 6 fields)
loader_360 = Alpha360DL(
    instruments="csi300",
    start_time="2020-01-01",
    end_time="2025-12-31",
    freq="day"
)
features_360 = loader_360.load()  # DataFrame with 360 factor columns
```

**Alpha158 Factor Categories** (158 factors total):
| Category | Count | Example Factors |
|----------|-------|-----------------|
| K-line features | ~10 | KMID, KLEN, KUP, KLOW, KMID2 |
| Price features | ~7 | Normalized prices at various lags |
| Rolling operators | ~140 | ROC, MA, STD, BETA, RSV, RSI, MACD, correlations, covariances |

**Alpha360 Structure**: 6 fields (open, close, high, low, volume, vwap) x 60 lookback days = 360 features, normalized by current close/volume. Best for deep learning models (LSTM, GRU, Transformer).

### What specific feature helps AlphaPulse-A the most?
The **Alpha158 factor library** directly addresses the biggest gap in AlphaPulse-A: the system has only 13 custom factors (8 original + 5 experimental). Qlib provides 158 battle-tested A-share factors with known IC/ICIR performance characteristics. This would dramatically expand the feature space for signal generation.

Also valuable: the **IC/ICIR/RankIC analysis module** provides standardized factor performance evaluation that AlphaPulse-A currently lacks.

### Concrete integration steps (3-5):

1. **Set up Python 3.12 sidecar environment** and install `pyqlib`:
   ```bash
   python3.12 -m venv .venv-312
   source .venv-312/bin/activate
   pip install pyqlib
   ```
   (Or use uv to manage dual Python versions.)

2. **Create a factor bridge module** at `alphapulse/factors/qlib_factors.py`:
   - `compute_alpha158(data: pd.DataFrame) -> pd.DataFrame` -- wraps `Alpha158DL` to compute 158 factors from a given OHLCV DataFrame
   - `compute_alpha360(data: pd.DataFrame) -> pd.DataFrame` -- computes 360 raw sequence features
   - Register these as batch factor generators in `factor_registry.py`
   - The bridge handles converting between AlphaPulse-A's CSV data format and Qlib's expected data format

3. **Add factor performance analysis** at `scripts/factor_ic_analysis.py`:
   - Compute IC (Information Coefficient), ICIR, RankIC for each factor
   - Forward-return alignment to avoid look-ahead bias
   - Output factor ranking report to `reports/factor_ic_analysis.json`

4. **Integrate LightGBM via Qlib** (or standalone `lightgbm` pip package):
   - Use Alpha158 factors as feature input
   - Train LightGBM ranker (`objective="lambdarank"`) for stock selection
   - Generate daily Top-K stock picks, competing with existing condition-based strategies
   - This is the "P0 #4" item from the existing gap analysis

5. **Data format adapter**: Qlib uses a custom binary format. Write a converter in `scripts/convert_to_qlib.py`:
   ```python
   import qlib
   from qlib.data import D
   from qlib.config import REG_CN
   qlib.init(provider_uri="data/qlib_bin", region=REG_CN)
   ```
   Or, more practically for minimal integration, convert CSV data to the format that `Alpha158DL` expects via its `instruments` and time-range parameters, without needing the full binary format pipeline.

---

## 2. Backtrader -- Backtesting Framework

### Can pip install?
**YES**. `pip install backtrader` installs v1.9.78.123, pure Python wheel compatible with Python 3.14.

### Can we run backtrader alongside our custom engine for cross-validation?
**YES**, but with a caveat. The CLAUDE.md constraint states "回测框架仅 VeighNa (vnpy)，不接受 backtrader" (backtesting framework only VeighNa, does not accept backtrader). However, backtrader can still serve as a **cross-validation tool** in a separate script or environment -- not as the primary backtester.

Recommended approach: run backtrader in a dedicated cross-validation script that:
1. Takes the same strategy signals as input
2. Runs backtrader's event-driven backtest in parallel
3. Compares metrics (Sharpe, max drawdown, win rate) against the VeighNa engine
4. Flags discrepancies >5% for investigation

### Does backtrader have advantages our custom engine lacks?
Yes, several:

| Feature | AlphaPulse-A Custom Engine | Backtrader |
|---------|---------------------------|------------|
| Multi-timeframe | No | Yes (daily + hourly) |
| Parameter optimization | Manual/grid-search planned | `cerebro.optstrategy()` auto grid search |
| Built-in analyzers | 5 metrics | Sharpe, Drawdown, TimeReturn, SQN, TradeAnalyzer, etc. |
| Order types | Market only | Market, Limit, Stop, StopLimit, StopTrail, OCO |
| Slippage models | Fixed percentage | Bar-based, volume-based, configurable |
| Plotting | Manual HTML | `cerebro.plot()` professional charts |
| Commission models | Fixed rate | Configurable per-instrument, per-broker |

However, the **original backtrader is no longer actively maintained** (last meaningful update was years ago). Consider `backtrader-slim` (dennisdeh/backtrader-slim) for Python 3.10+.

### What specific feature helps AlphaPulse-A the most?
**Multi-timeframe backtesting and parameter optimization**. The existing custom engine runs single-timeframe (daily) with manual parameter tuning. Backtrader's `cerebro.optstrategy()` can grid-search parameter combinations (e.g., shrink_ratio x j_threshold x K) in one run and produce a ranked results table.

### Concrete integration steps (3-5):

1. **Install backtrader in a dedicated validation environment** (or in the main venv if constraints allow):
   ```bash
   pip install backtrader
   ```

2. **Create cross-validation script** at `scripts/cross_validate_backtrader.py`:
   ```python
   import backtrader as bt
   from alphapulse.strategies.b1 import B1SignalGenerator
   
   class AlphaPulseStrategy(bt.Strategy):
       def __init__(self):
           self.signal_gen = B1SignalGenerator()
       def next(self):
           # Convert B1 condition-based signals to backtrader orders
           signals = self.signal_gen.generate(self.data)
           if signals['b1_signal'].iloc[-1]:
               self.buy()
   ```
   Run backtrader on the same data + same strategy logic, then compare performance metrics output against the VeighNa engine.

3. **Use backtrader for parameter grid search** (Phase 6 acceleration):
   ```python
   cerebro.optstrategy(
       B1Strategy,
       shrink_ratio=[0.2, 0.25, 0.3, 0.4],
       j_threshold=[8, 10, 13, 15],
       K=[1.5, 2.0, 2.5, 3.0]
   )
   ```
   Backtrader handles the Cartesian product automatically.

4. **Add benchmark comparison**: Run the same strategy logic through backtrader and VeighNa, comparing results. If metrics agree within 5%, the custom engine is validated. If not, investigate the discrepancy.

5. **Optional: Multi-timeframe validation**: Backtest strategies that use both daily and intraday signals, something VeighNa-supported but not yet implemented in the custom engine.

---

## 3. FinRL -- Reinforcement Learning for Trading

### Can pip install?
**YES**. `pip install finrl` installs v0.3.7, pure Python wheel.

### Is FinRL production-ready for A-shares?
**NO, not yet.** FinRL is a research and prototyping framework. Key production gaps:

| Gap | Detail |
|-----|--------|
| No live trading | No broker APIs, no order routing, no risk management built-in |
| Model instability | DDPG agents frequently collapse to "do nothing" (all-zero actions) |
| No regime detection | No concept drift detection or automatic model retraining triggers |
| Data pipeline | Relies on historical datasets; no real-time data integration |
| A-share specifics | T+1 settlement, short-selling restrictions, stamp duty not fully modeled |
| Reproducibility | High variance across training runs |

FinRL **does** have explicit A-share support (SSE 50, CSI 300) using Tushare data, with China-specific transaction costs and 100-share lot constraints.

### What specific feature helps AlphaPulse-A the most?
The **DRL environment framework** for comparing algorithms (DDPG, A2C, PPO, SAC, TD3). If AlphaPulse-A ever wants to explore RL-based dynamic position sizing or order execution optimization, FinRL provides the standardized environment and algorithm implementations.

### Concrete integration steps (3-5):

1. **Install FinRL** for research/experimentation only:
   ```bash
   pip install finrl
   ```

2. **Create experimental RL module** at `alphapulse/strategy/rl_agent.py` (flagged as experimental, not production):
   - Use FinRL's `StockTradingEnv` with A-share config (ticker_format="XXXXXX.SH", hundred_each_trade=True)
   - Train SAC or PPO agent (avoid DDPG due to collapse issues) on CSI 300 data
   - Run in `alphapulse/factors/experimental/` namespace

3. **Use RL for order execution optimization** (more practical than stock selection):
   - Given a set of selected stocks from existing condition-based strategies
   - Train RL agent to decide entry timing, position sizing, and exit timing
   - This is a more bounded, tractable problem than full stock selection

4. **Compare RL vs. existing strategies**: Run backtests comparing RL-generated signals against B1/Brick/Needle strategies over the same period. Document performance differences.

5. **Production readiness checklist** (before deploying any RL component):
   - [ ] Real-time data feed integration (akshare WebSocket or similar)
   - [ ] Broker API connectivity (vnpy CTP gateway)
   - [ ] Pre-trade risk checks integration
   - [ ] Model health monitoring (prediction distribution drift detection)
   - [ ] Automatic retraining pipeline
   - [ ] Paper trading for >= 3 months before live deployment

---

## 4. OpenBB -- Financial Data Platform

### Can pip install?
**YES**, but with a heavy footprint. `pip install openbb` installs v4.7.1 and triggers 30+ sub-packages (openbb-core, openbb-equity, openbb-fred, openbb-sec, etc.). The dependency tree includes `arch` (5.6.0, from source), `Quandl`, `alpha-vantage`, and many others. Install time is significant.

### Can we use OpenBB's data connectors instead of baostock?
**NO, not practically for A-shares.** OpenBB v4.x focuses on US/global markets. Its data provider ecosystem (Yahoo Finance, FMP, Intrinio, Polygon, FRED, SEC, etc.) does not include A-share-specific data sources like baostock, akshare, or Tushare.

However, OpenBB has value for:
- **US market benchmarks**: Fetch SPX/NDX data for comparison against A-share strategies
- **Macroeconomic data**: FRED, BLS, IMF, OECD data for regime analysis
- **The data provider abstraction pattern**: OpenBB's "connect once, consume everywhere" design is a good architectural reference for AlphaPulse-A's data layer

### What specific feature helps AlphaPulse-A the most?
The **data provider abstraction pattern**. AlphaPulse-A currently has a single data path (baostock/akshare -> CSV). OpenBB's design shows how to build a unified data interface with pluggable backends:

```python
from openbb import obb
# Single API, multiple backends
obb.equity.price.historical("AAPL", provider="yfinance")   # Yahoo
obb.equity.price.historical("AAPL", provider="fmp")        # FMP
obb.equity.price.historical("AAPL", provider="polygon")    # Polygon
```

This pattern can be replicated for A-share data sources (baostock, akshare, Tushare, JoinQuant).

### Concrete integration steps (3-5):

1. **Install OpenBB only if US benchmark data is needed**:
   ```bash
   pip install openbb  # Warning: heavy install (~50+ packages)
   ```

2. **Use OpenBB for macro/benchmark data**, not A-share primary data:
   ```python
   from openbb import obb
   
   # US benchmark for A-share strategy comparison
   sp500 = obb.equity.price.historical("SPY", start_date="2020-01-01").to_dataframe()
   
   # Macro data for regime classification
   gdp = obb.economy.gdp.fred(series_id="GDP").to_dataframe()
   cpi = obb.economy.cpi.fred(series_id="CPIAUCSL").to_dataframe()
   ```

3. **Adopt OpenBB's provider abstraction pattern for AlphaPulse-A's data layer**:
   Create `alphapulse/data/provider.py`:
   ```python
   class DataProvider:
       def get_daily(self, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
           raise NotImplementedError
   
   class BaostockProvider(DataProvider): ...
   class AKShareProvider(DataProvider): ...
   class TushareProvider(DataProvider): ...
   ```
   This allows swapping data sources without changing factor/strategy code.

4. **Create `scripts/compare_data_sources.py`**: Fetch the same symbol from baostock, akshare, and Tushare, then compare OHLCV values to identify inconsistencies and choose the most reliable source.

5. **Skip OpenBB if the dependency cost outweighs the benefit**. For A-share-only work, akshare + baostock is sufficient. OpenBB adds value only if you need US market benchmarks or macro data for regime analysis.

---

## 5. yfinance -- Yahoo Finance Data

### Can pip install?
**YES**. `pip install yfinance` installs v1.3.0. Has cp314 wheels for websockets dependency. Already has compatible versions of pandas, numpy, requests, beautifulsoup4, and curl_cffi installed in the venv.

### Can we use yfinance as backup data source?
**NOT recommended as a primary or even backup source in 2026.** Yahoo Finance has paywalled historical data since early 2025 (requires Gold tier: $50/month or $500/year). Free API access is unreliable:

| Issue | Timeline | Impact |
|-------|----------|--------|
| Historical data paywall | Early 2025 | Free tier no longer serves >1 month of history |
| Cookie/crumb validation upgrade | Sept 2025 | Scripts without persistent cookies return 401 Unauthorized |
| TCP RST blocking (China) | Ongoing | Yahoo API connections frequently reset from within China |

### What specific feature helps AlphaPulse-A the most?
**None for A-shares.** yfinance never had meaningful A-share coverage. Its value was always US/global equities. For A-share backup data, use **akshare** (already installed, v1.18.60) plus **Tushare** as secondary.

### Concrete recommendation:

**Do not integrate yfinance.** Use this data source hierarchy instead:

| Priority | Source | Purpose | pip status |
|----------|--------|---------|------------|
| Primary | **akshare** | A-share daily OHLCV, fundamentals, industry | Already installed (v1.18.60) |
| Secondary | **baostock** | A-share historical data validation | Already installed (v0.9.1) |
| Tertiary | **Tushare Pro** | Factor data, financial statements | `pip install tushare` (needs API token) |
| Benchmark | **OpenBB** (optional) | US market benchmarks, macro data | Heavy install, see Section 4 |
| Legacy | **yfinance** | US stock data only, paywalled | Avoid |

For US stock data specifically, use **defeatbeta-api** (free, no rate limits, Hugging Face-backed) or **EODHD** (free tier: 20 calls/day) as alternatives to yfinance.

---

## 6. ML for Trading (Stefan Jansen) -- Book Companion Code

### Can pip install?
**NO**, this is not a pip package. It is a GitHub repository (`stefan-jansen/machine-learning-for-trading`, ~12,900 stars) containing 150+ Jupyter notebooks and Python modules organized by topic. Install via:

```bash
git clone https://github.com/stefan-jansen/machine-learning-for-trading.git
cd machine-learning-for-trading
pip install -r requirements.txt
```

### Any reusable modules?
**YES**, the repository is explicitly designed as a modular toolkit. Each chapter directory is self-contained and reusable:

| Chapter | Module | Reusable Components for AlphaPulse-A |
|---------|--------|--------------------------------------|
| 02 | `market_and_fundamental_data` | Market data APIs, SEC/XBRL parsing, data storage (HDF5/Parquet) |
| 04 | `alpha_factor_research` | **Factor engineering patterns**, feature importance, IC analysis |
| 05 | `strategy_evaluation` | **Portfolio optimization** (mean-variance, Black-Litterman, HRP), performance metrics |
| 06 | `machine_learning_process` | Time-series cross-validation, walk-forward validation |
| 07 | `linear_models` | Linear factor models, regression-based alpha |
| 08 | `ml4t_workflow` | **End-to-end ML backtesting workflow**, vectorized backtester |
| 11 | `decision_trees_random_forests` | Tree-based factor importance analysis |
| 12 | `gradient_boosting_machines` | XGBoost/LightGBM/CatBoost for alpha prediction |
| 18 | `convolutional_neural_nets` | CNN for time-series pattern recognition |
| 22 | `deep_reinforcement_learning` | DRL trading agents with TensorFlow |

### What specific feature helps AlphaPulse-A the most?
Two things:

1. **Chapter 05 -- Portfolio optimization**: AlphaPulse-A currently uses fixed 20% single-stock / max-5-holdings position sizing. Stefan Jansen's code includes Hierarchical Risk Parity (HRP), mean-variance optimization, and Black-Litterman -- all applicable to improving position sizing.

2. **Chapter 04 -- Factor engineering patterns**: The `alpha_factor_research` chapter provides a template for systematic factor research that AlphaPulse-A's factor registry can adopt: factor computation -> IC analysis -> factor combination -> signal generation. This fills the gap between the current 13 factors and a rigorous factor research workflow.

### Concrete integration steps (3-5):

1. **Clone the repo as a reference (not a dependency)**:
   ```bash
   git clone https://github.com/stefan-jansen/machine-learning-for-trading.git /Users/qiushixuan/cc/ml-for-trading-ref
   ```
   Use it as a study reference and code-pattern source; do NOT import it as a Python package.

2. **Adopt the time-series cross-validation pattern from Chapter 06**:
   Create `alphapulse/utils/cross_validation.py`:
   ```python
   def purged_walk_forward_split(
       data: pd.DataFrame,
       n_splits: int = 5,
       train_size: int = 252 * 3,  # 3 years
       test_size: int = 252,       # 1 year
       purge_size: int = 21        # 1 month purge gap
   ) -> list[tuple]:
       """Walk-forward split with purge gap to prevent data leakage."""
   ```
   This is essential for honest model evaluation in ML-based strategies.

3. **Integrate portfolio optimization from Chapter 05**:
   Create `alphapulse/utils/portfolio_optimizer.py`:
   - `hrp_weights(returns: pd.DataFrame) -> pd.Series` -- Hierarchical Risk Parity
   - `min_variance_weights(cov: pd.DataFrame) -> pd.Series`
   - `black_litterman_weights(prior, views, confidence) -> pd.Series`
   Use these to replace the static 20%/max-5 position sizing with dynamic, risk-aware allocation.

4. **Borrow the factor engineering workflow from Chapter 04**:
   - Factor computation -> forward return alignment -> IC calculation -> factor ranking -> signal construction
   - Align with AlphaPulse-A's existing `compute_factor()` interface
   - This standardizes factor development so new factors (including Alpha158 imports) follow a consistent evaluation path

5. **Adopt HDF5/Parquet storage from Chapter 02**:
   - Current data storage is CSV (`data/day/{symbol}.csv`)
   - Add a Parquet-backed data layer for faster queries and columnar access:
   ```python
   # In alphapulse/utils/data_loader.py
   def load_all_stocks_parquet(data_dir: str = "data/parquet") -> pd.DataFrame:
       """Load all A-share stocks from Parquet with multi-index (date, symbol)."""
   ```

---

## 7. Integration Priority Matrix

| Priority | Project | Feature | Effort | Value | Python 3.14? |
|----------|---------|---------|--------|-------|--------------|
| **P0** | Qlib | Alpha158 factor library (via Alpha158DL) | Medium | High | Needs 3.12 env |
| **P1** | ML for Trading | Portfolio optimization (HRP/mean-variance) | Low-Medium | High | N/A (code ref) |
| **P1** | ML for Trading | Time-series cross-validation | Low | High | N/A (code ref) |
| **P1** | Qlib | LightGBM stock ranking pipeline | Medium-High | High | Needs 3.12 env |
| **P2** | Backtrader | Cross-validation of VeighNa backtests | Low | Medium | YES |
| **P2** | ML for Trading | Factor engineering workflow (Ch.04) | Medium | Medium | N/A (code ref) |
| **P3** | FinRL | RL order execution experiment | High | Low-Medium | YES |
| **P3** | OpenBB | US benchmark/macro data | Low | Low | YES (heavy) |
| **Skip** | yfinance | Backup data source | N/A | None | YES (deprecated) |

---

## 8. Recommended First Sprint (2 Weeks)

**Goal**: Integrate the highest-value features with the least friction.

### Week 1: Qlib Alpha158 Factors

1. Create Python 3.12 sidecar environment: `.venv-312` alongside `.venv`
2. `pip install pyqlib` (v0.9.7) in the 3.12 env
3. Write `alphapulse/factors/qlib_bridge.py` -- a bridge that runs in the 3.12 env and exposes Alpha158/Alpha360 factor computation via subprocess or RPC
4. Alternative (simpler): Extract Alpha158 expression formulas from Qlib source and re-implement them in pure pandas/numpy in the 3.14 env. This avoids the dual-environment complexity. Source formulas are in `qlib/contrib/data/loader.py`.
5. Register Alpha158 factors in `factor_registry.py` as batch factor generator
6. Run IC/ICIR analysis on all factors (existing 13 + Alpha158)

### Week 2: Portfolio Optimization + Cross-Validation

1. Adopt portfolio optimization code from stefan-jansen/ml-for-trading Ch.05
2. Write `alphapulse/utils/portfolio_optimizer.py` with HRP and min-variance
3. Write `alphapulse/utils/cross_validation.py` with purged walk-forward split
4. Run cross-validation comparing VeighNa engine vs. backtrader on the same strategy logic
5. Document any Metric discrepancies in `reports/cross_validation_report.md`

---

## Sources

- [Microsoft Qlib PyPI](https://pypi.org/project/pyqlib/) -- v0.9.7, Python 3.8-3.12 only
- [Qlib GitHub Issue #315](https://github.com/microsoft/qlib/issues/315) -- How to extract Alpha158/360 from DataFrame
- [Qlib Alpha158 Factor Documentation](https://blog.gitcode.com/796f9be4d0a177bbd3e8657ba46f7abb.html)
- [Backtrader GitHub](https://github.com/mementum/backtrader) -- v1.9.78.123, stable but unmaintained
- [Backtrader-slim GitHub](https://github.com/dennisdeh/backtrader-slim) -- Modernized fork for Python 3.10+
- [FinRL GitHub](https://github.com/AI4Finance-Foundation/FinRL) -- v0.3.7, research framework
- [FinRL A-Share Documentation](https://deepwiki.com/AI4Finance-Foundation/FinRL-Tutorials/5.2-international-markets-and-alternative-assets)
- [OpenBB Platform](https://docs.openbb.co/) -- v4.7.1, US/global focus
- [yfinance GitHub](https://github.com/ranaroussi/yfinance) -- v1.3.0, deprecated for production (Yahoo paywall)
- [2026 Python Quant Data Sources Audit](https://juejin.cn/post/7598020609282392098) -- yfinance status and alternatives
- [Stefan Jansen ML for Trading](https://github.com/stefan-jansen/machine-learning-for-trading) -- 2nd Ed., 150+ notebooks
