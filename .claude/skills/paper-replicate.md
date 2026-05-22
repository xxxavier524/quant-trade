---
name: paper-replicate
description: Independent replication of quant paper results — plan, backtest, benchmark comparison. Reads papers/<arxiv-id>/metrics.json, writes plan.md, signal.py, backtest.py, nav.png, drawdown.png, metrics.json, benchmark.md. Stops for user confirmation after planning.
---

# Paper Replicate — Independent Reproduction with Benchmark

Reproduce a quant paper's results independently, then compare against reported metrics.

This skill merges three tightly-coupled tasks into one: **plan + backtest + benchmark**. They share too much state to separate — the plan feeds the backtest, the benchmark validates the backtest.

## Three-Phase Workflow

### Phase A: Plan (STOP for user confirmation)

Read `papers/<arxiv-id>/metrics.json` and `papers/<arxiv-id>/note.md`.

Write `papers/<arxiv-id>/plan.md`:

```markdown
# Replication Plan: [Paper Title]

## Data Source
- Provider: [yfinance / WRDS / CRSP / custom CSV]
- Exact code: [import statement + function call]
- Start: [YYYY-MM-DD], End: [YYYY-MM-DD]
- Frequency: [daily / monthly]
- Symbols: [list or pattern]

## Signal Logic
[Pseudocode with equation references from paper]

Example:
```
# Eq. 3: rolling momentum
mom_12m = close.pct_change(252)

# Eq. 5: cross-sectional z-score
score = (mom_12m - mom_12m.mean()) / mom_12m.std()

# Eq. 7: top-quintile selection
signal = score > score.quantile(0.8)
```

## Portfolio Construction
- Weighting: [equal / score-weighted / inverse-vol]
- Rebalance: [frequency]
- Max positions: [N]

## Normalization / Preprocessing
[Cross-sectional z-score, winsorization, etc.]

## Assumptions to Fill
[List every assumption not explicit in the paper]
```

**MUST STOP HERE and wait for user confirmation.** No backtest runs until user approves the plan.

### Phase B: Backtest

After user confirms, implement in `papers/<arxiv-id>/`:

**signal.py** — pure signal generation:
```python
def generate_signal(data: pd.DataFrame, **params) -> pd.Series:
    """Returns: 1=buy, 0=hold, -1=sell (or continuous weights)"""
    ...
```

**portfolio.py** — position sizing / portfolio weights:
```python
def compute_weights(signals: pd.DataFrame, prices: pd.DataFrame, capital: float) -> pd.Series:
    """Returns: target weight per asset"""
    ...
```

**backtest.py** — P&L computation:
```python
def run_backtest(prices, weights, capital=1e6) -> dict:
    """Returns: {nav_series, metrics_dict, trades_df}"""
    ...
```

Output artifacts:
- `nav.png` — equity curve vs benchmark
- `drawdown.png` — underwater plot
- `metrics.json` — replicated metrics (machine-readable)
- `trades.csv` — individual trades (if discrete entry/exit)

Built-in strategy templates:
- **TSMOM**: time-series momentum with volatility scaling
- **CSMOM**: cross-sectional momentum with quintile sorts
- **Risk Parity**: inverse-vol weighting with target vol
- **Trend + Vol**: dual signal with regime filter

Default implementation: pure pandas/numpy vectorized, no heavyweight framework.

### Phase C: Benchmark

Output `papers/<arxiv-id>/benchmark.md`:

```markdown
# Benchmark: Paper vs Replication

| Metric     | Paper | Replication | Diff  | Note                        |
|------------|-------|-------------|-------|------------------------------|
| Sharpe     | 1.42  | 1.18        | -0.24 | Data source (CRSP vs Yahoo) |
| Max DD     | -18%  | -22%        | -4pp  | Period vol differences      |
| Ann Return | 11.3% | 9.8%        | -1.5pp| Consistent with Sharpe diff |

**Conclusion**: [Full replication / Partial replication / Cannot replicate]
**Confidence**: [High / Medium / Low]
**Main divergence sources**:
1. Data vendor differences (CRSP vs yfinance)
2. Dividend reinvestment assumption
3. Rebalance timing (month-end vs mid-month)
```

## Principles

- **Honesty over aesthetics**: "Too clean" replication is suspicious — flag it
- **No parameter tuning**: Don't adjust params to match paper numbers (overfitting)
- **No slippage/costs unless paper specifies them**
- **Replication confidence is more important than replication perfection**

## Dependencies

```bash
pip install pandas numpy matplotlib yfinance
```

No veighna/backtrader needed — pure pandas vectorized backtest.
