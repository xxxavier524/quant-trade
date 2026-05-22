---
name: strategy-translate
description: Translate validated vectorized strategy into event-driven production code. Converts pandas vectorized logic to on_bar event handlers with contract sizing, margin checks, and unit tests. Requires framework_spec.md before execution.
---

# Strategy Translate — Vectorized to Event-Driven Production

Translate a validated vectorized strategy from `papers/<arxiv-id>/` into production-ready event-driven code.

**Prerequisite**: `framework_spec.md` must exist with the team's event-driven framework specification. This skill refuses to guess — it errors out with a checklist of what's missing.

## What This Step Solves

Vectorized code (pandas) and event-driven code (on_bar handlers) are fundamentally different paradigms:

| Vectorized | Event-Driven |
|------------|-------------|
| `weights.shift(1) * returns` | Incremental P&L in `on_bar` |
| `pd.DataFrame` look-ahead OK if shifted | No look-ahead, strict time ordering |
| Float weights | Integer contracts |
| No margin concept | `abs(contracts) * price * multiplier * margin_rate ≤ capital` |

Mixing them creates production bugs. This skill handles the translation.

## Input Requirements

From `papers/<arxiv-id>/`:
- `signal.py` — validated signal function
- `metrics.json` — reference metrics

From team config:
- `framework_spec.md` — event types, function signatures, position API

## Framework Spec Format

`framework_spec.md` must define:

```markdown
## Event Loop
- on_bar(symbol, timestamp, o, h, l, c, v) — called each bar
- on_order_filled(order_id, fill_price, fill_qty) — async fill callback

## Position API
- get_position(symbol) -> {size, avg_cost, unrealized_pnl}
- get_capital() -> float (available buying power)

## Order API
- send_order(symbol, qty, order_type, limit_price=None) -> order_id
- cancel_order(order_id) -> bool

## Contract Specs
- multiplier: int (e.g., CSI300 futures = 300)
- margin_rate: float (e.g., 0.12)
- tick_size: float
```

## Output

For each strategy, produce `papers/<arxiv-id>/production/`:

```
production/
  strategy.py         # event-driven strategy class
  test_strategy.py    # unit tests for sizing + margin
```

### strategy.py Template

```python
class Strategy:
    def __init__(self, capital, contract_specs):
        self.capital = capital
        self.multiplier = contract_specs['multiplier']
        self.margin_rate = contract_specs['margin_rate']

    def on_bar(self, symbol, timestamp, o, h, l, c, v):
        signal = self._compute_signal(symbol, c)  # call ported logic
        if signal != 0:
            target_notional = self._size_position(signal, c)
            contracts = self._size_contracts(target_notional, c)
            if contracts != 0:
                return {'action': 'ORDER', 'symbol': symbol, 'qty': contracts}
        return None

    def _size_contracts(self, target_notional, price):
        contracts = round(target_notional / (price * self.multiplier))
        margin_required = abs(contracts) * price * self.multiplier * self.margin_rate
        if margin_required > self.capital:
            scale = self.capital / margin_required
            contracts = int(contracts * scale)
        return contracts
```

### test_strategy.py (MANDATORY)

Contract sizing and margin checks MUST have unit tests — this is the bug class that costs real money:

```python
def test_size_contracts_rounds_down():
    """Fractional contracts round to nearest integer."""
    ...

def test_size_contracts_margin_ceiling():
    """Position cannot exceed available margin."""
    ...

def test_size_contracts_zero_when_insufficient():
    """Return 0 when margin requirement > capital."""
    ...

def test_size_contracts_negative_for_shorts():
    """Short positions produce negative contract counts."""
    ...
```

## Execution Flow

1. Read `framework_spec.md` — if missing, output checklist and exit
2. Read `papers/<arxiv-id>/signal.py` — understand the signal logic
3. Map vectorized operations to event-driven equivalents:
   - Rolling windows → ring buffers or deque
   - Cross-sectional rankings → per-bar ranking with lookback window
   - `shift(1)` → use previous bar's computed value
4. Write `strategy.py` with the event-driven class
5. Write `test_strategy.py` with sizing/margin tests
6. Verify tests pass

## Anti-Patterns (Hard Blocks)

- **NEVER guess the framework spec** — if `framework_spec.md` is missing or incomplete, output exactly what's needed and exit
- **NEVER use look-ahead** — `on_bar` sees current bar only, plus stored history
- **NEVER use float positions for futures** — integer contracts only
- **NEVER skip margin checks**
- **NEVER skip unit tests on sizing functions**
