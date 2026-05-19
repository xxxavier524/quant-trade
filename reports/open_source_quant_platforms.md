# Open-Source Quantitative Trading Platforms: Feature Gap Analysis

> Generated: 2026-05-16 | Target System: AlphaPulse-A v0.7.0

---

## 1. Full List of Projects Found

| # | Project | GitHub | Stars (approx.) | Language | Focus | Active? |
|---|---------|--------|-----------------|----------|-------|---------|
| 1 | **Freqtrade** | [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | ~46,500 | Python | Crypto auto-trading bot | Yes |
| 2 | **Microsoft Qlib** | [microsoft/qlib](https://github.com/microsoft/qlib) | ~36,900 | Python | AI-oriented quant investment | Yes |
| 3 | **OpenBB Terminal** | [OpenBB-finance/OpenBBTerminal](https://github.com/OpenBB-finance/OpenBBTerminal) | ~23,000 | Python | Investment research terminal | Yes |
| 4 | **NautilusTrader** | [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | ~21,800 | Python+Rust | High-perf event-driven trading | Yes |
| 5 | **Zipline** | [quantopian/zipline](https://github.com/quantopian/zipline) | ~19,300 | Python | Backtesting engine | No (discontinued) |
| 6 | **VeighNa (vnpy)** | [vnpy/vnpy](https://github.com/vnpy/vnpy) | ~19,000 | Python | A-share/futures quant platform | Yes (v4.3.0) |
| 7 | **Abu** | [bbfamily/abu](https://github.com/bbfamily/abu) | ~16,100 | Python | Multi-asset quant system | Yes |
| 8 | **Backtrader** | [mementum/backtrader](https://github.com/mementum/backtrader) | ~10,000 | Python | Event-driven backtesting | Low activity |
| 9 | **QuantConnect Lean** | [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | ~9,700 | C#/Python | Cloud+local algo trading | Yes |
| 10 | **QUANTAXIS** | [yutiansut/QUANTAXIS](https://github.com/yutiansut/QUANTAXIS) | ~8,300 | Python+Rust | Distributed quant system | Yes (v2.1.0-alpha2) |
| 11 | **Jesse** | [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | ~7,400 | Python | Crypto trading bot | Yes |
| 12 | **AI-Trader** | [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | ~11,000 | Python | AI trading benchmark | Yes |
| 13 | **VectorBT** | [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | ~4,100 | Python | Vectorized backtesting | Yes |
| 14 | **Hikyuu** | [fasiondog/hikyuu](https://github.com/fasiondog/hikyuu) | ~2,300 | C++/Python | High-perf quant framework | Yes |
| 15 | **RD-Agent** | [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | ~12,000 | Python | LLM-driven auto quant R&D | Yes (NeurIPS 2025) |

### A-Share Relevance Filter

For A-share market (not crypto-focused), the top 3 most relevant projects are:

| Rank | Project | Why relevant to A-share |
|------|---------|------------------------|
| 1 | **VeighNa (vnpy)** | Native CTP gateway for Chinese futures/stocks, Chinese community, active maintenance |
| 2 | **Microsoft Qlib** | A-share data support (Tongdaxin/JoinQuant sources), Alpha158/360 factor library, ML pipeline |
| 3 | **QUANTAXIS** | Chinese market focus, distributed architecture, QMT/CTP integration, QARS2 Rust core |

---

## 2. Deep-Dive on Top 3 A-Share Projects

### 2.1 VeighNa (vnpy) v4.3.0 -- 19K stars

**Architecture Overview:**
- Layered, event-driven architecture (Pub-Sub pattern)
- Five layers: Gateway (data ingest) -> Event Engine (dispatch) -> Data Store -> Applications (strategies/risk/monitor) -> UI
- Dual-event publish mechanism: generic event (all subscribers) + symbol-specific event (targeted dispatch)
- Thread-safe, non-blocking design with automatic reconnection

**Key Modules:**

| Module | Description | AlphaPulse-A Has? |
|--------|-------------|-------------------|
| **Event Engine** (`vn.event`) | Core publish-subscribe event bus; decouples data sources from consumers | No (no event bus) |
| **CTP Gateway** | Native CTP protocol (C++ wrapper via pybind11) for SHFE/DCE/CFFEX/CZCE/INE | No |
| **CtaStrategy** | CTA strategy template with on_bar/on_tick/on_trade lifecycle | Partial (CtaTemplate wrappers exist) |
| **CtaBacktester** | Full backtest engine with bar-by-bar simulation, daily mark-to-market | Partial (independent engine only) |
| **PortfolioStrategy** | Multi-symbol portfolio-level strategy template | No |
| **AlgoTrading** | Smart order execution algorithms (TWAP, iceberg, etc.) | No |
| **SpreadTrading** | Calendar/futures spread strategy engine | No |
| **OptionMaster** | Options pricing (BS/binomial), Greeks, volatility surface | No |
| **ScriptTrader** | Interactive scripting for rapid strategy prototyping | No |
| **DataManager** | Unified data download/storage (RQData, TuShare, etc.) | Partial (baostock only) |
| **RiskManager** | Pre-trade risk checks (order size, frequency, flow control) | Partial (post-trade only) |
| **RpcService** | RPC framework for multi-process distributed architecture | No |
| **vnpy.alpha** (NEW in 4.0) | ML strategy module: dataset/feature engineering, model training (Lasso/LightGBM/MLP), strategy dev, research workflow | **No** |

**vnpy.alpha Deep-Dive (Most Relevant for AlphaPulse-A):**
- Four sub-modules: `dataset`, `model`, `strategy`, `lab`
- Alpha 158 factor set (from Qlib) for feature engineering
- Standardized ML model template with unified API (Lasso, LightGBM, MLP)
- Cross-sectional multi-symbol and time-series single-symbol strategy support
- Integrated research workflow: data -> model -> signal -> backtest -> analysis
- Jupyter notebook demos for end-to-end workflow

**Unique Features NOT in AlphaPulse-A:**
1. **Production-grade CTP real-trading gateway** (the #1 differentiator for Chinese markets)
2. **Smart order execution algorithms** (TWAP, iceberg orders, OCO/OTO contingent orders)
3. **Multi-process distributed RPC architecture** -- run data service, trading engine, strategy engine in separate processes
4. **Options trading framework** (pricing, Greeks, volatility surface)
5. **vnpy.alpha ML workflow** -- end-to-end ML strategy pipeline
6. **Pre-trade real-time risk controls** (order frequency limits, flow control)
7. **Spread/arbitrage trading engine**
8. **Interactive script trader** (Jupyter/IPython REPL for live trading)
9. **Loguru-based structured logging** (migrated from stdlib logging)
10. **Static type checking with mypy** (improved code quality)

---

### 2.2 Microsoft Qlib v0.9.7 -- 36.9K stars

**Architecture Overview:**
- Four-layer modular architecture: Data -> Model -> Strategy -> Workflow
- AI-oriented: supervised learning, market dynamics modeling, reinforcement learning
- DAG-based task scheduling with `qrun` one-click automation
- Custom binary data format (20-25x faster than HDF5/MySQL)

**Key Components:**

| Component | Description | AlphaPulse-A Has? |
|-----------|-------------|-------------------|
| **Data Layer** | Multi-source data (Tongdaxin/JQData/Yahoo/CSV), auto-cleaning, versioning via DataCache | Partial (CSV only, no versioning) |
| **DataHandler** | High-perf data loading (bin format), point-in-time database support | No |
| **Alpha158 Factor Set** | 158 engineered factors (K-bar patterns, price ratios, rolling stats) | No (8 custom factors) |
| **Alpha360 Factor Set** | 360 raw OHLCV features for deep learning models | No |
| **Model Zoo (15-30+ models)** | LightGBM, XGBoost, CatBoost, TabNet, Transformer, LSTM, GRU, TCN, TRA, HIST, IGMTF, GATs, Localformer, DoubleEnsemble | No (no ML models) |
| **RL Framework (QlibRL)** | PPO, OPDS, DQN for continuous investment decisions | No |
| **Strategy Layer** | TopkDropoutStrategy, WeightStrategyBase, nested decision framework | No (only condition-combo strategies) |
| **Backtest/Executor** | Signal-based backtest with multi-level account simulation | Partial |
| **Portfolio Optimization** | Risk modeling + portfolio construction + order execution (multi-granularity) | No |
| **Order Execution** | TWAP, VWAP algorithms, nested decision optimization | No |
| **Analysis Module** | IC/ICIR/RankIC analysis, performance attribution, report generation | Partial (8 metrics only) |
| **Workflow (qrun)** | YAML config -> one-click full pipeline (data-train-backtest-report) | No |
| **Experiment Management** | MLflow / Weights & Biases integration | No |
| **RD-Agent** (NEW) | LLM-driven autonomous R&D agent: auto factor mining, paper-to-factor, model optimization | **No** |

**RD-Agent Deep-Dive (Most Revolutionary Feature):**
- Four collaborating agents: Research (reads papers), Development (writes code), Scheduler (allocates resources), Implementation (fixes bugs)
- Five-step autonomous loop: Specification -> Synthesis -> Implementation -> Validation -> Analysis
- Three entry points: `fin_factor` (auto factor mining), `fin_factor_report` (extract from reports), `fin_quant` (joint factor-model evolution)
- **Performance**: 2x ARR improvement with 70% fewer factors; cost <$10/experiment; 18hrs/52 rounds to exceed human experts
- Co-STEER code-generation agent ensures executable, correct code
- Accepted at **NeurIPS 2025**

**Unique Features NOT in AlphaPulse-A:**
1. **30+ built-in ML/DL models** with standardized fit/predict API
2. **Alpha158/Alpha360 standardized factor libraries** (battle-tested on A-shares)
3. **RL-based order execution optimization** (PPO/OPDS)
4. **Portfolio optimization module** (risk budgeting, mean-variance, Black-Litterman)
5. **Point-in-time database** (eliminates look-ahead bias)
6. **Binary data format** (50x faster queries vs MySQL)
7. **RD-Agent** -- fully autonomous factor discovery and model optimization via LLM
8. **Nested decision framework** -- multi-granularity investment decisions
9. **Model rolling/timetable** -- automatic model retraining schedule
10. **IC/ICIR/RankIC attribution** -- factor performance decomposition
11. **Signal-to-portfolio conversion** with transaction cost modeling
12. **YAML-driven pipeline** -- reproducible experiments with single config file
13. **MLflow/W&B integration** -- experiment tracking and comparison

---

### 2.3 QUANTAXIS v2.1.0 -- 8.3K stars

**Architecture Overview:**
- 11 core modules for full quant pipeline
- Python+Rust hybrid (QARS2 Rust core via QARSBridge)
- Distributed architecture with RabbitMQ (QAPubSub) + Tornado (QAWebServer) + DAG scheduling
- Multi-language interop: Python/Rust/C++ via Apache Arrow zero-copy exchange

**Key Modules:**

| Module | Description | AlphaPulse-A Has? |
|--------|-------------|-------------------|
| **QARSBridge** (Rust) | 100x account ops, 10x backtest speedup, 90% memory reduction | No |
| **QAFetch/QASU** | Multi-market data fetch + MongoDB/ClickHouse storage | Partial (CSV only) |
| **QAData** | In-memory database for real-time and backtest computation | No |
| **QAIndicator** | Batch indicator computation, factor expression builder | Partial (factor registry) |
| **QAFactor** | Single factor research, factor management, merging, optimizer | Partial |
| **QAEngine** | Distributed async computing agents (LAN-based multi-machine) | No |
| **QAPubSub** | RabbitMQ message bus for task distribution and real-time order flow | No |
| **QAStrategy** | CTA/arbitrage backtesting with QIFI account protocol | Partial |
| **QAWebServer/QASchedule** | Tornado microservice + DAG pipeline task scheduling | No |
| **QIFI** | Unified multi-language account protocol (Python/Rust/C++) | No |
| **OMS + Risk** | QMT integration, OrderGateway risk flow rules, QARiskPro | Partial (QMT export only) |

**Unique Features NOT in AlphaPulse-A:**
1. **Rust core (QARS2)** -- 100x performance for account operations, 10x for backtesting
2. **Distributed computing** -- RabbitMQ-based task distribution across LAN machines
3. **MongoDB/ClickHouse dual-engine storage** -- scalable, query-optimized
4. **DAG pipeline scheduling** -- complex task dependency orchestration
5. **Multi-language account protocol (QIFI)** -- Python/Rust/C++ consistency guarantee
6. **Apache Arrow cross-language zero-copy data exchange**
7. **Tornado microservice web server** -- REST API for quant services
8. **In-memory data structure (QAData)** -- real-time computation and backtesting database
9. **Batch indicator apply across entire market** -- vectorized factor computation at scale
10. **OrderGateway with risk flow rules** -- pre-execution risk checks with rule engine

---

## 3. Feature Gap Analysis Table

### 3.1 Core Infrastructure

| Feature | AlphaPulse-A | VeighNa | Qlib | QUANTAXIS | Priority |
|---------|-------------|---------|------|-----------|----------|
| Event-driven architecture | No | Yes (Pub-Sub event engine) | No | Yes (RabbitMQ) | **P1** |
| Distributed/multi-process | No | Yes (RPC) | No | Yes (Agents) | P2 |
| High-perf data format | CSV | SQLite/DolphinDB | Binary (50x MySQL) | MongoDB/ClickHouse | **P1** |
| Data versioning | No | No | DataCache | No | P2 |
| Point-in-time database | No | No | Yes | No | P2 |
| Experiment tracking | No | No | MLflow/W&B | No | P2 |

### 3.2 Data & Factor Engineering

| Feature | AlphaPulse-A | VeighNa | Qlib | QUANTAXIS | Priority |
|---------|-------------|---------|------|-----------|----------|
| Built-in factor library | 13 custom factors | Alpha158 (via vnpy.alpha) | Alpha158 + Alpha360 | QAFactor suite | **P0** |
| Factor expression engine | No | Yes (expression calc) | Yes | Yes (QAIndicator) | **P1** |
| Factor IC/ICIR analysis | No | No | Yes | Yes | **P0** |
| Factor preprocessing pipeline | Basic | Standardized | Full pipeline | Batch apply | **P1** |
| Multiple data source adapters | 1 (baostock) | 10+ (RQData, TuShare, etc.) | Multi-source | Multi-source | P2 |
| Auto data cleaning/alignment | No | No | Yes (auto-rehab, interpolation) | Yes | P2 |

### 3.3 Model & ML

| Feature | AlphaPulse-A | VeighNa | Qlib | QUANTAXIS | Priority |
|---------|-------------|---------|------|-----------|----------|
| ML model library | No | Lasso/LGB/MLP (vnpy.alpha) | 30+ models (LGB, Transformer, RL) | No | **P0** |
| Reinforcement learning | No | No | Yes (PPO, OPDS, DQN) | No | P2 |
| Model training pipeline | No | Yes (vnpy.alpha lab) | Yes (qrun workflow) | No | **P1** |
| Model rolling/retraining | No | No | Yes | No | P2 |
| LLM-driven auto R&D | No | No | RD-Agent | No | P3 |

### 3.4 Strategy & Backtesting

| Feature | AlphaPulse-A | VeighNa | Qlib | QUANTAXIS | Priority |
|---------|-------------|---------|------|-----------|----------|
| Event-driven backtest | No | Yes (CtaBacktester) | No (signal-based) | Yes (CTA/arbitrage) | P1 |
| Vectorized backtest | Partial | No | No | No | P2 |
| Portfolio-level backtest | No | Yes (PortfolioStrategy) | Yes (WeightStrategy) | Yes | **P1** |
| Multi-asset backtest | Single stock | Multi-symbol | Multi-symbol | Multi-market | **P1** |
| Parameter grid search | Planned (not run) | Manual | Built-in (config-driven) | Manual | **P1** |
| Walk-forward optimization | No | No | Yes (timetable rolling) | No | P2 |
| Order execution simulation | Simple (slippage+fee) | Bar-level | TWAP/VWAP algorithms | QIFI account model | **P1** |
| Trading cost models | Basic (0.1%/0.2% + commission) | Configurable | Configurable | Configurable | P2 |
| Benchmark comparison | No | No | Built-in | No | **P1** |
| Look-ahead bias detection | No | No | Point-in-time DB | No | P2 |

### 3.5 Risk Management

| Feature | AlphaPulse-A | VeighNa | Qlib | QUANTAXIS | Priority |
|---------|-------------|---------|------|-----------|----------|
| Pre-trade risk checks | No | Yes (RiskManager) | No | Yes (OrderGateway) | **P0** |
| Real-time position limits | Post-trade only | Pre-trade | Configurable | Yes (QARiskPro) | **P0** |
| Portfolio risk metrics | No | Daily P&L | VaR/CVaR | Yes | **P1** |
| Drawdown circuit breaker | Simple (stop-loss) | Emergency stop | Configurable | Yes | **P1** |
| Order frequency control | No | Yes | No | Yes | P2 |
| Multi-account risk aggregation | No | Yes (RPC) | No | Yes (OMS) | P3 |

### 3.6 Live Trading & Execution

| Feature | AlphaPulse-A | VeighNa | Qlib | QUANTAXIS | Priority |
|---------|-------------|---------|------|-----------|----------|
| CTP native gateway | No | Yes (production-grade) | No | Yes | **P0** |
| Broker adapter framework | No | 20+ gateways | No | CTP+QMT | **P1** |
| Smart order routing | No | AlgoTrading (TWAP) | TWAP/VWAP | Yes | P2 |
| OMS (Order Management) | CSV export | Yes | No | Yes (母子账户) | P2 |
| Live strategy monitoring | Script-based | GUI dashboard | No | WebServer | P1 |
| Position reconciliation | No | Yes | No | Yes | P2 |

### 3.7 Visualization & Reporting

| Feature | AlphaPulse-A | VeighNa | Qlib | QUANTAXIS | Priority |
|---------|-------------|---------|------|-----------|----------|
| Built-in visualization | Chart.js (HTML) | GUI (PySide) | Plotting utils | QAWebServer | P2 |
| Performance attribution | No | No | Factor-level | Portfolio-level | P2 |
| HTML/PDF report export | Markdown | No | Yes | No | P2 |
| Monthly heatmap | No | Yes | Yes | Yes | P1 |
| Interactive dashboard | Static HTML | Desktop GUI | Jupyter only | Web dashboard | P2 |

### 3.8 DevOps & Operations

| Feature | AlphaPulse-A | VeighNa | Qlib | QUANTAXIS | Priority |
|---------|-------------|---------|------|-----------|----------|
| CLI tool | Script-based | Yes (run.py) | qrun CLI | QA_Setting | P2 |
| Docker deployment | No | No | Yes | Yes | P2 |
| Schedule/automation | launchd | No | No | DAG + QAWebServer | P2 |
| Logging system | stdlib logging | Loguru | Python logging | Python logging | P2 |
| Static type checking | No | mypy (v4.0) | No | No | P3 |
| Configuration management | settings.py | JSON/YAML | YAML configs | JSON/YAML | P2 |

---

## 4. Recommendations: Features to Add and Priority

### Priority P0 (Immediate -- Highest Impact, Lowest Effort)

These features directly improve strategy quality and risk safety:

| # | Feature | Source Project | Effort | Rationale |
|---|---------|---------------|--------|-----------|
| 1 | **Factor IC/ICIR/RankIC Analysis** | Qlib | Medium | Measure real predictive power of each factor; currently only have unit tests but no predictive validation. Essential before deploying any strategy. |
| 2 | **Alpha158 Factor Library** | Qlib / vnpy.alpha | Medium | 158 engineered A-share factors already battle-tested. Can be imported as an additional factor set alongside existing custom factors. Much richer than current 13 custom factors. |
| 3 | **Pre-trade Risk Checks** | VeighNa / QUANTAXIS | Low | Add order size limits, daily frequency caps, and flow control BEFORE orders are sent. Currently only post-trade monitoring exists. Critical safety gap. |
| 4 | **LightGBM Model Integration** | Qlib / vnpy.alpha | Low-Medium | Add ML-based signal generation alongside current condition-combo strategies. LightGBM is the simplest and most effective model for tabular financial data. |
| 5 | **CTP/Native Broker Gateway** | VeighNa | High | The single biggest differentiator for A-share real trading. vnpy's CTP gateway is the gold standard. Consider wrapping vnpy's gateway or integrating directly. |

### Priority P1 (Short-term -- High Value)

| # | Feature | Source Project | Effort | Rationale |
|---|---------|---------------|--------|-----------|
| 6 | **Event-Driven Architecture** | VeighNa | Medium | Decouple data sources, strategy engine, and risk controls. Pub-Sub pattern enables adding new components without touching existing code. Foundation for multi-process architecture. |
| 7 | **Portfolio-Level Backtest** | VeighNa / Qlib | Medium | Current backtest operates single-stock; need multi-symbol portfolio simulation with position sizing, rebalancing, and correlation-aware risk. |
| 8 | **Factor Expression Engine** | VeighNa / QUANTAXIS | Medium | Allow users to define factors as expressions (e.g., "MA(CLOSE,20) / MA(CLOSE,60)") rather than coding Python. Complements the NLP-to-formula frontend. |
| 9 | **Order Execution Algorithms** | VeighNa / Qlib | Medium-High | TWAP/VWAP execution simulation in backtest + live trading. Current simple slippage model is insufficient for realistic testing. |
| 10 | **High-Perf Data Format** | Qlib | Medium | Move from CSV to Parquet or Qlib's binary format. 20-50x query speedup for large-scale backtesting. Parquet is the pragmatic choice (widely supported). |
| 11 | **Parameter Grid Search Automation** | Qlib | Low-Medium | Already planned in Phase 6. Qlib's YAML-driven `qrun` approach is a good model: define search space in config, run with one command. |
| 12 | **Drawdown Circuit Breaker** | VeighNa / QUANTAXIS | Low | Emergency stop when portfolio drawdown exceeds threshold (e.g., -15%). Currently only per-position stop-loss exists. |
| 13 | **Model Training Pipeline** | Qlib / vnpy.alpha | High | End-to-end workflow: feature engineering -> model training -> signal generation -> backtesting. vnpy.alpha's `lab` module is the closest design pattern. |

### Priority P2 (Medium-term -- Good Investment)

| # | Feature | Source Project | Effort | Rationale |
|---|---------|---------------|--------|-----------|
| 14 | **Docker Deployment** | Qlib / NautilusTrader | Low | Containerize for reproducible environments and easier deployment across machines. |
| 15 | **Multi-Process RPC Architecture** | VeighNa | High | Separate data service, strategy engine, and trading gateway into different processes. Enables independent scaling and failure isolation. |
| 16 | **Walk-Forward Optimization** | Qlib | Medium | Rolling window training/testing to validate model stability through different market regimes. Qlib's timetable rolling is the reference implementation. |
| 17 | **Performance Attribution** | Qlib / QUANTAXIS | Medium-High | Decompose returns by factor/sector/style. Essential for understanding what's driving performance. |
| 18 | **Broker Adapter Framework** | VeighNa / NautilusTrader | High | Plugin-based adapter pattern for adding new brokers without core changes. VeighNa has 20+ gateways using this pattern. |
| 19 | **MLflow/W&B Experiment Tracking** | Qlib | Low | Track all experiments (parameters, metrics, artifacts) automatically. Essential for systematic strategy research. |
| 20 | **Monthly Heatmap / Visualization** | Freqtrade / Qlib | Low | Visualize monthly returns and drawdown periods. Freqtrade's plot-profit module is a good reference. |

### Priority P3 (Long-term -- Aspirational)

| # | Feature | Source Project | Effort | Rationale |
|---|---------|---------------|--------|-----------|
| 21 | **RD-Agent Integration** | Qlib / RD-Agent | High | LLM-driven autonomous factor discovery and model optimization. Revolutionary but requires significant infrastructure setup. |
| 22 | **Options Trading Framework** | VeighNa | High | Options pricing (BS/binomial), Greeks calculation, volatility surface modeling. Large scope. |
| 23 | **Rust Core for Performance** | QUANTAXIS / NautilusTrader | Very High | Rewrite performance-critical paths (account ops, data processing) in Rust. 100x speedup in some operations. |
| 24 | **Reinforcement Learning Framework** | Qlib | High | PPO/OPDS for order execution and dynamic portfolio optimization. Requires significant RL expertise and infrastructure. |
| 25 | **Multi-Account OMS** | QUANTAXIS | High | Order management system for parent-child account splitting, multi-broker routing, and compliance checks. |

---

## 5. Key Architectural Patterns to Adopt

### 5.1 Event-Driven Pub-Sub (from VeighNa)

```
Gateway -> Event(TICK) -> EventEngine -> [Strategy, RiskManager, Logger, UI]
```

Benefits: Loose coupling, easy to add new components, testable in isolation.
AlphaPulse-A should adopt this as the core architectural pattern.

### 5.2 Factor Expression Engine (from VeighNa/QUANTAXIS)

Allow defining factors declaratively:
```
"MA(CLOSE, 20) > MA(CLOSE, 60) AND VOLUME > MA(VOLUME, 20) * 1.5"
```

This complements the existing NLP-to-formula frontend perfectly.

### 5.3 ModelTemplate Pattern (from vnpy.alpha)

```python
class AlphaModel:
    def prepare_data(self) -> Dataset
    def train(self, dataset: Dataset) -> Model
    def predict(self, model: Model, data: DataFrame) -> Series
    def evaluate(self, predictions: Series, returns: Series) -> Dict
```

Standardized interface allows swapping models without changing strategy code.

### 5.4 YAML-Driven Pipeline (from Qlib)

```yaml
workflow:
  data: {handler: Alpha158, instruments: csi300}
  model: {class: LightGBM, params: {...}}
  strategy: {class: TopkDropoutStrategy, topk: 50}
  backtest: {start: 2020-01-01, end: 2025-12-31}
```

Single config file = reproducible experiment. Critical for systematic research.

### 5.5 Adapter Pattern for Brokers (from VeighNa/NautilusTrader)

```python
class BrokerAdapter(ABC):
    def connect(self): ...
    def send_order(self, order: Order) -> OrderId: ...
    def cancel_order(self, order_id: OrderId): ...
    def on_trade(self, callback: Callable): ...
```

Plugin-based design: add new brokers without touching core logic.

---

## 6. Summary

AlphaPulse-A v0.7.0 has a solid foundation: 13 factors, 3 strategies, independent backtesting, automation scripts, and QMT export. It is a working end-to-end system.

The biggest gaps versus established open-source platforms are in three areas:

1. **Risk Management** (P0): Pre-trade checks and circuit breakers are essential safety features that the system currently lacks. VeighNa's RiskManager is the best reference model.

2. **ML/AI Capabilities** (P0-P1): The system currently relies entirely on condition-based strategies. Adding even a basic LightGBM model (from Qlib/vnpy.alpha) with standardized factor analysis (IC/ICIR) would dramatically improve signal quality.

3. **Production Readiness** (P0-P1): Real trading requires a native CTP gateway (VeighNa), portfolio-level simulation, smart order execution, and an event-driven architecture. These are the features that separate research platforms from production trading systems.

The recommended approach is to implement P0 items first (1-2 weeks each), then progressively adopt P1 architectural patterns. The event-driven core (from VeighNa) should be the foundation, with Qlib's factor/model libraries layered on top, and QUANTAXIS's distributed computing as a long-term scaling goal.

---

## Sources

- [Freqtrade GitHub](https://github.com/freqtrade/freqtrade)
- [Microsoft Qlib GitHub](https://github.com/microsoft/qlib)
- [VeighNa (vnpy) GitHub](https://github.com/vnpy/vnpy)
- [NautilusTrader GitHub](https://github.com/nautechsystems/nautilus_trader)
- [QUANTAXIS GitHub](https://github.com/yutiansut/QUANTAXIS)
- [QuantConnect Lean GitHub](https://github.com/QuantConnect/Lean)
- [Zipline-Reloaded GitHub](https://github.com/stefan-jansen/zipline-reloaded)
- [Backtrader GitHub](https://github.com/mementum/backtrader)
- [RD-Agent GitHub](https://github.com/microsoft/RD-Agent)
- [awesome-quant GitHub](https://github.com/wilsonfreitas/awesome-quant)
- [Backtrader vs vnpy vs Qlib Comparison (2026)](https://dev.to/linou518/backtrader-vs-vnpy-vs-qlib-a-deep-comparison-of-python-quant-backtesting-frameworks-2026-3gjl)
- [VeighNa CTP DeepWiki](https://deepwiki.com/vnpy/vnpy_ctp/1-overview)
- [VeighNa Architecture Analysis](https://deepwiki.com/vnpy/vnpy/2.5-gateway-system)
