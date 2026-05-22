---
name: paper-extract
description: Extract structured research notes and metrics JSON from quant finance PDFs. Uses PyMuPDF for text extraction, math font detection for formulas, regex for reported metrics. Outputs papers/<arxiv-id>/note.md and metrics.json.
---

# Paper Extract — PDF to Structured Research Notes

Extract key information from quant finance PDFs into machine-readable and human-readable formats.

## Extraction Pipeline

### 1. Text Extraction (PyMuPDF / fitz)
- Extract all text blocks with font metadata
- Identify section boundaries by font size changes (title > heading > body)
- Preserve reading order (left-to-right, top-to-bottom within columns)

### 2. Formula Detection
Scan for math content by detecting:
- Math fonts: CMMI, CMSY, CMEX (LaTeX math mode fonts)
- Greek letters (α, β, σ, μ, ±, Σ, Π) in text
- Equation number patterns: `(1)`, `Eq. 1`, `Equation 1`
- Sum/integral/equality symbols clustered in close proximity

"Core formulas" = formulas in Methodology section that are cited in Results section.

### 3. Metrics Scanning
Regex patterns for reported performance metrics:

```
Sharpe:       sharpe|sharpe ratio|SR\\b
Max DD:       max(imum)?\s*(drawdown|draw-down)|MDD\\b
Ann Return:   annual(ized)?\s*(return|yield)|CAGR\\b
Volatility:   annual(ized)?\s*volatility|vol\\b
Calmar:       calmar|calmar ratio\\b
IR:           information\s*ratio|IR\\b
Win Rate:     win\s*(rate|ratio)|hit\s*ratio\\b
```

Each match captures: metric name, value, variant (e.g. "12m lookback"), page number, context (surrounding sentences).

### 4. Data Period Detection
Look for: date ranges (`1990-01 to 2020-12`), frequency (`daily`, `monthly`, `weekly`), and asset universe descriptions.

## Output Files

### note.md (human-readable)

```markdown
# [Paper Title]

**Authors**: [authors]
**Arxiv ID**: [id]
**Published**: [date]

## TL;DR
[1-2 sentence takeaway]

## Data
- Period: [start] to [end]
- Frequency: [daily/monthly/...]
- Universe: [description]
- Sources: [data vendors]

## Methodology
- Signal type: [momentum/mean-reversion/...]
- Key formulas: [Eq. numbers with context]
- Parameters: [key parameter choices]

## Core Formulas
- **Eq. 3** (pg 7): r_{i,t} = (1/L) * sum_{k=1..L} ret_{i,t-k}
- **Eq. 5** (pg 9): w_{i,t} = score_{i,t} / sum(score)

## Reported Metrics
[table of metrics with variants]

## Replication Open Questions
[assumptions not specified in paper, ambiguities, data gaps]
```

### metrics.json (machine-readable)

```json
{
  "arxiv_id": "2403.12345",
  "title": "...",
  "reported_metrics": [
    {"name": "sharpe", "value": 1.42, "variant": "12m lookback", "page": 14},
    {"name": "max_drawdown", "value": -0.18, "variant": "12m lookback", "page": 14}
  ],
  "core_formulas": [
    {"label": "Eq. 3", "section": "Methodology", "page": 7,
     "text": "r_{i,t} = (1/L) * sum_{k=1..L} ret_{i,t-k}"}
  ],
  "data_period": {"start": "1990-01", "end": "2020-12", "frequency": "daily"},
  "asset_universe": ["CRSP common stocks", "NYSE/AMEX/NASDAQ"],
  "key_parameters": {"lookback": 12, "holding_period": 1, "top_quintile": 0.2}
}
```

## Deliberate Omissions

- Does NOT attempt LaTeX rendering of extracted math (PyMuPDF math extraction is lossy — expected behavior)
- Does NOT hallucinate missing metrics — if a value isn't found, omit it
- Does NOT normalize metric names (keep paper's terminology for traceability)

## Dependencies

```bash
pip install PyMuPDF  # fitz module
```
No other dependencies needed — regex and stdlib for everything else.
