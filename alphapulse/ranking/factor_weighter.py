"""IC-IR factor weighter with exponential decay and rank IC computation."""
import json
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


def compute_rank_ic(factor_values, forward_returns) -> float:
    """Spearman rank IC between factor values and forward returns.

    Args:
        factor_values: array-like, factor values for each stock
        forward_returns: array-like, forward returns for each stock

    Returns:
        Rank IC (Spearman correlation) as float. 0.0 if fewer than 30
        valid paired samples.
    """
    factor_vals = pd.to_numeric(pd.Series(factor_values), errors="coerce")
    fwd_returns = pd.to_numeric(pd.Series(forward_returns), errors="coerce")
    mask = factor_vals.notna() & fwd_returns.notna()
    if mask.sum() < 30:
        return 0.0
    ic, _ = stats.spearmanr(factor_vals[mask], fwd_returns[mask])
    if np.isnan(ic):
        return 0.0
    return float(ic)


def compute_ic_ir(ic_series) -> float:
    """Compute Information Coefficient Information Ratio (IC IR).

    IC IR = mean(IC) / std(IC). A higher IC IR means more consistent IC.

    Args:
        ic_series: array-like of daily cross-sectional IC values

    Returns:
        IC IR as float. 0.0 if fewer than 5 samples or std == 0.
    """
    ics = pd.to_numeric(pd.Series(ic_series), errors="coerce").dropna()
    if len(ics) < 5:
        return 0.0
    std_ic = ics.std(ddof=1)
    if np.isclose(std_ic, 0.0):
        return 0.0
    return float(ics.mean() / std_ic)


def exponential_decay_weight(ic_series, half_life: int = 30) -> float:
    """Exponentially decay-weighted mean IC.

    Recent values receive higher weight.  lambda = ln(2) / half_life.

    Args:
        ic_series: array-like of daily IC values ordered from oldest to newest
        half_life: number of periods after which weight halves

    Returns:
        Decay-weighted mean IC as float.
    """
    ics = pd.to_numeric(pd.Series(ic_series), errors="coerce").dropna().values
    n = len(ics)
    if n == 0:
        return 0.0
    lam = np.log(2) / half_life
    # Weights: most recent observation at index n-1 gets highest weight
    weights = np.exp(-lam * np.arange(n - 1, -1, -1))
    weights = weights / weights.sum()
    return float(np.dot(ics, weights))


class FactorWeighter:
    """Dynamic factor weighting based on IC-IR and exponential decay.

    Tracks per-strategy per-factor IC history, computes weights by combining
    exponentially decay-weighted IC with an IC-IR boost factor.
    """

    def __init__(self, config_path: str = "config/factor_weights.json"):
        self.config_path = config_path
        self.weights: dict = {}        # strategy -> {factor: weight}
        self.ic_history: dict = {}     # strategy -> {factor: [ic_values]}
        self._load()

    def _load(self) -> None:
        """Load weights and IC history from JSON file."""
        path = Path(self.config_path)
        if not path.exists():
            logger.info("Factor weights config not found at %s, starting fresh.", self.config_path)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.weights = data.get("weights", {})
            self.ic_history = data.get("ic_history", {})
            logger.info("Loaded factor weights from %s", self.config_path)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load factor weights: %s", e)

    def save(self) -> None:
        """Persist weights and IC history to JSON."""
        path = Path(self.config_path)
        # 防清空：_load 失败时 self.weights 为空，直接落盘会把 IC 调优出的生产权重
        # （如 B1_SCORE）整体覆盖没——空权重 + 目标文件非空 = 拒绝保存
        if not self.weights and path.exists() and path.stat().st_size > 10:
            logger.warning("weights 为空且 %s 非空——疑似加载失败，拒绝覆盖保存", path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "weights": self.weights,
            "ic_history": self.ic_history,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Saved factor weights to %s", self.config_path)

    def update_ic(self, strategy: str, factor_name: str,
                  factor_df: pd.DataFrame, forward_col: str) -> None:
        """Compute daily cross-sectional IC values and append to history.

        For each date in factor_df, computes the Spearman rank IC between the
        factor column and the forward return column across stocks.

        Args:
            strategy: strategy identifier string
            factor_name: factor column name in factor_df
            factor_df: DataFrame with factor values and forward returns,
                       indexed by date (level 0) with factor_name and
                       forward_col as columns
            forward_col: column name for forward returns
        """
        if factor_name not in factor_df.columns or forward_col not in factor_df.columns:
            logger.warning("Columns %s or %s missing from factor_df", factor_name, forward_col)
            return

        daily_ics = []
        # Group by date: assume first index level is date, or group on it
        if isinstance(factor_df.index, pd.MultiIndex):
            groupby = factor_df.groupby(level=0)
        else:
            groupby = factor_df.groupby(factor_df.index)

        for _, group in groupby:
            ic_val = compute_rank_ic(group[factor_name], group[forward_col])
            daily_ics.append(ic_val)

        # Store in ic_history
        self.ic_history.setdefault(strategy, {}).setdefault(factor_name, []).extend(daily_ics)
        # Keep only the last 252 values
        if len(self.ic_history[strategy][factor_name]) > 252:
            self.ic_history[strategy][factor_name] = \
                self.ic_history[strategy][factor_name][-252:]

        logger.debug("Updated IC for %s/%s: added %d values, total %d",
                     strategy, factor_name, len(daily_ics),
                     len(self.ic_history[strategy][factor_name]))

    def compute_weights(self, strategy: str, half_life: int = 30) -> dict:
        """Compute factor weights for a strategy using IC-IR and decay.

        For each factor:
        1. Exponentially decay-weighted mean IC (recent-centric)
        2. IC-IR boost factor clamped to [0.8, 1.5]
        3. Raw weight = decay_ic * boost
        4. Normalize all raw weights to sum to 1

        Args:
            strategy: strategy identifier
            half_life: half-life for exponential decay weighting

        Returns:
            dict mapping factor_name -> normalized weight
        """
        raw = {}
        factors = self.ic_history.get(strategy, {})
        if not factors:
            logger.warning("No IC history for strategy '%s'", strategy)
            return {}

        for fname, ic_list in factors.items():
            # 1. Decay-weighted mean IC
            decay_ic = exponential_decay_weight(ic_list, half_life=half_life)

            # 2. IC-IR boost (higher for consistent IC)
            ic_ir = compute_ic_ir(ic_list)
            boost = np.clip(1.0 + ic_ir * 0.5, 0.8, 1.5)

            # 3. Raw weight: 用"有符号"IC，负IC截零（2026-07-28 修正）。
            #    此前用 abs(decay_ic)：一个稳定反向预测（IC 显著为负）的因子会拿到
            #    与同等强度正向因子一样大的正权重，等于把反指当正指用。
            #    与 scripts/ic_weight_tuning.py 的 clip(lower=0) 口径保持一致。
            raw_w = max(0.0, decay_ic) * boost
            raw[fname] = raw_w

        total = sum(raw.values())
        if total == 0:
            return {}

        normalized = {k: v / total for k, v in raw.items()}
        self.weights[strategy] = normalized
        return normalized

    def get_weights(self, strategy: str) -> dict:
        """Get cached weights for a strategy, computing them if absent.

        Args:
            strategy: strategy identifier

        Returns:
            dict mapping factor_name -> normalized weight (sums to 1)
        """
        if strategy in self.weights:
            return self.weights[strategy]
        return self.compute_weights(strategy)
