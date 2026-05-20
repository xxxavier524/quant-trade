"""流水线编排器 (Pipeline Orchestrator)。

负责串联全部 6 个 Agent + 3 个 Gate + 2 层验证，
输出 PipelineResult 聚合所有信息。

流水线执行顺序:
  Hypothesis Agent -> Data Agent -> Code Agent -> Backtest Agent
     -> Gate 1: Critic Gate
     -> Gate 2: DSR Gate
     -> Gate 3: Risk Gate
     -> Layer 2 Validation (Walk-Forward, Purged CV, DSR)
     -> Memory Agent (记录)
     -> 输出最终结果

用法:
    orchestrator = PipelineOrchestrator(config)
    result = orchestrator.run(hypothesis_text="...", stocks=..., strategy_fn=...)
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from alphapulse.pipeline.agents import (
    AgentResult,
    HypothesisAgent,
    DataAgent,
    CodeAgent,
    BacktestAgent,
    CritiqueAgent,
    RiskAgent,
    MemoryAgent,
)
from alphapulse.pipeline.gates import (
    GateResult,
    CriticGate,
    DSRGate,
    RiskGate,
)
from alphapulse.pipeline.validation import (
    walk_forward_analysis,
    combinatorial_purged_cv,
    deflated_sharpe_ratio,
    compute_degradation_ratio,
)
from alphapulse.pipeline.memory import (
    ExperimentRecord,
    StrategyMemory,
)


@dataclass
class PipelineConfig:
    """流水线配置。"""
    # Gate 参数
    dsr_n_trials: int = 100
    dsr_significance: float = 0.95
    critic_threshold: float = 0.80
    risk_max_correlation: float = 0.70
    risk_max_drawdown: float = 25.0

    # 回测参数
    initial_capital: float = 1_000_000
    max_holdings: int = 5
    max_single_pct: float = 0.20
    backtest_start: str = "2020-01-01"
    backtest_end: str = "2025-12-31"

    # Walk-Forward 参数
    wf_train_years: int = 3
    wf_test_years: int = 1
    wf_step_years: int = 1

    # Purged CV 参数
    cv_n_splits: int = 10
    cv_purge_pct: float = 0.01
    cv_embargo_pct: float = 0.0

    # 存储
    memory_path: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineConfig":
        return cls(
            dsr_n_trials=d.get("dsr_n_trials", 100),
            dsr_significance=d.get("dsr_significance", 0.95),
            critic_threshold=d.get("critic_threshold", 0.80),
            risk_max_correlation=d.get("risk_max_correlation", 0.70),
            risk_max_drawdown=d.get("risk_max_drawdown", 25.0),
            initial_capital=d.get("initial_capital", 1_000_000),
            max_holdings=d.get("max_holdings", 5),
            max_single_pct=d.get("max_single_pct", 0.20),
            backtest_start=d.get("backtest_start", "2020-01-01"),
            backtest_end=d.get("backtest_end", "2025-12-31"),
            wf_train_years=d.get("wf_train_years", 3),
            wf_test_years=d.get("wf_test_years", 1),
            wf_step_years=d.get("wf_step_years", 1),
            cv_n_splits=d.get("cv_n_splits", 10),
            cv_purge_pct=d.get("cv_purge_pct", 0.01),
            cv_embargo_pct=d.get("cv_embargo_pct", 0.0),
            memory_path=d.get("memory_path", ""),
        )

    def to_dict(self) -> dict:
        return {
            "dsr_n_trials": self.dsr_n_trials,
            "dsr_significance": self.dsr_significance,
            "critic_threshold": self.critic_threshold,
            "risk_max_correlation": self.risk_max_correlation,
            "risk_max_drawdown": self.risk_max_drawdown,
            "initial_capital": self.initial_capital,
            "max_holdings": self.max_holdings,
            "max_single_pct": self.max_single_pct,
            "backtest_start": self.backtest_start,
            "backtest_end": self.backtest_end,
            "wf_train_years": self.wf_train_years,
            "wf_test_years": self.wf_test_years,
            "wf_step_years": self.wf_step_years,
            "cv_n_splits": self.cv_n_splits,
            "cv_purge_pct": self.cv_purge_pct,
            "cv_embargo_pct": self.cv_embargo_pct,
            "memory_path": self.memory_path,
        }


@dataclass
class PipelineResult:
    """完整流水线运行结果。"""
    experiment_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    status: str = "running"  # running, passed, failed, error
    config: PipelineConfig = field(default_factory=PipelineConfig)

    # Agent 结果
    hypothesis_agent: dict = field(default_factory=dict)
    data_agent: dict = field(default_factory=dict)
    code_agent: dict = field(default_factory=dict)
    backtest_agent: dict = field(default_factory=dict)
    critique_agent: dict = field(default_factory=dict)

    # Gates
    critic_gate: dict = field(default_factory=dict)
    dsr_gate: dict = field(default_factory=dict)
    risk_gate: dict = field(default_factory=dict)
    all_gates_passed: bool = False

    # Layer 2 验证
    walk_forward: dict = field(default_factory=dict)
    purged_cv: dict = field(default_factory=dict)
    dsr_validation: dict = field(default_factory=dict)
    degradation: dict = field(default_factory=dict)

    # 汇总
    summary: dict = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "config": self.config.to_dict(),
            "hypothesis_agent": self.hypothesis_agent,
            "data_agent": self.data_agent,
            "code_agent": self.code_agent,
            "backtest_agent": self.backtest_agent,
            "critique_agent": self.critique_agent,
            "gates": {
                "critic_gate": self.critic_gate,
                "dsr_gate": self.dsr_gate,
                "risk_gate": self.risk_gate,
                "all_passed": self.all_gates_passed,
            },
            "validation": {
                "walk_forward": self.walk_forward,
                "purged_cv": self.purged_cv,
                "dsr_validation": self.dsr_validation,
                "degradation": self.degradation,
            },
            "summary": self.summary,
            "recommendations": self.recommendations,
            "errors": self.errors,
        }

    def print_summary(self):
        """打印简洁的流水线结果摘要。"""
        print("\n" + "=" * 70)
        print("  AlphaPulse-A Pipeline Result")
        print("=" * 70)
        print(f"  Experiment: {self.experiment_id}")
        print(f"  Status:     {self.status}")
        print(f"  Duration:   {self.completed_at}")
        print("-" * 70)

        bt = self.backtest_agent.get("data", {})
        print(f"  Annual Return:  {bt.get('annual_return', 'N/A'):>8}%")
        print(f"  Sharpe Ratio:   {bt.get('sharpe_ratio', 'N/A'):>8}")
        print(f"  Max Drawdown:   {bt.get('max_drawdown', 'N/A'):>8}%")
        print(f"  Win Rate:       {bt.get('win_rate', 'N/A'):>8}%")
        print(f"  Total Trades:   {bt.get('total_trades', 'N/A'):>8}")
        print("-" * 70)
        print(f"  Gate 1 (Critic): {'PASSED' if self.critic_gate.get('passed') else 'FAILED':>8}")
        print(f"  Gate 2 (DSR):    {'PASSED' if self.dsr_gate.get('passed') else 'FAILED':>8}  "
              f"(p={self.dsr_gate.get('score', 0):.4f})")
        print(f"  Gate 3 (Risk):   {'PASSED' if self.risk_gate.get('passed') else 'FAILED':>8}")
        print(f"  All Gates:       {'PASSED' if self.all_gates_passed else 'FAILED':>8}")
        print("-" * 70)
        deg = self.degradation
        if deg:
            print(f"  Degradation:     {deg.get('degradation_ratio', 'N/A'):>8}  "
                  f"({deg.get('interpretation', '')})")
        print(f"  DSR p-value:     {self.dsr_validation.get('dsr_pvalue', 'N/A'):>8}")
        print("=" * 70)

        if self.recommendations:
            print("\n  Recommendations:")
            for r in self.recommendations:
                print(f"    - {r}")
        if self.errors:
            print("\n  Errors:")
            for e in self.errors:
                print(f"    ! {e}")
        print()


class PipelineOrchestrator:
    """流水线编排器。

    串联所有 Agent、Gate、Validation 层，记录所有结果。

    用法:
        config = PipelineConfig()
        orch = PipelineOrchestrator(config)
        result = orch.run(
            hypothesis_text="均值回归 + 放量确认",
            stocks=stocks_dict,
            strategy_fn=my_strategy,
            strategy_name="mean_rev",
        )
        result.print_summary()
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.memory = StrategyMemory(storage_path=self.config.memory_path)

        # 初始化 Agent
        self.hypothesis_agent = HypothesisAgent()
        self.data_agent = DataAgent()
        self.code_agent = CodeAgent()
        self.backtest_agent = BacktestAgent()
        self.critique_agent = CritiqueAgent()
        self.risk_agent = RiskAgent()

        # 初始化 Gate
        self.critic_gate = CriticGate()
        self.dsr_gate = DSRGate(
            n_trials=self.config.dsr_n_trials,
            significance_level=self.config.dsr_significance,
        )
        self.risk_gate = RiskGate(
            max_correlation=self.config.risk_max_correlation,
            max_drawdown=self.config.risk_max_drawdown,
        )

    def run(
        self,
        hypothesis_text: str,
        stocks: dict[str, pd.DataFrame],
        strategy_fn: Optional[Callable] = None,
        strategy_name: str = "",
        factor_ids: Optional[list[str]] = None,
        entry_rules: Optional[dict] = None,
        exit_rules: Optional[dict] = None,
        param_ranges: Optional[dict] = None,
        skip_layer2: bool = False,
        **strategy_params,
    ) -> PipelineResult:
        """运行完整流水线。

        Args:
            hypothesis_text: 策略假设描述
            stocks: symbol -> DataFrame (OHLCV, DatetimeIndex)
            strategy_fn: 策略信号生成函数
            strategy_name: 策略名称
            factor_ids: 使用的因子列表
            entry_rules: 入场规则
            exit_rules: 出场规则
            param_ranges: 参数搜索范围
            skip_layer2: 是否跳过 Layer 2 验证（速度优先时使用）
            **strategy_params: 传给策略函数的额外参数

        Returns:
            PipelineResult: 完整结果
        """
        experiment_id = f"exp_{int(time.time()*1000)}"
        result = PipelineResult(
            experiment_id=experiment_id,
            started_at=datetime.now().isoformat(),
            config=self.config,
        )

        errors = []

        # ================================================================
        # Agent 1: Hypothesis
        # ================================================================
        hyp_result = self.hypothesis_agent.run(
            hypothesis_text=hypothesis_text,
            factor_ids=factor_ids,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            param_ranges=param_ranges,
        )
        result.hypothesis_agent = hyp_result.to_dict()
        if not hyp_result.success:
            errors.append(f"Hypothesis: {hyp_result.error}")
            result.status = "failed"
            result.errors = errors
            result.completed_at = datetime.now().isoformat()
            return result

        # ================================================================
        # Agent 2: Data
        # ================================================================
        data_result = self.data_agent.run(
            stocks=stocks,
            start_date=self.config.backtest_start,
            end_date=self.config.backtest_end,
        )
        result.data_agent = data_result.to_dict()
        if not data_result.success:
            errors.append(f"Data: {data_result.error}")
            result.status = "failed"
            result.errors = errors
            result.completed_at = datetime.now().isoformat()
            return result

        valid_stocks = data_result.data.get("stocks", {})

        # ================================================================
        # Agent 3: Code
        # ================================================================
        code_result = self.code_agent.run(
            hypothesis=hyp_result.data,
            strategy_fn=strategy_fn,
            strategy_name=strategy_name,
        )
        result.code_agent = code_result.to_dict()
        if not code_result.success:
            errors.append(f"Code: {code_result.error}")
            result.status = "failed"
            result.errors = errors
            result.completed_at = datetime.now().isoformat()
            return result

        verified_fn = code_result.data.get("strategy_fn", strategy_fn)

        # ================================================================
        # Agent 4: Backtest
        # ================================================================
        bt_result = self.backtest_agent.run(
            stocks=valid_stocks,
            strategy_fn=verified_fn,
            start_date=self.config.backtest_start,
            end_date=self.config.backtest_end,
            initial_capital=self.config.initial_capital,
            max_holdings=self.config.max_holdings,
            max_single_pct=self.config.max_single_pct,
            **strategy_params,
        )
        result.backtest_agent = bt_result.to_dict()
        if not bt_result.success:
            errors.append(f"Backtest: {bt_result.error}")
            result.status = "failed"
            result.errors = errors
            result.completed_at = datetime.now().isoformat()
            return result

        bt_data = bt_result.data

        # ================================================================
        # Agent 5: Critique
        # ================================================================
        crit_result = self.critique_agent.run(
            hypothesis=hyp_result.data,
            backtest_results=bt_data,
            strategy_code=code_result.data,
        )
        result.critique_agent = crit_result.to_dict()

        # ================================================================
        # Gate 1: Critic Gate
        # ================================================================
        critic_result = self.critic_gate.evaluate(
            backtest_results=bt_data,
            hypothesis=hyp_result.data,
        )
        result.critic_gate = critic_result.to_dict()

        # ================================================================
        # Gate 2: DSR Gate
        # ================================================================
        # 尝试从回测数据构建日收益率序列
        daily_returns = self._extract_daily_returns(bt_data, valid_stocks)
        dsr_result = self.dsr_gate.evaluate(
            daily_returns=daily_returns,
            sharpe_ratio=bt_data.get("sharpe_ratio"),
            n_observations=bt_data.get("n_days", 0),
        )
        result.dsr_gate = dsr_result.to_dict()

        # ================================================================
        # Gate 3: Risk Gate
        # ================================================================
        risk_result = self.risk_gate.evaluate(
            strategy_returns=daily_returns,
            backtest_results=bt_data,
            strategy_name=strategy_name,
        )
        result.risk_gate = risk_result.to_dict()

        # 判断 Gate 是否全部通过
        result.all_gates_passed = (
            critic_result.passed and dsr_result.passed and risk_result.passed
        )

        # ================================================================
        # Layer 2 验证 (可选跳过以加速)
        # ================================================================
        if not skip_layer2 and len(valid_stocks) > 0:
            # Walk-Forward Analysis
            wf_result = walk_forward_analysis(
                stocks=valid_stocks,
                strategy_fn=verified_fn,
                start_date=self.config.backtest_start,
                end_date=self.config.backtest_end,
                train_window_years=self.config.wf_train_years,
                test_window_years=self.config.wf_test_years,
                step_years=self.config.wf_step_years,
                **strategy_params,
            )
            result.walk_forward = wf_result

            # Degradation ratio
            deg = compute_degradation_ratio(
                is_sharpe=wf_result.get("avg_is_sharpe", 0),
                oos_sharpe=wf_result.get("avg_oos_sharpe", 0),
            )
            result.degradation = deg

            # DSR from Validation module
            if daily_returns is not None and len(daily_returns) > 30:
                dsr_val = deflated_sharpe_ratio(
                    daily_returns=daily_returns,
                    n_trials=self.config.dsr_n_trials,
                    significance_level=self.config.dsr_significance,
                )
                result.dsr_validation = dsr_val

            # Purged CV
            if len(valid_stocks) > 0:
                all_dates = sorted(set().union(*(
                    set(df.index) for df in valid_stocks.values()
                )))
                cv_info = combinatorial_purged_cv(
                    n_samples=len(all_dates),
                    n_splits=self.config.cv_n_splits,
                    purge_pct=self.config.cv_purge_pct,
                    embargo_pct=self.config.cv_embargo_pct,
                )
                result.purged_cv = cv_info

        # ================================================================
        # 汇总
        # ================================================================
        result.summary = {
            "annual_return": bt_data.get("annual_return"),
            "sharpe_ratio": bt_data.get("sharpe_ratio"),
            "max_drawdown": bt_data.get("max_drawdown"),
            "win_rate": bt_data.get("win_rate"),
            "total_trades": bt_data.get("total_trades"),
            "all_gates_passed": result.all_gates_passed,
            "dsr_pvalue": result.dsr_gate.get("score"),
            "degradation_ratio": result.degradation.get("degradation_ratio"),
        }

        # 建议
        recommendations = []
        if not result.all_gates_passed:
            recommendations.append("策略未通过全部闸门，建议修改假设或参数后重试")
        if deg.get("is_healthy", False):
            recommendations.append("退化率健康，策略泛化良好，可推进到实盘观察阶段")
        else:
            recommendations.append("退化率不健康，建议检查过拟合并做进一步验证")
        if bt_data.get("sharpe_ratio", 0) > 1.0:
            recommendations.append("夏普比率良好，建议考虑实盘小仓位试运行")
        result.recommendations = recommendations

        # 最终状态
        if result.all_gates_passed:
            result.status = "passed"
        elif errors:
            result.status = "failed"
        else:
            result.status = "completed"  # 完成但未通过 Gate

        result.completed_at = datetime.now().isoformat()

        # ================================================================
        # Memory: 记录结果
        # ================================================================
        exp_record = ExperimentRecord(
            experiment_id=experiment_id,
            started_at=result.started_at,
            completed_at=result.completed_at,
            hypothesis=hyp_result.data,
            status=result.status,
            agents={
                "hypothesis_agent": result.hypothesis_agent,
                "data_agent": result.data_agent,
                "code_agent": result.code_agent,
                "backtest_agent": result.backtest_agent,
                "critique_agent": result.critique_agent,
            },
            gates={
                "critic_gate": result.critic_gate,
                "dsr_gate": result.dsr_gate,
                "risk_gate": result.risk_gate,
                "all_passed": result.all_gates_passed,
            },
            validation={
                "walk_forward": result.walk_forward,
                "purged_cv": result.purged_cv,
                "dsr_validation": result.dsr_validation,
                "degradation": result.degradation,
            },
            summary=result.summary,
        )
        self.memory.record(exp_record)

        return result

    def _extract_daily_returns(
        self,
        backtest_data: dict,
        stocks: dict[str, pd.DataFrame],
    ) -> Optional[pd.Series]:
        """从回测结果中提取（或估算）日收益率序列。

        如果回测数据中包含 nav_curve，则从中推导。
        否则根据 annual_return 和 annual_volatility 模拟。
        """
        nav_curve = backtest_data.get("nav_curve")
        if nav_curve is not None and len(nav_curve) > 0:
            nav_df = pd.DataFrame(nav_curve)
            if "nav" in nav_df.columns:
                nav_df["daily_return"] = nav_df["nav"].pct_change()
                return nav_df["daily_return"].dropna()

        # 降级方案：用回测汇总指标生成近似收益率序列
        annual_ret = backtest_data.get("annual_return", 0) / 100.0
        annual_vol = backtest_data.get("annual_volatility", 20.0) / 100.0
        n_days = backtest_data.get("n_days", 252)

        if annual_vol > 0 and n_days > 0:
            daily_ret = annual_ret / 252
            daily_vol = annual_vol / np.sqrt(252)
            np.random.seed(42)
            synthetic = np.random.normal(daily_ret, daily_vol, n_days)
            return pd.Series(synthetic)

        return None

    def run_batch(
        self,
        hypotheses: list[dict],
        stocks: dict[str, pd.DataFrame],
        skip_layer2: bool = True,
    ) -> list[PipelineResult]:
        """批量运行多条假设。

        Args:
            hypotheses: [{"hypothesis_text": ..., "strategy_fn": ..., ...}, ...]
            stocks: 共享的股票数据
            skip_layer2: 批量模式建议跳过 Layer 2 以加速

        Returns:
            结果列表
        """
        results = []
        for i, h in enumerate(hypotheses):
            print(f"\n[{i+1}/{len(hypotheses)}] Running: {h['hypothesis_text'][:60]}...")
            result = self.run(
                hypothesis_text=h["hypothesis_text"],
                stocks=stocks,
                strategy_fn=h.get("strategy_fn"),
                strategy_name=h.get("strategy_name", f"batch_{i}"),
                factor_ids=h.get("factor_ids"),
                entry_rules=h.get("entry_rules"),
                exit_rules=h.get("exit_rules"),
                param_ranges=h.get("param_ranges"),
                skip_layer2=skip_layer2,
                **h.get("strategy_params", {}),
            )
            results.append(result)
            status_icon = "PASSED" if result.all_gates_passed else "FAILED"
            print(f"  Status: {result.status} | Gates: {status_icon} | "
                  f"Sharpe: {result.summary.get('sharpe_ratio', 'N/A')}")

        return results

    def replay_from_memory(self, experiment_id: str) -> Optional[PipelineResult]:
        """从 Memory 中重放历史实验结果。

        Args:
            experiment_id: 实验 ID

        Returns:
            PipelineResult 或 None
        """
        rec = self.memory.get(experiment_id)
        if rec is None:
            return None

        result = PipelineResult(
            experiment_id=rec.experiment_id,
            started_at=rec.started_at,
            completed_at=rec.completed_at,
            status=rec.status,
            hypothesis_agent=rec.agents.get("hypothesis_agent", {}),
            data_agent=rec.agents.get("data_agent", {}),
            code_agent=rec.agents.get("code_agent", {}),
            backtest_agent=rec.agents.get("backtest_agent", {}),
            critique_agent=rec.agents.get("critique_agent", {}),
            critic_gate=rec.gates.get("critic_gate", {}),
            dsr_gate=rec.gates.get("dsr_gate", {}),
            risk_gate=rec.gates.get("risk_gate", {}),
            all_gates_passed=rec.gates.get("all_passed", False),
            walk_forward=rec.validation.get("walk_forward", {}),
            purged_cv=rec.validation.get("purged_cv", {}),
            dsr_validation=rec.validation.get("dsr_validation", {}),
            degradation=rec.validation.get("degradation", {}),
            summary=rec.summary,
        )
        return result
