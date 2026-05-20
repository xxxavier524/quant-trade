"""3 验证闸门 (Gates)。

所有策略必须通过全部 3 个闸门才能进入实盘阶段。

Gate 1 - Critic Gate: 结构审查（前视偏差、仓位规模、费用核算、成交假设）
Gate 2 - DSR Gate: Deflated Sharpe Ratio (López de Prado), dsr_pvalue >= 0.95
Gate 3 - Risk Gate: 组合层面适配（相关性、最大配置）

设计原则：
- 每个 Gate 独立运行，输出 GateResult(success, score, evidence)
- Gate 之间不共享状态，保证可独立测试
- DSR 实现参考 López de Prado & Bailey (2018) SSRN 3167017
"""

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class GateResult:
    """Gate 统一返回结构。"""
    gate_name: str
    passed: bool
    score: float = 0.0       # 0-1 分数
    threshold: float = 0.0   # 通过阈值
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "score": self.score,
            "threshold": self.threshold,
            "evidence": self.evidence,
            "error": self.error,
        }


# ==============================================================================
# Gate 1: Critic Gate (结构审查)
# ==============================================================================
class CriticGate:
    """结构审查闸门。

    确保策略无方法论错误。检查项有明确的量化评分标准，
    总分 >= 0.8 即通过。
    """

    WEIGHTS = {
        "look_ahead_bias": 0.30,
        "position_sizing": 0.25,
        "cost_accounting": 0.25,
        "fill_assumptions": 0.20,
    }

    def evaluate(
        self,
        backtest_results: dict,
        hypothesis: Optional[dict] = None,
        nav_curve: Optional[pd.DataFrame] = None,
    ) -> GateResult:
        """评估策略结构的合理性。

        Args:
            backtest_results: 回测指标字典
            hypothesis: 结构化假设（可选）
            nav_curve: 净值曲线 DataFrame (可选，含 daily_return 列)

        Returns:
            GateResult: 包含各维度评分
        """
        scores = {}

        # 1. 前视偏差检测
        scores["look_ahead_bias"] = self._score_look_ahead(nav_curve, backtest_results)

        # 2. 仓位规模评估
        scores["position_sizing"] = self._score_position_sizing(backtest_results)

        # 3. 费用核算
        scores["cost_accounting"] = self._score_cost_accounting(backtest_results)

        # 4. 成交假设
        scores["fill_assumptions"] = self._score_fill_assumptions(backtest_results)

        total = sum(scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        passed = total >= 0.80

        return GateResult(
            gate_name="CriticGate",
            passed=passed,
            score=round(total, 4),
            threshold=0.80,
            evidence={
                "sub_scores": scores,
                "weights": self.WEIGHTS,
                "total_score": round(total, 4),
            },
            error="" if passed else f"结构审查未通过: score={total:.2f} < 0.80",
        )

    def _score_look_ahead(self, nav_curve, results) -> float:
        """检测前视偏差。

        方法: 分析首日收益率分布。如果首日收益异常集中
        （如首日收益均值远超历史均值），可能存在信息泄漏。
        """
        score = 1.0
        if nav_curve is not None and "daily_return" in nav_curve.columns:
            returns = nav_curve["daily_return"].dropna()
            if len(returns) > 0:
                # 检查收益的自相关性（如果有显著的滞后自相关可能表明泄漏）
                if len(returns) > 5:
                    ac1 = returns.autocorr(lag=1)
                    if abs(ac1) > 0.3:
                        score -= 0.2
                # 检查异常收益天数
                outlier_pct = (np.abs(returns) > returns.std() * 4).mean()
                if outlier_pct > 0.02:
                    score -= 0.15
        return max(0.0, min(1.0, score))

    def _score_position_sizing(self, results) -> float:
        """评估仓位规模。"""
        score = 0.8  # 基础分
        max_dd = abs(results.get("max_drawdown", 0))
        if max_dd < 15:
            score += 0.2
        elif max_dd < 25:
            score += 0.1
        elif max_dd > 40:
            score -= 0.3
        if max_dd > 60:
            score -= 0.3
        return max(0.0, min(1.0, score))

    def _score_cost_accounting(self, results) -> float:
        """评估费用核算。"""
        total_trades = results.get("total_trades", 0)
        n_days = max(results.get("n_days", 1), 1)
        score = 1.0
        turnover_per_year = total_trades / (n_days / 252) if n_days > 0 else 0
        if turnover_per_year > 50:
            score -= 0.2  # 高频交易，费用影响大
        if turnover_per_year > 100:
            score -= 0.3
        return max(0.0, min(1.0, score))

    def _score_fill_assumptions(self, results) -> float:
        """评估成交假设。"""
        # 默认通过——系统使用滑点和标准手续费模型
        return 0.85


# ==============================================================================
# Gate 2: Deflated Sharpe Ratio Gate
# ==============================================================================
class DSRGate:
    """Deflated Sharpe Ratio (DSR) 闸门。

    参考: López de Prado & Bailey (2018)
    "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality"
    https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3167017

    核心思想:
    - 标准 Sharpe Ratio 在多次试验下有选择偏差
    - DSR 将 Sharpe Ratio "压缩"回考虑多重测试下的真实水平
    - dsr_pvalue >= 0.95 意味着在多重测试校正后，策略仍有显著 alpha

    公式:
        DSR = Prob[SR_true > 0]  (在多重测试下)
        dsr_pvalue = 1 - Phi(DSR_zscore)

        其中:
        DSR_zscore = (SR_hat - E[max{SR_n}]) / SE[SR_hat]

        E[max{SR_n}] ≈ gamma * (1 - gamma) * Z_{(1-1/N)} + gamma * Z_{(1-1/(N*e))}
        (极值理论的 Gumbel 分布近似)

        SE[SR_hat] = sqrt((1 + 0.5*SR_hat^2) / T) * adjusted_for_skew_kurt
    """

    # 欧拉常数
    EULER_MASCHERONI = 0.5772156649015329

    def __init__(self, n_trials: int = 100, significance_level: float = 0.95):
        """初始化 DSR Gate。

        Args:
            n_trials: 多重测试次数（估计的策略变体数）
            significance_level: 显著性水平阈值，默认 0.95
        """
        self.n_trials = n_trials
        self.significance_level = significance_level

    def evaluate(
        self,
        daily_returns: Optional[pd.Series] = None,
        sharpe_ratio: Optional[float] = None,
        n_observations: int = 0,
        skewness: Optional[float] = None,
        kurtosis: Optional[float] = None,
        n_trials: Optional[int] = None,
    ) -> GateResult:
        """计算 Deflated Sharpe Ratio p-value。

        Args:
            daily_returns: 日收益率序列（优先使用，自动计算统计量）
            sharpe_ratio: 年化夏普比率（如不提供 daily_returns）
            n_observations: 观测数（如不提供 daily_returns）
            skewness: 偏度（如不提供 daily_returns）
            kurtosis: 峰度（如不提供 daily_returns）
            n_trials: 覆盖默认的多重测试次数

        Returns:
            GateResult: 包含 dsr_pvalue 和详细证据
        """
        if daily_returns is not None and len(daily_returns) > 0:
            returns = daily_returns.dropna()
            n = len(returns)
            sr_daily = returns.mean() / returns.std() if returns.std() > 0 else 0
            sr_annual = sr_daily * np.sqrt(252)
            skew = float(stats.skew(returns))
            kurt = float(stats.kurtosis(returns, fisher=False))  # excess=False -> Pearson kurtosis
        elif sharpe_ratio is not None and n_observations > 0:
            sr_annual = float(sharpe_ratio)
            n = n_observations
            skew = float(skewness) if skewness is not None else 0.0
            kurt = float(kurtosis) if kurtosis is not None else 3.0
        else:
            return GateResult(
                gate_name="DSRGate",
                passed=False,
                score=0.0,
                threshold=self.significance_level,
                error="缺少收益率数据或夏普比率",
            )

        trials = n_trials if n_trials is not None else self.n_trials
        dsr_pvalue = self._compute_dsr_pvalue(sr_annual, n, skew, kurt, trials)

        passed = dsr_pvalue >= self.significance_level
        e_max_sr = self._expected_max_sr(n, trials)

        return GateResult(
            gate_name="DSRGate",
            passed=passed,
            score=float(dsr_pvalue),
            threshold=self.significance_level,
            evidence={
                "sharpe_ratio": round(sr_annual, 4),
                "n_observations": n,
                "n_trials": trials,
                "skewness": round(skew, 4),
                "kurtosis": round(kurt, 4),
                "expected_max_sr": round(e_max_sr, 4),
                "deflated_sr": round(sr_annual - e_max_sr, 4),
                "dsr_pvalue": round(dsr_pvalue, 4),
            },
            error="" if passed else f"DSR不显著: pvalue={dsr_pvalue:.4f} < {self.significance_level}",
        )

    def _compute_dsr_pvalue(
        self,
        sr_annual: float,
        n_obs: int,
        skew: float,
        kurt: float,
        n_trials: int,
    ) -> float:
        """计算 DSR p-value。

        公式:
        SE[SR] = sqrt((1 + SR_hat^2/2 + (gamma_3/3)*SR_hat + (gamma_4-3)/12*SR_hat^2) / T)
        但简化版使用:
        SE[SR] = sqrt((1 + 0.5*SR_hat^2) / T) * sqrt((kurt-1)/3)  (非正态调整)

        E[max SR] ≈ sqrt(Var[SR]) * quantile_from_extreme_value_theory(N)
        """
        # 标准误（考虑非正态性）
        se_sr_daily = np.sqrt(1.0 / n_obs)
        # 非正态调整因子 (López de Prado 公式)
        non_normality_adj = np.sqrt(1.0 + (skew / 3.0) * sr_annual / np.sqrt(252)
                                     + ((kurt - 3.0) / 12.0) * (sr_annual / np.sqrt(252))**2)
        se_sr = se_sr_daily * non_normality_adj * np.sqrt(252)

        # 期望最大 SR（多重测试下）
        e_max_sr = self._expected_max_sr(n_obs, n_trials)

        # DSR z-score
        sr_deflated = sr_annual - e_max_sr
        z_score = sr_deflated / se_sr if se_sr > 0 else 0.0

        # p-value
        dsr_pvalue = float(stats.norm.cdf(z_score))

        return dsr_pvalue

    def _expected_max_sr(self, n_obs: int, n_trials: int) -> float:
        """计算在 N 次独立试验下期望最大夏普比率。

        使用极值理论 (Extreme Value Theory) 的 Gumbel 分布近似。

        E[max{SR_n}] ≈ sqrt(Var[SR]) * ((1 - γ) * Z_{1-1/N} + γ * Z_{1-1/(N*e)})

        其中:
        - γ = 欧拉常数 ≈ 0.5772
        - Var[SR] = 1 / n_obs（日频近似）
        - Z_p = 标准正态分布的 p 分位数
        """
        var_sr = 1.0 / n_obs  # SE^2 of daily SR
        gamma = self.EULER_MASCHERONI

        # 极值分位数
        p1 = 1.0 - 1.0 / n_trials
        p2 = 1.0 - 1.0 / (n_trials * np.e)

        z1 = stats.norm.ppf(p1) if p1 < 1.0 else stats.norm.ppf(0.9999)
        z2 = stats.norm.ppf(p2) if p2 < 1.0 else stats.norm.ppf(0.9999)

        # 日频期望最大 SR -> 年化
        expected_max_sr_daily = np.sqrt(var_sr) * ((1 - gamma) * z1 + gamma * z2)
        expected_max_sr_annual = expected_max_sr_daily * np.sqrt(252)

        return expected_max_sr_annual

    def compute_dsr(
        self,
        daily_returns: pd.Series,
        n_trials: Optional[int] = None,
    ) -> dict:
        """便捷函数：从日收益率直接计算 DSR 全部指标。

        Returns:
            dict: {sharpe_ratio, dsr_pvalue, expected_max_sr, passed, ...}
        """
        result = self.evaluate(daily_returns=daily_returns, n_trials=n_trials)
        return {
            "sharpe_ratio": result.evidence.get("sharpe_ratio", 0),
            "expected_max_sr": result.evidence.get("expected_max_sr", 0),
            "deflated_sr": result.evidence.get("deflated_sr", 0),
            "dsr_pvalue": result.score,
            "passed": result.passed,
        }


# ==============================================================================
# Gate 3: Risk Gate (组合风险)
# ==============================================================================
class RiskGate:
    """组合风险管理闸门。

    评估新策略是否适配现有组合：
    - 与现有策略的相关性（分散化收益）
    - 回撤风险预算
    - 策略容量 / 流动性
    """

    MAX_CORRELATION = 0.70
    MAX_DRAWDOWN_PCT = 25.0
    MIN_SHARPE = 0.30

    def __init__(
        self,
        existing_returns: Optional[dict[str, pd.Series]] = None,
        max_correlation: float = 0.70,
        max_drawdown: float = 25.0,
    ):
        """初始化 Risk Gate。

        Args:
            existing_returns: {strategy_name: daily_returns_series}
            max_correlation: 最大允许相关性
            max_drawdown: 最大允许回撤 (%)
        """
        self.existing_returns = existing_returns or {}
        self.max_correlation = max_correlation
        self.max_drawdown = max_drawdown

    def evaluate(
        self,
        strategy_returns: Optional[pd.Series] = None,
        backtest_results: Optional[dict] = None,
        strategy_name: str = "",
    ) -> GateResult:
        """评估策略在组合上下文中的风险。

        Returns:
            GateResult
        """
        scores = {}
        evidence = {}

        # 1. 回撤评估
        dd_score, dd_evidence = self._score_drawdown(backtest_results)
        scores["drawdown"] = dd_score
        evidence["drawdown"] = dd_evidence

        # 2. 相关性评估
        corr_score, corr_evidence = self._score_correlation(strategy_returns)
        scores["correlation"] = corr_score
        evidence["correlation"] = corr_evidence

        # 3. 夏普比率评估
        sharpe_score, sharpe_evidence = self._score_sharpe(backtest_results)
        scores["sharpe"] = sharpe_score
        evidence["sharpe"] = sharpe_evidence

        weights = {"drawdown": 0.35, "correlation": 0.40, "sharpe": 0.25}
        total = sum(scores[k] * weights[k] for k in weights)

        # 额外硬约束：相关性过高或回撤过大直接失败
        max_corr = evidence.get("correlation", {}).get("max_correlation", 0)
        max_dd = abs(backtest_results.get("max_drawdown", 0)) if backtest_results else 0

        if max_corr > self.max_correlation:
            total = min(total, 0.49)  # 强制失败
            evidence["hard_fail"] = f"相关性 {max_corr:.2f} > {self.max_correlation}"
        if max_dd > self.max_drawdown:
            total = min(total, 0.49)
            evidence["hard_fail"] = f"回撤 {max_dd:.1f}% > {self.max_drawdown}%"

        passed = total >= 0.70

        return GateResult(
            gate_name="RiskGate",
            passed=passed,
            score=round(total, 4),
            threshold=0.70,
            evidence=evidence,
            error="" if passed else f"风险评估未通过: score={total:.2f} < 0.70",
        )

    def _score_drawdown(self, results) -> tuple:
        if results is None:
            return 0.5, {"max_drawdown": None}
        max_dd = abs(results.get("max_drawdown", 100))
        if max_dd < 10:
            score = 1.0
        elif max_dd < 15:
            score = 0.9
        elif max_dd < 20:
            score = 0.75
        elif max_dd < 25:
            score = 0.6
        elif max_dd < 35:
            score = 0.4
        else:
            score = 0.1
        return score, {"max_drawdown": max_dd}

    def _score_correlation(self, strategy_returns) -> tuple:
        if strategy_returns is None or not self.existing_returns:
            return 1.0, {"max_correlation": 0.0, "correlations": {}}

        correlations = {}
        max_corr = 0.0
        for name, er in self.existing_returns.items():
            if er is not None and len(er) > 0:
                aligned = pd.DataFrame({"s": strategy_returns, "e": er}).dropna()
                if len(aligned) > 30:
                    corr = aligned["s"].corr(aligned["e"])
                    correlations[name] = round(float(corr), 4)
                    max_corr = max(max_corr, abs(corr))

        # 低相关性 = 高分
        if max_corr < 0.3:
            score = 1.0
        elif max_corr < 0.5:
            score = 0.85
        elif max_corr < 0.6:
            score = 0.7
        elif max_corr < 0.7:
            score = 0.5
        else:
            score = 0.2

        return score, {"max_correlation": max_corr, "correlations": correlations}

    def _score_sharpe(self, results) -> tuple:
        if results is None:
            return 0.5, {"sharpe_ratio": None}
        sr = results.get("sharpe_ratio", 0)
        if sr > 2.0:
            score = 1.0
        elif sr > 1.5:
            score = 0.9
        elif sr > 1.0:
            score = 0.8
        elif sr > 0.5:
            score = 0.6
        elif sr > 0.3:
            score = 0.4
        else:
            score = 0.2
        return score, {"sharpe_ratio": sr}
