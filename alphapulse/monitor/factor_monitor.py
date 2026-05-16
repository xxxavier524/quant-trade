"""因子有效性监控。

规格书4.5节：IC计算、ICIR、因子衰减、自动剔除与状态标记。
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


class FactorMonitor:
    """因子有效性持续监控。"""

    def __init__(
        self,
        ic_threshold: float = 0.02,
        decay_window: int = 20,
        remove_threshold: float = 0.01,
    ):
        self.ic_threshold = ic_threshold
        self.decay_window = decay_window
        self.remove_threshold = remove_threshold
        self.ic_history: dict[str, list[float]] = {}

    def calc_ic(self, factor_values: pd.Series, forward_returns: pd.Series) -> float:
        """计算Spearman秩相关系数IC。"""
        valid = factor_values.notna() & forward_returns.notna()
        if valid.sum() < 10:
            return np.nan
        ic, _ = spearmanr(factor_values[valid], forward_returns[valid])
        return float(ic)

    def daily_update(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
    ) -> dict:
        """每日更新所有因子的IC并判定状态。

        Args:
            factor_df: 因子矩阵（行为股票，列为因子）
            return_df: 收益DataFrame，需含 'forward_return' 列

        Returns:
            dict: {factor_name: {daily_ic, mean_ic_Nd, status, ...}}
        """
        report = {}
        for col in factor_df.columns:
            if not col.startswith("f_"):
                continue
            ic = self.calc_ic(factor_df[col], return_df["forward_return"])

            if col not in self.ic_history:
                self.ic_history[col] = []
            self.ic_history[col].append(ic)

            recent = [v for v in self.ic_history[col][-self.decay_window :] if not np.isnan(v)]
            mean_ic = np.mean(recent) if recent else 0.0

            if len(recent) >= self.decay_window and abs(mean_ic) < self.remove_threshold:
                status = "REMOVE"
            elif abs(mean_ic) < self.ic_threshold:
                status = "WATCH"
            else:
                status = "ACTIVE"

            report[col] = {
                "daily_ic": round(ic, 4) if not np.isnan(ic) else None,
                "mean_ic_20d": round(mean_ic, 4),
                "status": status,
                "data_points": len(recent),
            }

        return report

    def get_removed_factors(self) -> list[str]:
        """获取应剔除的因子列表。"""
        removed = []
        for name, history in self.ic_history.items():
            recent = [v for v in history[-self.decay_window :] if not np.isnan(v)]
            if len(recent) >= self.decay_window and abs(np.mean(recent)) < self.remove_threshold:
                removed.append(name)
        return removed

    def get_active_factors(self) -> list[str]:
        """获取当前有效的因子列表。"""
        removed = set(self.get_removed_factors())
        return [f for f in self.ic_history if f not in removed]
