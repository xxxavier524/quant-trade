# Top 10 GitHub Open-Source Projects for AlphaPulse-A Enhancement

> Generated: 2026-05-16 | Target: AlphaPulse-A | Python: 3.14.3  
> Goal: Identify and integrate the best open-source features to enhance our A-share quant trading system.

---

## Quick Summary: Python 3.14 Compatibility Matrix

| # | Project | Stars | pip Package | v3.14 Install | Key Value |
|---|---------|-------|------------|--------------|-----------|
| 1 | OpenBB | 67K+ | `openbb` | PENDING | Data provider abstraction pattern |
| 2 | QuantConnect Lean | 19K | N/A (C# engine) | N/A | Reference architecture, CLI tooling |
| 3 | Microsoft Qlib | 43K+ | `pyqlib` | **FAILED** (no cp314) | Alpha158/360 factors, ML models, IC/ICIR |
| 4 | Backtrader | 21K+ | `backtrader` | **YES** (1.9.78.123) | Cross-validation engine (constrained) |
| 5 | TradingAgents | 71K+ | `tradingagents` | **YES** (0.6.0) | Multi-agent LLM signal generation |
| 6 | Riskfolio-Lib | 4K+ | `riskfolio-lib` | **YES** (7.2.1) | Black-Litterman, CVaR, HRP, HERC, NCO |
| 7 | yfinance | 23K+ | `yfinance` | **YES** (1.3.0) | Already integrated, rate-limited |
| 8 | FinanceToolkit | 4.6K+ | `financetoolkit` | **YES** (2.0.7) | 180+ financial ratios as new factors |
| 9 | vectorbt | 7.5K+ | `vectorbt` | **YES** (0.28.2) | Vectorized backtest (100x faster grid search) |
| 10 | lightweight-charts | 15.7K+ | npm `lightweight-charts` | **YES** (v5.2.0) | Replace Chart.js with TradingView charts |

---

## 1. OpenBB (OpenBB-finance/OpenBBTerminal)

### Vital Statistics
- **Stars**: 67,400+ (fastest-growing finance OSS in 2026)
- **Latest version**: v4.5.0
- **Python**: 3.10+ minimum
- **License**: MIT
- **Pip install**: `pip install "openbb[all]"` (heavy: 50+ sub-packages)

### Core Features
- Unified API for 100+ financial data sources (equities, options, crypto, FX, fixed income, macro)
- Built-in technical analysis, fundamentals, AI/ML (LSTM, OpenBB Copilot)
- MCP Server support (allows AI agents like Claude to query financial data directly)
- Multi-interface: CLI, Python SDK, REST API, Excel, MCP
- Plugin architecture for custom extensions

### Relevance to AlphaPulse-A
**LOW for A-share data; MEDIUM for architecture pattern.**

OpenBB v4.x focuses on US/global markets. Its data provider ecosystem (Yahoo, FMP, Polygon, FRED, SEC) does not include A-share sources like akshare, baostock, or Tushare. However, two pieces are valuable:

1. **Data provider abstraction pattern** -- "connect once, consume everywhere" design is a useful reference for AlphaPulse-A's data layer.
2. **US market benchmarks via MCP** -- Fetch SPX/NDX data for comparison against A-share strategies.
3. **Macro data** -- FRED/BLS/OECD data for regime analysis.

### Verdict
**Skip primary integration.** The dependency cost (50+ packages) outweighs the benefit for an A-share-only system. Borrow the provider abstraction pattern for `alphapulse/data/provider.py`. Use OpenBB only if US benchmark comparisons become necessary.

---

## 2. QuantConnect Lean (QuantConnect/Lean)

### Vital Statistics
- **Stars**: ~19,000
- **Language**: C# (94%) + Python API (5.7%)
- **License**: Apache 2.0
- **Last update**: April 2026 (actively maintained)
- **Install**: `pip install lean` (CLI only), Docker for engine

### Core Features
- Event-driven algorithmic trading engine (tick/sec/min/hour/day resolution)
- Multi-asset: US Equities, Options, Futures, Forex, Crypto
- 20+ broker integrations (Interactive Brokers, Alpaca, Coinbase, Binance, etc.)
- 400TB+ historical data, 40+ alternative data vendors
- Cloud + local hybrid deployment
- CLI: `lean project-create`, `lean backtest`, `lean deploy`
- Research: Cloud-hosted Jupyter notebooks
- AI Assistant "Mia" for natural-language strategy design
- FIX 5.0 SP2 for institutional clients
- Modular: Alpha/Risk/Execution/Portfolio models

### Relevance to AlphaPulse-A
**MEDIUM as architectural reference; LOW for direct integration.**

Lean is primarily a C# engine with Python bindings. It does NOT support A-share markets natively (no CTP gateway, no CSI 300/SSE data). Key architectural patterns worth studying:

1. **Modular alpha model design**: Separate Alpha Construction, Risk Management, Execution, Portfolio Construction modules -- more sophisticated than AlphaPulse-A's current monolithic strategy approach.
2. **CLI tooling**: `lean project-create`, `lean backtest`, `lean optimize` -- a unified CLI for the full quant workflow.
3. **Research environment**: Jupyter-based research with direct engine API access.

### Verdict
**Do not integrate directly.** The C# core and US-market focus make it unsuitable for A-share quant. Study the architectural patterns for a future v2 refactor of AlphaPulse-A's engine. The modular alpha/risk/execution separation is the key takeaway.

---

## 3. Microsoft Qlib (microsoft/qlib)

### Vital Statistics
- **Stars**: ~43,000 (#1 quant OSS on GitHub)
- **Latest version**: v0.9.7
- **Language**: Python
- **License**: MIT
- **Pip install on Python 3.14**: **FAILED** -- wheels only for cp38-cp312

### Core Features
- Alpha158: 158 engineered technical factors (K-bar, price ratios, rolling stats)
- Alpha360: 360 raw OHLCV sequence features (60d x 6 fields) for DL models
- Model Zoo: 30+ models (LightGBM, XGBoost, CatBoost, TabNet, Transformer, LSTM, GRU, TCN, TRA, HIST, GATs, DoubleEnsemble)
- QlibRL: Reinforcement learning (PPO, OPDS, DQN) for continuous decisions
- Point-in-time database (eliminates look-ahead bias)
- IC/ICIR/RankIC factor analysis module
- Binary data format (50x faster than MySQL)
- YAML-driven `qrun` one-click pipeline (data -> train -> backtest -> report)
- Portfolio optimization module
- RD-Agent: LLM-driven autonomous factor discovery and model optimization (NeurIPS 2025)
- MLflow/W&B experiment tracking
- Nested decision framework (multi-granularity investment decisions)

### Relevance to AlphaPulse-A
**VERY HIGH -- but blocked by Python 3.14 wheel availability.**

The Python 3.14 incompatibility is the key blocker. Solutions:

1. **Python 3.12 sidecar environment**: Create `.venv-312` alongside `.venv`, install `pyqlib` there, and bridge via subprocess or IPC.
2. **Re-implement Alpha158 in pure pandas**: Extract expression formulas from Qlib source and reimplement in the 3.14 env. This avoids dual-environment complexity.
3. **Use vnpy.alpha** (VeighNa's ML module that bundles Alpha158 factors): This is a lighter-weight alternative.

### Specific Features Worth Extracting
| Feature | Effort | Impact | Approach |
|---------|--------|--------|----------|
| Alpha158 factors | Medium | HIGH | Reimplement 158 factor formulas in pure pandas |
| IC/ICIR analysis | Low | HIGH | Replicate the IC calculation module |
| LightGBM ranking pipeline | Medium | HIGH | Standalone `pip install lightgbm` + custom ranking logic |
| RD-Agent factor discovery | High | P3 | Requires LLM API access; future experiment |

### Verdict
**P0 priority -- but work around Python 3.14 constraint.** Reimplement the Alpha158 factor formulas in pure pandas/numpy as `alphapulse/factors/alpha158.py`. This is the single highest-impact feature: going from 13 custom factors to 158 battle-tested A-share factors with known IC/ICIR characteristics.

---

## 4. Backtrader (mementum/backtrader)

### Vital Statistics
- **Stars**: ~21,200
- **Latest release**: v1.9.74.123 (May 30, 2019)
- **Status**: **UNMAINTAINED** (no updates since 2019)
- **Pip install on Python 3.14**: **YES** (1.9.78.123)

### Core Features
- Event-driven backtesting with `Cerebro` architecture
- 100+ built-in technical indicators
- Multi-timeframe support
- Parameter optimization: `cerebro.optstrategy()`
- Built-in analyzers: Sharpe, Drawdown, TimeReturn, SQN, TradeAnalyzer
- Multiple order types: Market, Limit, Stop, StopLimit, StopTrail, OCO
- Professional plotting: `cerebro.plot()`

### Relevance to AlphaPulse-A
**CONSTRAINED by CLAUDE.md.** The project constraint states: "回测框架仅 VeighNa (vnpy)，不接受 backtrader" (backtesting framework only VeighNa, does not accept backtrader).

However, backtrader can still serve as:
1. **Cross-validation benchmark**: Run the same strategy logic through backtrader and compare metrics against VeighNa. Flag discrepancies >5%.
2. **Parameter grid search accelerator**: `cerebro.optstrategy()` handles Cartesian product automatically. Run parameter sweeps (shrink_ratio x j_threshold x K) in a dedicated validation script.
3. **Multi-timeframe exploration**: Test strategies that use both daily and intraday signals -- a capability AlphaPulse-A's engine lacks.

### Verdict
**Use as cross-validation tool only, not as primary engine.** Backtrader is unmaintained and single-threaded (slow on large datasets). The CLAUDE.md constraint is appropriate -- VeighNa is the better choice for production A-share backtesting. Use backtrader in `scripts/cross_validate_backtrader.py` for one-off validation runs.

---

## 5. TradingAgents (TauricResearch/TradingAgents)

### Vital Statistics
- **Stars**: 71,400+ (exploded from 0 to 71K in ~17 months)
- **Latest version**: v0.6.0
- **Python**: 3.10+
- **License**: Research/custom
- **Pip install on Python 3.14**: **YES** (0.6.0)
- **Paper**: arXiv 2412.20138

### Core Features
- **4-layer multi-agent architecture** simulating a hedge fund's full investment research chain:
  - **Analyst Team** (4 agents): Fundamental, Sentiment, News, Technical analysts working in parallel
  - **Researcher Team** (2 agents): Bull vs. Bear structured debate (devil's advocate system)
  - **Trader Agent**: Synthesizes bull/bear debate into structured trading proposals
  - **Risk Manager + Portfolio Manager**: 3-tier risk assessment (Aggressive/Neutral/Conservative) -> final decision
- Supports: OpenAI GPT, Gemini, Claude, Grok, DeepSeek, Qwen, GLM, Ollama local models
- Built on LangGraph for stateful multi-agent orchestration
- Natural language output with structured trading decisions

### Relevance to AlphaPulse-A
**HIGH -- but requires LLM API access.**

The multi-agent approach directly complements AlphaPulse-A's signal generation pipeline:
1. **Signal quality enhancement**: Use TradingAgents to validate/override condition-based signals with LLM reasoning
2. **News/sentiment integration**: Analyst agents can process Chinese financial news (Caixin, Securities Times, etc.)
3. **Risk-aware position sizing**: The built-in risk manager provides 3-tier assessment that maps to AlphaPulse-A's position limits
4. **Explainable decisions**: Natural language reasoning for every trade decision -- better than opaque condition-combo signals

### Integration Architecture
```
AlphaPulse-A Strategy Signals
        |
        v
TradingAgents Analyst Team (analyze stock + market context)
        |
        v
TradingAgents Bull/Bear Debate (validate signal)
        |
        v
TradingAgents Risk Manager (adjust position size)
        |
        v
Enhanced Signal (with reasoning + risk tier) -> VeighNa Backtest/Execution
```

### Verdict
**P1 priority -- integrate as signal enhancement layer.** Write `alphapulse/adapters/tradingagents_adapter.py` that:
1. Takes AlphaPulse-A strategy signals as input
2. Wraps TradingAgents' analyst team for context-aware validation
3. Uses the risk assessment tier to dynamically adjust position sizing
4. Returns enhanced signals with natural language reasoning
5. Requires LLM API key (DeepSeek recommended, already used by AlphaPulse-A)

---

## 6. Riskfolio-Lib (dcajasn/Riskfolio-Lib)

### Vital Statistics
- **Stars**: ~4,000
- **Latest version**: v7.2.1
- **Python**: 3.10+
- **License**: BSD-3-Clause
- **Pip install on Python 3.14**: **YES** (7.2.1)

### Core Features
- **24+ convex risk measures**: CVaR, Tail Gini, RLVaR, CDaR, Mean Absolute Deviation, Semi-Variance, etc.
- **Modern portfolio construction methods**:
  - Mean-Variance Optimization (Markowitz)
  - **Black-Litterman** (incorporate investor views with market equilibrium)
  - **Hierarchical Risk Parity (HRP)**
  - **HERC** (Hierarchical Equal Risk Contribution)
  - **Nested Clustered Optimization (NCO)**
  - Risk Parity / Risk Budgeting
- Built on CVXPY: supports LP, QP, SOCP, SDP, exponential cone programming
- Integrates with pandas, scikit-learn, arch (volatility modeling), networkx

### Relevance to AlphaPulse-A
**VERY HIGH.** This is the single highest-impact, lowest-effort integration.

AlphaPulse-A currently uses crude fixed-size position allocation:
- Single stock <= 20% of capital
- Maximum 5 holdings
- Equal weight among selected stocks

This is the weakest part of the system. Riskfolio-Lib provides production-grade portfolio optimization:

| Current Approach | Riskfolio-Lib Replacement | Benefit |
|-----------------|--------------------------|---------|
| Equal weight | Mean-Variance optimal weights | Risk-adjusted allocation |
| Fixed 20% cap | CVaR-based risk budgets | Dynamic position sizing based on tail risk |
| No correlation consideration | Hierarchical Risk Parity | Clustered allocation accounting for sector correlation |
| No factor views | Black-Litterman | Incorporate factor-based return views into allocation |
| Manual rebalancing | HERC/NCO rebalancing | Automated risk-parity rebalancing |

### Key API Surface for Integration

```python
import riskfolio as rp

# Black-Litterman: incorporate our factor views
port = rp.BlackLitterman(
    mu_bench=market_implied_returns,  # from CAPM
    S_bench=cov_matrix,
    P=views_matrix,     # our factors' return predictions
    Q=views_values,     # expected returns from views
    delta=2.5           # risk aversion
)

# CVaR optimization: minimize tail risk
port = rp.Portfolio(returns=returns)
port.assets_stats(method_mu='hist', method_cov='hist')
w = port.optimization(
    model='CVaR',       # Conditional Value at Risk
    rm='CVaR',
    alpha=0.05           # 95% confidence
)

# Hierarchical Risk Parity: factor-based clustering
w = port.optimization(
    model='HRP',
    codependence='pearson',
    rm='MV'
)
```

### Verdict
**P0 priority -- integrate immediately.** Write `alphapulse/adapters/riskfolio_adapter.py` with:
1. `compute_bl_weights()` -- Black-Litterman with factor-derived views
2. `compute_cvar_weights()` -- CVaR-based risk budgeting
3. `compute_hrp_weights()` -- Hierarchical Risk Parity
4. Replace the static 20%/max-5 allocation in `backtest_utils.py` with dynamic weights

---

## 7. yfinance (ranaroussi/yfinance)

### Vital Statistics
- **Stars**: ~23,000
- **Latest version**: v1.3.0
- **License**: Apache-2.0
- **Pip install on Python 3.14**: **YES** (1.3.0, already installed)

### Status in AlphaPulse-A
**Already integrated** via `alphapulse/utils/yfinance_adapter.py`. However, yfinance is rate-limited from this network (429 Too Many Requests) and Yahoo Finance paywalled historical data since early 2025.

### Verdict
**No further integration needed.** The existing adapter is sufficient as a fallback. Primary A-share data source remains akshare (v1.18.60). yfinance should only be used for US-listed Chinese ADRs or global benchmark data when not rate-limited.

---

## 8. FinanceToolkit (JerBouma/FinanceToolkit)

### Vital Statistics
- **Stars**: ~4,634
- **Latest version**: v2.0.7
- **Language**: Python
- **License**: MIT
- **Pip install on Python 3.14**: **YES** (2.0.7)

### Core Features
- **180+ financial ratios** across: Efficiency, Liquidity, Profitability, Solvency, Valuation
- **Fully transparent calculations** -- every formula openly documented (unlike Bloomberg/Morningstar)
- Multi-asset: Equities, Options, Currencies, Cryptocurrencies, ETFs, Mutual Funds, Indices, Commodities, Fixed Income, Economic Indicators
- Modules: Toolkit (core), Discovery, Ratios, Models, Options, Technicals, Risk, Performance, Economics, Fixed Income, Portfolio
- Companion: FinanceDatabase (300K+ symbols, ~5K stars)

### Relevance to AlphaPulse-A
**MEDIUM-HIGH.** The 180+ financial ratios can be integrated as new fundamental factors.

AlphaPulse-A currently has **only technical/price-based factors** (13 total: N_STRUCT, VOL_RED_GREEN, KDJ, MACD, etc.). It completely lacks fundamental factors. FinanceToolkit provides:

| Ratio Category | Count | Example Factors for AlphaPulse-A |
|---------------|-------|----------------------------------|
| Profitability | ~30 | ROE, ROA, Gross Margin, Net Margin |
| Valuation | ~25 | P/E, P/B, EV/EBITDA, P/S, PEG |
| Liquidity | ~15 | Current Ratio, Quick Ratio, Cash Ratio |
| Solvency | ~20 | Debt/Equity, Interest Coverage, Debt/EBITDA |
| Efficiency | ~20 | Asset Turnover, Inventory Turnover |

### Integration Challenge
FinanceToolkit requires financial statement data (income statement, balance sheet, cash flow) from FinancialModelingPrep (FMP) API, which requires a free API key. For A-share stocks, financial data must come from akshare or Tushare, then be mapped to FinanceToolkit's ratio calculation engine.

### Verdict
**P1 priority.** Write `alphapulse/adapters/financetoolkit_adapter.py`:
1. Use akshare/Tushare to fetch A-share financial statements
2. Feed them through FinanceToolkit's ratio calculation
3. Convert 180+ ratios into AlphaPulse-A factor format (`compute(data) -> pd.Series`)
4. Register fundamental factors in `FACTOR_REGISTRY` as a new category

---

## 9. vectorbt (polakowo/vectorbt)

### Vital Statistics
- **Stars**: ~7,500
- **Latest version**: v1.0.0 (April 2026) / v0.28.2 on PyPI
- **Language**: Python (95.6%) + Rust (4.2%)
- **License**: GPL v3.0
- **Pip install on Python 3.14**: **YES** (0.28.2)

### Core Features
- **Vectorized backtesting**: Every strategy config is a column in a 2D matrix -- thousands of parameter combos simultaneously
- **3-layer acceleration**: NumPy broadcasting (10-100x) + Numba JIT (50-500x) + Rust engine (no JIT warm-up)
- **Pandas-native API**: Custom `.vbt` accessor on Series/DataFrames
- **Portfolio simulation**: `Portfolio.from_signals()`, `from_orders()`, `from_order_func()`
- **IndicatorFactory**: Build custom indicators, integrates TA-Lib/Pandas TA
- **Robustness testing**: Walk-forward optimization, ML label generation
- **Interactive visualization**: Plotly dashboards, Jupyter widgets
- **Performance analytics**: Sharpe, max drawdown, win rate, QuantStats integration
- **Data connectors**: Yahoo Finance, Binance, CCXT, Alpaca

### Relevance to AlphaPulse-A
**VERY HIGH for backtest performance.**

The current backtest engine runs single-threaded, bar-by-bar simulation. vectorbt can accelerate parameter grid search by **100-1000x** by broadcasting all parameter combinations across columns:

```python
import vectorbt as vbt
import pandas as pd

# Current: manual grid search (hours)
# for sr in [0.2, 0.25, 0.3, 0.4]:
#     for jt in [8, 10, 13, 15]:
#         for k in [1.5, 2.0, 2.5, 3.0]:
#             run_single_backtest(sr, jt, k)  # 64 separate runs

# vectorbt: all 64 combos in ONE call (seconds)
signals = generate_signal_matrix(close, shrink_ratios, j_thresholds, Ks)
portfolio = vbt.Portfolio.from_signals(
    close, entries, exits,
    freq="1D",
    init_cash=100000,
    slippage=0.001,     # 0.1% buy
    fees=0.00025,        # 0.025% commission
    min_fee=5.0
)
stats = portfolio.stats()  # All 64 configs compared at once
```

### Key Benefits for AlphaPulse-A Phase 6 (Parameter Grid Search)
| Current Approach | vectorbt Approach | Speedup |
|-----------------|-------------------|---------|
| 64 sequential backtests (hours) | 1 vectorized call (seconds) | ~100-500x |
| Manual result comparison | Built-in stats() aggregation | 10x faster analysis |
| Single metric focus | Multi-dimensional Pareto frontier | More thorough |

### Verdict
**P0 priority for backtest acceleration.** Write `alphapulse/adapters/vectorbt_adapter.py`:
1. `vbt_grid_search()` -- Wraps parameter grid search in vectorized form
2. `vbt_signal_to_portfolio()` -- Converts AlphaPulse-A signals to vbt Portfolio
3. `vbt_compare_engines()` -- Cross-validates vbt results vs VeighNa results
4. Use as Phase 6 (parameter grid search) accelerator, not as primary engine

**IMPORTANT**: vectorbt should COMPLEMENT VeighNa, not REPLACE it. The CLAUDE.md constraint requires VeighNa as the primary backtest engine. vectorbt serves as:
- Pre-screening: Quickly eliminate bad parameter combos
- Cross-validation: Verify VeighNa results
- Speed: Reduce grid search from hours to seconds

---

## 10. TradingView Lightweight Charts (tradingview/lightweight-charts)

### Vital Statistics
- **Stars**: ~15,700
- **Latest version**: v5.2.0 (April 2026)
- **Language**: TypeScript (47.5%) + JavaScript (31.1%)
- **License**: Apache 2.0
- **Install**: `npm install lightweight-charts` or CDN `<script>` tag
- **Used by**: 15,100+ projects

### Core Features
- **Candlestick/OHLC charts** rendered on HTML5 Canvas (high performance)
- Line series, area charts, histograms, baseline charts
- Time/price markers, crosshair, zoom/pan
- Custom series plugin system
- Extremely lightweight: minimal bundle size
- React, Vue, SolidJS, Kotlin (Android) wrappers available
- Professional-grade: same rendering as TradingView platform

### Current AlphaPulse-A Frontend
The existing frontend (`frontend/index.html`) uses **Chart.js (v4.4.0)** loaded from CDN:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
```

Chart.js is a general-purpose charting library. It does NOT natively support:
- Candlestick charts (requires hacky OHLC overlay plugins)
- Professional financial chart UX (crosshair, price axis, volume profile)
- Multi-pane layouts (price above, volume below, indicators below)
- Time-based navigation (quick zoom to 1M/3M/1Y/ALL)

### Benefits of Switching to Lightweight Charts

| Feature | Chart.js | Lightweight Charts |
|---------|----------|-------------------|
| Candlestick charts | Plugin-based (fragile) | Native, first-class |
| Professional crosshair | Manual | Built-in |
| Volume sub-pane | Manual grid | Native pane system |
| Time navigation | Manual buttons | Built-in toolbar |
| Dark theme | Custom CSS | Built-in theme system |
| Bundle size | ~60KB | ~45KB (lighter!) |
| Zoom/pan | Plugin | Built-in, smooth |
| Community trust | General-purpose | TradingView (industry standard) |

### Integration Approach

Replace Chart.js with lightweight-charts via CDN:
```html
<!-- Before -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>

<!-- After -->
<script src="https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script>
```

The migration requires rewriting chart initialization code but the HTML/CSS layout remains the same. The Chart.js canvas elements are replaced with lightweight-charts containers.

### Verdict
**P1 priority -- high UX impact, moderate effort.** Write a migration guide at `frontend/lightweight_charts_migration.md` and create a new `frontend/index_lwc.html` that replaces Chart.js with lightweight-charts. The improved professional trading UI directly benefits strategy analysis and backtest visualization.

---

## Integration Priority Matrix

| Priority | Project | Feature | Effort | Impact | P3.14 OK? |
|----------|---------|---------|--------|--------|-----------|
| **P0** | Riskfolio-Lib | Black-Litterman + CVaR + HRP allocation | Low | VERY HIGH | YES |
| **P0** | vectorbt | Vectorized grid search accelerator | Medium | VERY HIGH | YES |
| **P1** | FinanceToolkit | 180+ fundamental ratio factors | Medium | HIGH | YES |
| **P1** | TradingAgents | Multi-agent LLM signal validation | Medium | HIGH | YES |
| **P1** | lightweight-charts | TradingView frontend upgrade | Medium | HIGH | YES (npm) |
| **P1** | Qlib | Alpha158 factor reimplementation | High | VERY HIGH | NO (3.12 env) |
| **P2** | Backtrader | Cross-validation of VeighNa | Low | MEDIUM | YES |
| **P2** | OpenBB | Data provider abstraction pattern | Low | LOW | PENDING |
| **P3** | Lean | Modular engine architecture reference | N/A | LOW | N/A |
| **Skip** | yfinance | Already integrated, rate-limited | N/A | NONE | YES |

---

## Recommended Implementation Sprint (2 Weeks)

### Week 1: Portfolio Optimization + Backtest Speed

1. **Day 1-2: Riskfolio-Lib adapter** (`alphapulse/adapters/riskfolio_adapter.py`)
   - Black-Litterman weight computation with factor-derived views
   - CVaR-based position sizing replacing static 20% cap
   - HRP clustering for correlation-aware allocation
   - Integration with existing `backtest_utils.py`

2. **Day 3-4: vectorbt adapter** (`alphapulse/adapters/vectorbt_adapter.py`)
   - Convert AlphaPulse-A factor signals to vbt signal matrix
   - Vectorized grid search for Phase 6 parameters
   - Cross-validation report against VeighNa results

3. **Day 5: FinanceToolkit adapter** (`alphapulse/adapters/financetoolkit_adapter.py`)
   - A-share financial statement fetching via akshare
   - 180+ ratio computation as factor candidates
   - IC/ICIR screening to identify top fundamental factors
   - Register in FACTOR_REGISTRY

### Week 2: Signal Enhancement + Frontend

4. **Day 6-7: TradingAgents adapter** (`alphapulse/adapters/tradingagents_adapter.py`)
   - Wrap multi-agent analysis pipeline
   - DeepSeek integration (same LLM as AlphaPulse-A's model routing)
   - Signal validation + risk tier output
   - Unit test with mock LLM responses

5. **Day 8-9: Lightweight Charts migration**
   - `frontend/lightweight_charts_migration.md` guide
   - New `frontend/index_lwc.html` with candlestick + indicators
   - Side-by-side comparison: Chart.js vs lightweight-charts

6. **Day 10: Integration testing + report**
   - End-to-end test: signals -> portfolio optimization -> backtest
   - Performance benchmarks: vbt grid search vs manual
   - Final report append to `progress_log.md`

---

## Key Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Qlib Python 3.14 incompatibility | Certain (no cp314 wheels) | Reimplement Alpha158 formulas in pure pandas; dual venv as fallback |
| TradingAgents LLM API costs | High | Use DeepSeek (cheaper than GPT-4), implement caching for repeated analyses |
| vectorbt GPL v3 license conflict | Low | Use as standalone analysis tool, not linked into core engine; GPL boundaries respected |
| FinanceToolkit FMP API key requirement | Medium | Use akshare financial data + FinanceToolkit's calculation engine only |
| yfinance rate limiting | Certain | Keep as fallback only; akshare is primary |

---

## Sources

- [OpenBB GitHub](https://github.com/OpenBB-finance/OpenBBTerminal) - 67K+ stars, v4.5.0
- [QuantConnect Lean GitHub](https://github.com/QuantConnect/Lean) - 19K stars
- [Microsoft Qlib GitHub](https://github.com/microsoft/qlib) - 43K stars, v0.9.7
- [Backtrader GitHub](https://github.com/mementum/backtrader) - 21K stars, unmaintained
- [TradingAgents GitHub](https://github.com/TauricResearch/TradingAgents) - 71K stars, v0.6.0
- [Riskfolio-Lib GitHub](https://github.com/dcajasn/Riskfolio-Lib) - 4K stars, v7.2.1
- [yfinance GitHub](https://github.com/ranaroussi/yfinance) - 23K stars, v1.3.0
- [FinanceToolkit GitHub](https://github.com/JerBouma/FinanceToolkit) - 4.6K stars, v2.0.7
- [vectorbt GitHub](https://github.com/polakowo/vectorbt) - 7.5K stars, v0.28.2
- [Lightweight Charts GitHub](https://github.com/tradingview/lightweight-charts) - 15.7K stars, v5.2.0
- [TradingAgents arXiv Paper](https://arxiv.org/abs/2412.20138)
- [2026 Backtrader vs VnPy vs Qlib Comparison](https://dev.to/linou518/backtrader-vs-vnpy-vs-qlib-a-deep-comparison-of-python-quant-backtesting-frameworks-2026-3gjl)
