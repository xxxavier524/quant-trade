# Bug Fix Report

**Date**: 2026-05-16
**Test Suite**: `tests/` (15 tests: `test_factors.py` 10 + `test_strategies.py` 5)

## Result Summary

| Metric | Before Fix | After Fix |
|--------|-----------|-----------|
| Tests Passed | 14 | 15 |
| Tests Failed | 1 | 0 |
| Import Checks Passed | 4/4 | 4/4 |
| Syntax/Compile Errors | 0 | 0 |

---

## Bug 1: `test_all_factors_no_error` -- incorrect bool dtype assertion

**File**: `tests/test_factors.py`, line 191

**Symptom**:
```
AssertionError: NORTHBOUND_FLOW: 非bool类型: float64
```

**Root cause**: The test asserted that all factors except `N_STRUCT` must return `dtype == bool`. However, experimental factors (NORTHBOUND_FLOW, IDIOSYNCRATIC_VOL, TURNOVER_UNIFORMITY, ANALYST_REVISION, CAPITAL_FLOW_BIG) are quantitative factors that legitimately return `float64` (continuous Z-scores). The test did not account for these.

**Fix**: Updated `test_all_factors_no_error` in `tests/test_factors.py` to build a set of non-bool factors dynamically from the registry, exempting both `N_STRUCT` and all factors with `type == "experimental"` (later extended to also exempt `type == "indicator"`).

```python
# Before:
if name != "N_STRUCT":
    assert result.dtype == bool, ...

# After:
NON_BOOL_FACTORS = {"N_STRUCT"}.union(
    name for name, entry in FACTOR_REGISTRY.items()
    if entry.get("type") in ("experimental", "indicator")
)
if name not in NON_BOOL_FACTORS:
    assert result.dtype == bool, ...
```

---

## Bug 2: `BRICK_INDICATOR` returns bool instead of numeric indicator values

**File**: `alphapulse/factors/factor_registry.py` (registry entry) + `alphapulse/factors/brick_ultra.py` (module)

**Symptom**: `BRICK_INDICATOR` was registered as `type: "indicator"` (numeric output) but used the default `brick_ultra.compute()` function which returns `bool` (selection signals). Calling `compute_factor("BRICK_INDICATOR", data)` returned bool instead of the raw brick indicator values.

**Root cause**: The registry had `"module": brick_ultra` and `compute_factor()` always called `entry["module"].compute()`. There was no way to specify an alternative entry point on the module.

**Fix**:
1. Updated `compute_factor()` in `factor_registry.py` to support an optional `compute_func` key on registry entries:
   ```python
   func_name = entry.get("compute_func", "compute")
   func = getattr(entry["module"], func_name)
   return func(data, **merged_params)
   ```
2. Added `"compute_func": "compute_brick_indicator"` to the `BRICK_INDICATOR` registry entry, directing calls to `brick_ultra.compute_brick_indicator()` which returns `float64`.

**Result**: `BRICK_INDICATOR` now returns `float64` (brick indicator values), while `BRICK_ULTRA` continues to return `bool` (selection signals).

---

## Bug 3: `ZHIXING_LINES` returns bool instead of numeric line values

**File**: `alphapulse/factors/factor_registry.py` (registry entry) + `alphapulse/factors/zhixing_washout.py` (module)

**Symptom**: `ZHIXING_LINES` was registered as `type: "indicator"` (numeric output) but used `zhixing_washout.compute()` which returns `bool` (selection signals). Calling `compute_factor("ZHIXING_LINES", data)` returned bool instead of the four-line numeric values.

**Root cause**: Same as Bug 2 -- no `compute_func` mechanism existed, and `zhixing_washout.py` had no function that returned a single numeric `pd.Series` for the indicator values.

**Fix**:
1. Added `compute_indicator()` function to `zhixing_washout.py` that returns a composite score (equal-weighted mean of the four lines: short, medium, med_long, long) as `float64`:
   ```python
   def compute_indicator(data, n1=5, n2=30) -> pd.Series:
       lines = compute_lines(data, n1, n2)
       composite = (lines["short"] + lines["medium"] + lines["med_long"] + lines["long"]) / 4.0
       return composite.fillna(0).astype(float)
   ```
2. Added `"compute_func": "compute_indicator"` to the `ZHIXING_LINES` registry entry.

**Result**: `ZHIXING_LINES` now returns `float64` (composite indicator values in range ~0-100), while `ZHIXING_WASHOUT` continues to return `bool` (selection signals).

---

## Files Modified

| File | Change |
|------|--------|
| `tests/test_factors.py` | Updated `test_all_factors_no_error` to exempt experimental and indicator factors from bool dtype assertion |
| `alphapulse/factors/factor_registry.py` | Added `compute_func` key support to `compute_factor()`; updated `BRICK_INDICATOR` and `ZHIXING_LINES` entries |
| `alphapulse/factors/zhixing_washout.py` | Added `compute_indicator()` function returning numeric composite score |

## Verification

All 15 tests pass:
```
tests/test_factors.py::test_n_struct PASSED
tests/test_factors.py::test_vol_red_green PASSED
tests/test_factors.py::test_abnormal_vol PASSED
tests/test_factors.py::test_vol_cont_shrink PASSED
tests/test_factors.py::test_kdj_j_low PASSED
tests/test_factors.py::test_weekly_ma_bull PASSED
tests/test_factors.py::test_macd_bull_dead PASSED
tests/test_factors.py::test_shrink_to_abnormal PASSED
tests/test_factors.py::test_factor_registry PASSED
tests/test_factors.py::test_all_factors_no_error PASSED
tests/test_strategies.py::test_b1_formula_strategy_signal_format PASSED
tests/test_strategies.py::test_b1_formula_edge_cases PASSED
tests/test_strategies.py::test_b1_enhanced_strategy_signal_format PASSED
tests/test_strategies.py::test_needle_strategy_compatibility PASSED
tests/test_strategies.py::test_needle_enhanced_compat PASSED
```

All import checks pass:
- `alphapulse.factors` -- OK
- `alphapulse.strategies` -- OK
- `alphapulse.factors.experimental` -- OK
- Individual strategy modules (b1_enhanced, b1_formula_strategy, brick_ultra_strategy, needle_enhanced) -- OK
