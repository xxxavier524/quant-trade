---
name: paper-search
description: Search arxiv q-fin for quant finance papers and download PDFs. Covers all q-fin subcategories (CP/EC/GN/MF/PM/PR/RM/ST/TR). Outputs papers/<arxiv-id>/paper.pdf and meta.json.
---

# Paper Search — Arxiv Quant Finance Paper Retrieval

Search arxiv quantitative finance papers and download PDFs to local storage.

## Search Scope

Default: all q-fin subcategories:
- **CP** — Computational Finance
- **EC** — Economics
- **GN** — General
- **MF** — Mathematical Finance
- **PM** — Portfolio Management
- **PR** — Pricing
- **RM** — Risk Management
- **ST** — Statistical Finance
- **TR** — Trading

## Search Modes

1. **Keyword search**: `--query "cross-sectional momentum" --categories q-fin.PM,q-fin.TR`
2. **Arxiv ID lookup**: `--arxiv-id 2403.12345`
3. **Batch download**: `--arxiv-ids 2403.12345,2404.56789`
4. **Time range**: `--from 2024-01-01 --to 2024-06-30`

## Rate Limiting

Arxiv API requires 3-second throttle between requests. Always sleep 3s between API calls.

## Output Structure

Each paper creates `papers/<arxiv-id>/`:
```
papers/2403.12345/
  paper.pdf          # downloaded PDF (if available)
  meta.json          # structured metadata
```

## meta.json Schema

```json
{
  "arxiv_id": "2403.12345",
  "title": "Cross-Sectional Momentum and Liquidity Risk",
  "authors": ["Zhang, L.", "Kumar, R."],
  "categories": ["q-fin.PM", "q-fin.TR"],
  "published": "2024-03-18",
  "pdf_url": "http://arxiv.org/pdf/2403.12345",
  "abstract": "...",
  "downloaded_at": "2026-05-21T10:00:00"
}
```

## Implementation

Use `urllib` + `xml.etree.ElementTree` to parse arxiv API (no extra deps):
- API endpoint: `http://export.arxiv.org/api/query?search_query={query}&max_results={n}`
- PDF URL pattern: `https://arxiv.org/pdf/{arxiv_id}.pdf`

## Usage Examples

- "用 paper-search 找最近6个月 q-fin.PM 里关于 cross-sectional momentum 的论文，最多10篇"
- "用 paper-search 按 arxiv id 2403.12345 下载这篇论文"
- "搜索 q-fin.TR 中关于 limit order book 的论文，从2024年开始"

## Anti-patterns

- Don't scrape arxiv HTML pages — use the official API
- Don't skip the 3-second throttle
- Don't create papers/ without meta.json (breaks downstream pipeline)
