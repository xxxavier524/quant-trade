# yfinance as an A-Share Data Source: Feasibility Research

> Generated: 2026-05-16 | Project: AlphaPulse-A | Python 3.14.3

---

## 1. Executive Summary

**yfinance is NOT recommended as the primary A-share data source for AlphaPulse-A.** The existing akshare pipeline (already installed and functional in this project) provides superior A-share coverage, reliability, and accessibility. yfinance may serve as a **secondary/backup** source for specific use cases (cross-verification, US-listed Chinese ADRs, global market data).

---

## 2. Live Test Results (2026-05-16)

### 2.1 Installation Status

| Package | Version | Installed? | Functional? | Notes |
|---------|---------|-----------|-------------|-------|
| **yfinance** | 1.3.0 | Yes | **No** - Rate limited | 429 Too Many Requests from this network |
| **akshare** | 1.18.60 | Yes | **Yes** | Successfully fetched 87 rows for 600519 |
| **baostock** | 0.9.1 | Yes | **No** - Network error | Login failed: 10002007 (network receive error) |
| **openbb** | -- | **No** | N/A | `pip install openbb` not found; would need `openbb-cli` + `openbb_akshare` |
| **pandas-datareader** | 0.10.0 | Yes | **No** - Import error | Uses `distutils` (removed in Python 3.12+), incompatible with Python 3.14 |

### 2.2 Connectivity Test

```
Test environment: macOS 24.6.0, Python 3.14.3, venv
Network condition: Rate-limited to Yahoo Finance servers

yfinance tests:
  - 600519.SS (Kweichow Moutai): ERROR - Too Many Requests. Rate limited.
  - 000001.SZ (Ping An Bank):    ERROR - Too Many Requests. Rate limited.
  - 300750.SZ (CATL):            ERROR - Too Many Requests. Rate limited.
  - 688981.SS (SMIC):            ERROR - Too Many Requests. Rate limited.

akshare test:
  - 600519 (Kweichow Moutai):    OK - 87 rows, last close=1598.18

baostock test:
  - sh.600519:                    ERROR - Network receive error (10002007)
```

**Key finding**: yfinance is severely rate-limited from this network environment, making it unusable as a primary A-share data source.

---

## 3. A-Share Symbol Format for yfinance

### 3.1 Exchange Suffix Rules

| Exchange | Suffix | Code Prefix | Example |
|----------|--------|-------------|---------|
| Shanghai Stock Exchange (SSE) | `.SS` | `6xxxxx` | `600519.SS` (Kweichow Moutai) |
| Shanghai STAR Market (科创板) | `.SS` | `688xxx` | `688981.SS` (SMIC) |
| Shenzhen Stock Exchange (SZSE) | `.SZ` | `0xxxxx` | `000001.SZ` (Ping An Bank) |
| Shenzhen ChiNext (创业板) | `.SZ` | `3xxxxx` | `300750.SZ` (CATL) |
| Shenzhen SME Board | `.SZ` | `002xxx` | `002594.SZ` (BYD) |
| Beijing Stock Exchange (北交所) | `.SS` (fallback) | `8xxxxx` | NOT supported by Yahoo Finance |

### 3.2 Symbol Normalization Function

```python
def normalize_a_share_symbol(code: str) -> str:
    """Convert 6-digit A-share code to Yahoo Finance ticker."""
    code = code.strip().zfill(6)
    if code.startswith("6"):
        return f"{code}.SS"
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    return f"{code}.SS"  # fallback
```

This logic is implemented in `alphapulse/utils/yfinance_adapter.py`.

---

## 4. yfinance vs baostock vs akshare: Comprehensive Comparison

### 4.1 Summary Matrix

| Dimension | **yfinance** | **baostock** | **akshare** |
|:----------|:------------|:------------|:-----------|
| **Cost** | Free | Free | Free |
| **Registration** | Not required | Not required (login/logout) | Not required |
| **A-Share Coverage** | Limited/Incomplete | Excellent | Excellent |
| **US Stock Coverage** | Excellent | None | None |
| **HK Stock Coverage** | Good | None | Partial |
| **Real-time Data** | Yes (unstable for A-shares) | No | Yes |
| **Historical Depth** | ~10 years | **15+ years** (since 1990) | ~5 years |
| **Minute-level K-line** | Supported | **Excellent** | Partial |
| **Adjusted Price Data** | Limited | **Excellent** (precise factor) | Good (forward/backward) |
| **Financial Data** | Basic | Moderate (~70 indicators) | Basic (~50 indicators) |
| **API Stability** | 4/5 (overseas) | 4/5 (99.5%+ with exchange) | 3/5 (depends on source websites) |
| **Response Time** | <500ms | <300ms | <850ms |
| **Mainland China Access** | **Requires VPN/proxy** | Direct access | Direct access |
| **Data Accuracy vs Exchange** | Moderate for A-shares | High | Moderate (varies by source) |
| **Rate Limiting** | Yahoo-imposed, varies | Generous | Depends on source (<10/min recommended) |
| **Code Format** | `600519.SS` / `000001.SZ` | `sh.600519` / `sz.000001` | `600519` (plain 6-digit) |

### 4.2 Detailed Analysis

#### yfinance -- Global Market Specialist

**Strengths:**
- Best-in-class for US stock data (NYSE, NASDAQ)
- Clean API returning pandas DataFrames directly
- Supports dividends, splits, financials, institutional holders
- No API key or registration required

**Weaknesses for A-Shares:**
- A-share data is frequently incomplete, delayed, or unavailable
- Requires stable VPN/proxy access from mainland China
- Rate limiting is aggressive (easily triggered with batch queries)
- Data accuracy verification difficult (source is Yahoo Finance, not exchange)

**Best for:** US stock strategies with incidental A-share interest; ADR data.

#### baostock -- Historical Data Gold Standard

**Strengths:**
- Deepest historical coverage (back to 1990, 15+ years)
- Most accurate adjusted-price factors
- Complete minute-level K-line data
- Free, no registration beyond library login
- Designed specifically for A-share market

**Weaknesses:**
- No real-time data (T+1 only, available ~2 hours after close)
- Limited to A-shares (no HK, US, or other markets)
- Fewer financial indicators than Tushare
- Network-dependent; can fail in some environments

**Best for:** Quantitative backtesting, technical analysis, academic research.

#### akshare -- Most Comprehensive Coverage

**Strengths:**
- Widest asset class coverage (stocks, funds, futures, bonds, crypto, macro)
- Real-time quotes available
- Aggregates multiple data sources (Eastmoney, Sina, Tencent, etc.)
- Active community, frequent updates
- Zero registration, zero cost

**Weaknesses:**
- Stability depends on upstream websites (can break when they change)
- API formats inconsistent across functions
- Data accuracy varies by source
- Requires rate limiting to avoid IP bans

**Best for:** Rapid prototyping, real-time monitoring, multi-asset data aggregation.

---

## 5. openbb Assessment

### 5.1 Installation

```bash
# Direct install fails (PyPI name issue)
pip install openbb          # FAILED - package not found

# Correct approach
pip install openbb-cli      # Required base package
pip install openbb_akshare   # Community extension for A-shares
```

### 5.2 A-Share Capability

OpenBB does **not** natively support A-share data. The community extension `openbb_akshare` (by Roger Ye / finanalyzer) wraps akshare into OpenBB's provider framework:

```python
from openbb import obb

df = obb.equity.price.historical(
    symbol="600028",
    start_date="2024-01-01",
    end_date="2025-09-08",
    provider="akshare"
).to_dataframe()
```

### 5.3 Verdict

OpenBB adds unnecessary complexity for AlphaPulse-A's use case, since it is essentially a wrapper around akshare (which is already installed and working). Not recommended.

---

## 6. pandas-datareader Assessment

### 6.1 Compatibility Issue

`pandas-datareader` v0.10.0 imports `distutils.version.LooseVersion`, which was removed from the Python standard library in Python 3.12. This makes it **incompatible with Python 3.14** (the project's current runtime).

```
ModuleNotFoundError: No module named 'distutils'
```

### 6.2 Verdict

Not recommended. Even on Python 3.10/3.11, it adds no value over direct yfinance/akshare usage -- it is merely a thin wrapper.

---

## 7. Recommendation for AlphaPulse-A

### 7.1 Primary Data Source: akshare (already installed and working)

```python
import akshare as ak

# Daily K-line with forward-adjusted prices
df = ak.stock_zh_a_hist(
    symbol="600519",
    period="daily",
    start_date="20240101",
    end_date="20240516",
    adjust="qfq"
)
```

### 7.2 Secondary Data Source: yfinance (for US stock / cross-market)

Use the `YFinanceAdapter` class in `alphapulse/utils/yfinance_adapter.py` for:
- Fetching US-listed Chinese ADR data (BABA, JD, NIO, etc.)
- Cross-verifying A-share data against international sources
- Accessing global market indices (SPX, DJI, HSI) for correlation analysis

### 7.3 Data Source Architecture

```
┌─────────────────────────────────────────────────────┐
│                  AlphaPulse-A                        │
│                                                      │
│  Primary Pipeline (A-Share)                          │
│  ┌──────────┐   ┌──────────┐   ┌───────────────┐   │
│  │ TDX .day │ → │ parse    │ → │ data/day/*.csv │   │
│  │ files    │   │ scripts  │   │                │   │
│  └──────────┘   └──────────┘   └───────────────┘   │
│                                      │               │
│                                      ▼               │
│                              ┌──────────────┐       │
│                              │ Factor Engine │       │
│                              └──────────────┘       │
│                                                      │
│  Live/Supplement Pipeline                            │
│  ┌──────────┐   ┌──────────────┐                    │
│  │ akshare  │──▶│ Real-time    │ (working)          │
│  │ 1.18.60  │   │ quotes/hist  │                    │
│  └──────────┘   └──────────────┘                    │
│                                                      │
│  ┌──────────┐   ┌──────────────┐                    │
│  │ yfinance │──▶│ Global/US    │ (rate-limited)     │
│  │ 1.3.0    │   │ ADR data     │                    │
│  └──────────┘   └──────────────┘                    │
│                                                      │
│  ══════════════ NOT RECOMMENDED ══════════════════  │
│  ✗ baostock     - network connectivity issues       │
│  ✗ openbb       - unnecessary wrapper layer         │
│  ✗ pandas-datareader - Python 3.14 incompatible    │
└─────────────────────────────────────────────────────┘
```

---

## 8. yfinance Adapter Module

### 8.1 Location

`alphapulse/utils/yfinance_adapter.py`

### 8.2 API Summary

```python
from alphapulse.utils.yfinance_adapter import YFinanceAdapter, normalize_a_share_symbol

adapter = YFinanceAdapter(rate_limit_delay=0.5, max_retries=3)

# Symbol normalization
ticker = normalize_a_share_symbol("600519")  # "600519.SS"

# Historical OHLCV
df = adapter.get_history("600519", start="2024-01-01", end="2024-05-01")

# Metadata (name, market cap, P/E, sector, etc.)
meta = adapter.get_metadata("600519")

# Batch download (multiple tickers)
df = adapter.batch_get_history(["600519", "000001", "300750"], period="1y")

# Dividends and splits
divs = adapter.get_dividends("600519", start="2020-01-01")
splits = adapter.get_splits("600519")

# Connectivity check
from alphapulse.utils.yfinance_adapter import is_yfinance_available
if is_yfinance_available():
    print("yfinance is reachable")
```

### 8.3 Key Features

- **Automatic symbol normalization**: Accepts raw 6-digit codes (`600519`) or full yahoo tickers (`600519.SS`)
- **Rate limiting**: Built-in delay enforcement to avoid HTTP 429 errors
- **Exponential backoff retry**: 3 attempts with configurable backoff
- **Column normalization**: Maps yfinance column names to lowercase standard names (open, high, low, close, adj_close, volume)
- **Empty DataFrame handling**: Returns empty DataFrame (not None) on failure, safe for downstream pandas operations
- **LRU-cached symbol resolution**: `resolve_symbol_cached()` avoids recomputing suffix mappings

---

## 9. Conclusion

| Question | Answer |
|:---------|:-------|
| Does yfinance support A-share stocks? | **Yes**, via `.SS`/`.SZ` suffixes, but support is incomplete and unreliable |
| Is yfinance usable from this environment? | **No** -- consistently rate-limited (HTTP 429) |
| Should we use yfinance as primary A-share source? | **No** -- use akshare (already installed and working) |
| Should we keep yfinance installed? | **Yes** -- useful for US stock/ADR data and cross-market analysis |
| Is the adapter module worth keeping? | **Yes** -- provides clean abstraction if network conditions improve |

**Bottom line**: The current data pipeline (TDX `.day` files + akshare for live data) is the optimal configuration. yfinance remains a viable backup/extension point via the adapter module but should not be relied upon for production A-share data.
