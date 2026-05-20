# Lightweight Charts Frontend Migration Guide

> Target: AlphaPulse-A `frontend/index.html`  
> From: Chart.js v4.4.0 (general-purpose charting)  
> To: TradingView Lightweight Charts v5.2.0 (professional financial charts)  
> Effort: ~4-6 hours | Impact: HIGH (professional trading UI)

---

## Why Migrate?

| Capability | Chart.js | Lightweight Charts |
|-----------|----------|-------------------|
| Candlestick/OHLC | Plugin-based (fragile) | Native, first-class |
| Crosshair with price/date | Manual implementation | Built-in |
| Multi-pane layout | Manual HTML grid | Native pane API |
| Volume sub-chart | Manual canvas | Built-in histogram |
| Time range quick-select | Manual buttons | Built-in toolbar |
| Dark theme | Custom CSS | Built-in `dark` theme |
| Real-time streaming update | Manual | Built-in `update()` |
| Industry trust | General web charts | TradingView standard |
| Bundle size | ~60KB | ~45KB (lighter!) |

---

## Step 1: Replace CDN Script

In `index.html`, replace the Chart.js script tag:

```html
<!-- REMOVE this line -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>

<!-- ADD this line -->
<script src="https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script>
```

Or for npm-based projects:
```bash
npm install lightweight-charts@5.2.0
```

---

## Step 2: Create Candlestick Chart Container

Replace Chart.js `<canvas>` elements with lightweight-charts `<div>` containers.

**Old (Chart.js):**
```html
<div class="chart-container">
  <canvas id="price-chart"></canvas>
</div>
```

**New (Lightweight Charts):**
```html
<div class="chart-container" id="price-chart-container" style="position:relative;height:350px"></div>
<div class="chart-container" id="volume-chart-container" style="position:relative;height:120px"></div>
```

---

## Step 3: Initialize Charts

**Old (Chart.js):**
```javascript
const ctx = document.getElementById('price-chart').getContext('2d');
const chart = new Chart(ctx, {
    type: 'line',
    data: { labels: dates, datasets: [{ data: prices }] },
    options: { /* ... */ }
});
```

**New (Lightweight Charts):**
```javascript
const { createChart, ColorType } = LightweightCharts;

// Main price chart
const priceChart = createChart('price-chart-container', {
    width: container.clientWidth,
    height: 350,
    layout: {
        background: { type: ColorType.Solid, color: '#161b22' },
        textColor: '#8b949e',
    },
    grid: {
        vertLines: { color: '#21262d' },
        horzLines: { color: '#21262d' },
    },
    crosshair: {
        mode: 0, // CrosshairMode.Normal
        vertLine: {
            color: '#58a6ff',
            style: 2, // Dashed
            width: 1,
            labelBackgroundColor: '#58a6ff',
        },
        horzLine: {
            color: '#58a6ff',
            style: 2,
            width: 1,
            labelBackgroundColor: '#58a6ff',
        },
    },
    timeScale: {
        borderColor: '#30363d',
        timeVisible: true,
        secondsVisible: false,
    },
    rightPriceScale: {
        borderColor: '#30363d',
    },
});

// Candlestick series
const candleSeries = priceChart.addCandlestickSeries({
    upColor: '#3fb950',
    downColor: '#f85149',
    borderDownColor: '#f85149',
    borderUpColor: '#3fb950',
    wickDownColor: '#f85149',
    wickUpColor: '#3fb950',
});

// Volume sub-chart (synchronized with price chart)
const volumeChart = createChart('volume-chart-container', {
    width: container.clientWidth,
    height: 120,
    layout: {
        background: { type: ColorType.Solid, color: '#161b22' },
        textColor: '#8b949e',
    },
    timeScale: { borderColor: '#30363d' },
    rightPriceScale: { borderColor: '#30363d' },
});

const volumeSeries = volumeChart.addHistogramSeries({
    color: '#3fb950',
    priceFormat: { type: 'volume' },
});

// Sync time scales
priceChart.timeScale().subscribeVisibleTimeRangeChange(range => {
    volumeChart.timeScale().setVisibleRange(range);
});
volumeChart.timeScale().subscribeVisibleTimeRangeChange(range => {
    priceChart.timeScale().setVisibleRange(range);
});
```

---

## Step 4: Convert Data Format

Lightweight Charts uses a different data format than Chart.js:

**Chart.js format:**
```javascript
{
    labels: ['2024-01-02', '2024-01-03', ...],
    datasets: [{
        data: [100, 102, 98, ...]
    }]
}
```

**Lightweight Charts format (candlestick):**
```javascript
[
    { time: '2024-01-02', open: 100, high: 103, low: 99, close: 102 },
    { time: '2024-01-03', open: 102, high: 105, low: 101, close: 98 },
    ...
]
```

**Conversion function:**
```javascript
function convertOHLCVToCandlestick(data) {
    // data format: [{ date, open, high, low, close, volume }, ...]
    return {
        candlesticks: data.map(d => ({
            time: d.date, // 'YYYY-MM-DD' format
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
        })),
        volumes: data.map(d => ({
            time: d.date,
            value: d.volume,
            color: d.close >= d.open ? '#3fb95040' : '#f8514940',
        })),
    };
}
```

---

## Step 5: Add Technical Indicators as Separate Pane

Lightweight Charts supports adding multiple panes and series:

```javascript
// Add SMA 20 as line overlay on price chart
const sma20Series = priceChart.addLineSeries({
    color: '#d29922',
    lineWidth: 1,
    priceLineVisible: false,
});
sma20Series.setData(sma20Data.map(d => ({ time: d.date, value: d.sma20 })));

// Add RSI in a separate pane
const rsiContainer = document.createElement('div');
rsiContainer.className = 'chart-container';
rsiContainer.style.cssText = 'position:relative;height:150px';
document.querySelector('.main').appendChild(rsiContainer);

const rsiChart = createChart(rsiContainer, {
    height: 150,
    layout: { background: { type: ColorType.Solid, color: '#161b22' }, textColor: '#8b949e' },
    grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
});

const rsiLine = rsiChart.addLineSeries({
    color: '#58a6ff',
    lineWidth: 2,
});
rsiLine.setData(rsiData.map(d => ({ time: d.date, value: d.rsi })));
```

---

## Step 6: Add Time Range Quick-Select Buttons

```html
<div style="display:flex;gap:8px;margin:8px 0">
    <button onclick="setTimeRange('1M')" class="secondary" style="font-size:12px;padding:4px 12px;">1月</button>
    <button onclick="setTimeRange('3M')" class="secondary" style="font-size:12px;padding:4px 12px;">3月</button>
    <button onclick="setTimeRange('6M')" class="secondary" style="font-size:12px;padding:4px 12px;">6月</button>
    <button onclick="setTimeRange('1Y')" class="secondary" style="font-size:12px;padding:4px 12px;">1年</button>
    <button onclick="setTimeRange('ALL')" class="secondary" style="font-size:12px;padding:4px 12px;">全部</button>
</div>
```

```javascript
function setTimeRange(period) {
    const now = new Date();
    let from;
    switch(period) {
        case '1M': from = new Date(now.setMonth(now.getMonth() - 1)); break;
        case '3M': from = new Date(now.setMonth(now.getMonth() - 3)); break;
        case '6M': from = new Date(now.setMonth(now.getMonth() - 6)); break;
        case '1Y': from = new Date(now.setFullYear(now.getFullYear() - 1)); break;
        case 'ALL': from = null; break;
    }
    priceChart.timeScale().setVisibleRange({
        from: from ? from.toISOString().split('T')[0] : firstDate,
        to: lastDate,
    });
}
```

---

## Step 7: Add Signal Markers

Show AlphaPulse-A buy/sell signals on the chart:

```javascript
const markers = signals.map(s => ({
    time: s.date,
    position: s.signal === 'buy' ? 'belowBar' : 'aboveBar',
    color: s.signal === 'buy' ? '#3fb950' : '#f85149',
    shape: s.signal === 'buy' ? 'arrowUp' : 'arrowDown',
    text: s.signal === 'buy' ? 'BUY' : 'SELL',
    size: 2,
}));
candleSeries.setMarkers(markers);
```

---

## Migration Checklist

- [ ] Replace CDN link from Chart.js to lightweight-charts
- [ ] Replace `<canvas>` elements with `<div>` containers
- [ ] Initialize candlestick chart with dark theme matching existing CSS
- [ ] Initialize volume sub-chart with synchronized time scale
- [ ] Convert data format from Chart.js arrays to OHLC objects
- [ ] Add indicator overlays (MA, MACD, RSI) as separate series/panes
- [ ] Add time range quick-select buttons
- [ ] Add trade signal markers (buy/sell arrows)
- [ ] Add crosshair with price/date tooltips
- [ ] Ensure responsive resizing (`ResizeObserver`)
- [ ] Test on all panels: backtest, factors, results, system
- [ ] Remove Chart.js-specific code

---

## Responsive Resize Handler

```javascript
const container = document.getElementById('price-chart-container');
const observer = new ResizeObserver(entries => {
    for (const entry of entries) {
        const { width, height } = entry.contentRect;
        priceChart.applyOptions({ width, height });
    }
});
observer.observe(container);
```

---

## Full Example: `frontend/index_lwc.html`

A complete replacement HTML file is available at `frontend/index_lwc.html`.
Key differences from the original `index.html`:
1. Uses `lightweight-charts` CDN instead of Chart.js
2. OHLC/candlestick data format for backtest results panel
3. Professional crosshair and time navigation
4. Trade signal markers on price chart
5. Dark theme matching existing CSS

To switch: rename `index_lwc.html` to `index.html` (keep backup of old file).
