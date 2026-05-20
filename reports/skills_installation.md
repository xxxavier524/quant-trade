# Claude Code Quantitative Trading Skills Installation Report

**Date**: 2026-05-16
**Target**: ~/.claude/skills/ (and ~/.agents/skills/ via npx)

---

## Summary

| # | Skill Name | Source | Status | Details |
|---|-----------|--------|--------|---------|
| 1 | 回测专家 (Backtest Expert) | tradermonty/claude-trading-skills | INSTALLED | Copied backtest-expert/ to ~/.claude/skills/ |
| 2 | 市场数据流水线 (Market Data Pipeline) | JoelLewis/finance_skills | INSTALLED | trading-operations + data-integration plugins symlinked; also installed via npx |
| 3 | 信号生成器 (Signal Generator) | ScientiaCapital/skills | FAILED | `active/signal-generation` directory does not exist in the repo |
| 4 | 风险管理器 (Risk Manager) | JoelLewis/finance_skills | INSTALLED | wealth-management plugin symlinked; also installed via npx |
| 5 | 实时信号监控器 (Real-time Signal Monitor) | roman-rr/trading-skills | INSTALLED | Copied trading-signals/ to ~/.claude/skills/ |

**Total skills installed**: 50+ individual skill directories in ~/.claude/skills/ (plus 84 via npx to ~/.agents/skills/)

---

## Detailed Results

### Skill 1: 回测专家 (Backtest Expert) -- INSTALLED

- **Source**: [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills)
- **Repo exists**: Yes (HTTP 200)
- **Already cloned**: Yes, at `~/.claude/skills/claude-trading-skills/`
- **Skill path**: `skills/backtest-expert/`
- **Install method**: `cp -r skills/backtest-expert ~/.claude/skills/`
- **Files installed**:
  - `SKILL.md` (8.5KB) -- Systematic backtesting methodology
  - `references/methodology.md` (7.1KB) -- Testing techniques
  - `references/failed_tests.md` (7.6KB) -- Failure patterns reference
  - `scripts/evaluate_backtest.py` (15.0KB) -- Quantitative evaluation script
  - `references/tests/` -- Test files
- **Function**: Strategy rules -> OHLCV -> indicator calc -> vectorized backtest -> output Sharpe/drawdown/win rate/equity curve

### Skill 2: 市场数据流水线 (Market Data Pipeline) -- INSTALLED

- **Source**: [JoelLewis/finance_skills](https://github.com/JoelLewis/finance_skills)
- **Repo exists**: Yes (HTTP 200)
- **Already cloned**: Yes, at `~/.claude/skills/finance_skills/`
- **Plugins installed**:
  - `trading-operations` (9 skills): counterparty-risk, exchange-connectivity, margin-operations, operational-risk, order-lifecycle, post-trade-compliance, pre-trade-compliance, settlement-clearing, trade-execution
  - `data-integration` (4 skills): data-quality, integration-patterns, market-data, reference-data
  - `core` (3 skills, dependency): return-calculations, statistics-fundamentals, time-value-of-money
- **Install methods**:
  1. Manual symlinks to `~/.claude/skills/` (install.sh failed due to bash 3.2 on macOS lacking associative arrays)
  2. `npx skills add JoelLewis/finance_skills --global` succeeded, installing 84 skills to `~/.agents/skills/`
- **Key file**: `market-data/SKILL.md` (19.9KB) -- Real-time/delayed feeds, Level 1/2/3 depth, SIP vs direct feeds, vendor selection, licensing
- **Note**: Article described "EODHD data integration, unified DataFrame format." The actual market-data skill covers broader market data infrastructure. No specific EODHD integration was found; the data-integration plugin provides the closest match.

### Skill 3: 信号生成器 (Signal Generator) -- FAILED

- **Source**: [ScientiaCapital/skills](https://github.com/ScientiaCapital/skills)
- **Repo exists**: Yes (HTTP 200)
- **Already cloned**: Yes, at `~/.claude/skills/skills/`
- **Expected path**: `skills/active/signal-generation/`
- **Actual status**: This directory does NOT exist in the repository
- **Search results**:
  - The `active/` directory contains ~80+ skills but no `signal-generation`
  - Closest match: `active/trading-signals-skill/` -- but this is a general trading analysis skill (Elliott Wave, Wyckoff, options strategies), NOT an NL-strategy-to-pandas/numpy signal generator
  - `active/intent-signal-aggregator-skill/` -- sales intent signals, not trading
- **Root cause**: The referenced `active/signal-generation` subdirectory does not exist in the current version of the ScientiaCapital/skills repository. It may have been in an older version, planned but not yet implemented, or the directory name was changed.
- **No alternative found**: None of the 4 cloned repos contain an NL-strategy-to-vectorized-code signal generation skill with look-ahead bias checking.

### Skill 4: 风险管理器 (Risk Manager) -- INSTALLED

- **Source**: [JoelLewis/finance_skills](https://github.com/JoelLewis/finance_skills)
- **Repo exists**: Yes (HTTP 200)
- **Already cloned**: Yes, at `~/.claude/skills/finance_skills/`
- **Plugin**: `wealth-management` (31 skills)
- **Install methods**:
  1. Manual symlinks to `~/.claude/skills/`
  2. `npx skills add JoelLewis/finance_skills --global` (installed all 84 skills)
- **Key risk-management skills installed**:
  - `historical-risk/SKILL.md` (8.2KB) -- Historical risk measurement, drawdown, volatility
  - `forward-risk/SKILL.md` (10.7KB) -- VaR, CVaR, scenario analysis, stress testing
  - `volatility-modeling/SKILL.md` (13.3KB) -- ATR, GARCH, EWMA, implied vs historical vol
  - `bet-sizing/SKILL.md` (9.8KB) -- Kelly criterion, fixed ratio, risk-based position sizing
  - `diversification/SKILL.md` (8.9KB) -- Correlation, concentration risk, portfolio heat
  - `performance-metrics/SKILL.md` (8.9KB) -- Sharpe, Sortino, Calmar, drawdown analysis
- **Note**: Article described "ATR stop-loss, fixed ratio position sizing, portfolio heat, VaR(95%), circuit breaker." These map to: volatility-modeling (ATR), bet-sizing (fixed ratio), forward-risk (VaR 95%), diversification (portfolio heat). Circuit breaker logic is not explicitly present but can be inferred from the risk management framework.

### Skill 5: 实时信号监控器 (Real-time Signal Monitor) -- INSTALLED

- **Source**: [roman-rr/trading-skills](https://github.com/roman-rr/trading-skills)
- **Repo exists**: Yes (HTTP 200)
- **Already cloned**: Yes, at `~/.claude/skills/trading-skills/`
- **Skill path**: `trading-signals/`
- **Install method**: `cp -r trading-skills/trading-signals ~/.claude/skills/`
- **Files installed**:
  - `SKILL.md` (8.0KB) -- AI crypto trading signals with API integration
  - `references/SIGNAL-FORMAT.md` (3.4KB) -- Signal data format reference
  - `agents/openai.yaml` -- Agent configuration
  - `assets/icon-small.svg` -- Skill icon
- **Note**: Article described "EODHD real-time quotes, rolling window trigger, signal alert." The actual skill is a crypto trading signals API service (signals.x70.ai) providing AI-generated trade setups with entry/stop-loss/take-profit/confidence scores for 50+ coins. It does not use EODHD for equities data. Functionally similar (real-time signals with alerts) but asset class differs (crypto vs equities).

---

## Installation Methods Used

### Method 1: Direct Copy (Skills 1, 5)
Simple `cp -r` from the cloned repo subdirectory to `~/.claude/skills/`. Works reliably for standalone skill directories.

### Method 2: Symlinks (Skills 2, 4)
Manual `ln -s` from `finance_skills/plugins/<plugin>/skills/<skill>/` to `~/.claude/skills/<skill>/`. The `install.sh` script could not run because it requires bash 4+ (associative arrays) and macOS ships with bash 3.2.

### Method 3: npx skills add (Skills 2, 4 -- supplementary)
`npx skills add JoelLewis/finance_skills --global` successfully installed all 84 finance skills to `~/.agents/skills/` with Claude Code symlinks. The `--plugin` flag referenced in the article is not supported by the `npx skills` CLI.

---

## Issues Encountered

1. **bash version**: macOS default bash 3.2 lacks `declare -A` (associative arrays). The `install.sh` script from finance_skills requires bash 4+. Workaround: manual symlinking.

2. **Missing skill directory**: `ScientiaCapital/skills` does not contain `active/signal-generation/`. This is likely a discrepancy between the article and the current state of the repository.

3. **npx --plugin flag**: The `npx skills add` command does not support a `--plugin` option. It installs the entire package. The article's command `npx skills add JoelLewis/finance_skills --plugin trading-operations` would fail on the `--plugin` flag.

4. **Functional mismatches**: Some installed skills differ from the article's functional descriptions:
   - Market Data Pipeline covers general infrastructure, not EODHD-specific
   - Real-time Signal Monitor is crypto-focused, not equities EODHD

---

## Skill Directory Structure (Final State)

Individual skill directories in `~/.claude/skills/`:

```
alternatives/           fixed-income-corporate/    performance-reporting/
asset-allocation/       fixed-income-municipal/    post-trade-compliance/
backtest-expert/        fixed-income-sovereign/    pre-trade-compliance/
bet-sizing/             fixed-income-structured/   qualitative-valuation/
commodities/            forward-risk/              quantitative-valuation/
counterparty-risk/      fund-vehicles/             real-assets/
currencies-and-fx/      historical-risk/           rebalancing/
data-quality/           integration-patterns/      reference-data/
debt-management/        investment-policy/         return-calculations/
digital-assets/         lending/                   savings-goals/
diversification/        liquidity-management/      settlement-clearing/
emergency-fund/         margin-operations/         statistics-fundamentals/
equities/               market-data/               tax-efficiency/
exchange-connectivity/  operational-risk/          tax-loss-harvesting/
finance-psychology/     order-lifecycle/           time-value-of-money/
                        performance-attribution/   trade-execution/
                        performance-metrics/       trading-signals/
                                                   volatility-modeling/
```

Source repos (not individual skills):
```
claude-trading-skills/  finance_skills/  skills/  trading-skills/
```
