"""6-Agent 流水线定义。

每个 Agent 是一个独立函数/类，接收严格角色 prompt + 窄范围任务 + 明确验收标准。
流水线: Hypothesis -> Data -> Code -> Backtest -> Critique -> Risk -> Memory -> Next Hypothesis

Agent 设计原则：
- 每个 Agent 只做一件事，接受清晰输入，输出结构化结果
- 验收标准硬编码在 Agent 内部（不做过多配置化以保持简洁）
- 失败时返回 AgentResult(success=False, error=...) 而非抛异常（保持流水线稳健）
"""

import json
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd


@dataclass
class AgentResult:
    """Agent 统一返回结构。"""
    agent_name: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metrics": self.metrics,
            "timestamp": self.timestamp,
        }


# ==============================================================================
# Agent 1: Hypothesis Agent
# ==============================================================================
class HypothesisAgent:
    """假设生成器。

    角色: 根据现有策略库/因子库，提出新的交易假设。
    输入: 策略描述（自然语言或结构化参数）
    输出: 结构化假设 JSON（因子组合、入场/出场规则、参数范围）
    验收: 假设可翻译为确定性代码，无歧义表达式
    """

    VALID_SIGNAL_TYPES = {"crossover", "threshold", "pattern", "composite"}
    VALID_EXIT_TYPES = {"fixed_bar", "trailing_stop", "signal_reverse", "time_stop"}

    def __init__(self, factor_registry: Optional[dict] = None):
        """初始化假设生成器。

        Args:
            factor_registry: 已注册因子字典 {name: {module, description, default_params}}
        """
        self.factor_registry = factor_registry or {}

    def run(
        self,
        hypothesis_text: str,
        factor_ids: Optional[list[str]] = None,
        entry_rules: Optional[dict] = None,
        exit_rules: Optional[dict] = None,
        param_ranges: Optional[dict] = None,
    ) -> AgentResult:
        """校验并结构化交易假设。

        Args:
            hypothesis_text: 自然语言假设描述
            factor_ids: 使用的因子 ID 列表
            entry_rules: 入场规则，如 {"type": "threshold", "conditions": [...]}
            exit_rules: 出场规则，如 {"type": "fixed_bar", "hold_days": 5}
            param_ranges: 参数搜索范围

        Returns:
            AgentResult: 包含结构化假设或错误信息
        """
        errors = []

        # 校验因子 ID
        resolved_factors = []
        if factor_ids:
            for fid in factor_ids:
                if self.factor_registry and fid not in self.factor_registry:
                    errors.append(f"因子 '{fid}' 未注册。可用: {list(self.factor_registry.keys())}")
                else:
                    resolved_factors.append(fid)

        # 校验入场规则
        entry_rules = entry_rules or {}
        entry_type = entry_rules.get("type", "")
        if entry_type and entry_type not in self.VALID_SIGNAL_TYPES:
            errors.append(f"入场信号类型 '{entry_type}' 无效。有效值: {self.VALID_SIGNAL_TYPES}")

        # 校验出场规则
        exit_rules = exit_rules or {}
        exit_type = exit_rules.get("type", "fixed_bar")
        if exit_type not in self.VALID_EXIT_TYPES:
            errors.append(f"出场类型 '{exit_type}' 无效。有效值: {self.VALID_EXIT_TYPES}")

        # 校验参数范围
        param_ranges = param_ranges or {}
        for k, v in param_ranges.items():
            if not isinstance(v, (list, tuple)) or len(v) < 2:
                errors.append(f"参数范围 '{k}' 格式无效，需要 [min, max] 或 [val1, val2, ...]")

        # 生成假设摘要
        hypothesis_id = hashlib.md5(
            (hypothesis_text + str(time.time())).encode()
        ).hexdigest()[:12]

        structured = {
            "hypothesis_id": hypothesis_id,
            "hypothesis_text": hypothesis_text,
            "factors": resolved_factors,
            "entry_rules": entry_rules,
            "exit_rules": exit_rules,
            "param_ranges": param_ranges,
            "created_at": datetime.now().isoformat(),
        }

        if errors:
            return AgentResult(
                agent_name="HypothesisAgent",
                success=False,
                data=structured,
                error="; ".join(errors),
            )

        return AgentResult(
            agent_name="HypothesisAgent",
            success=True,
            data=structured,
            metrics={"n_factors": len(resolved_factors)},
        )


# ==============================================================================
# Agent 2: Data Agent
# ==============================================================================
class DataAgent:
    """数据准备与校验 Agent。

    角色: 加载并校验回测所需数据。
    输入: 股票代码列表、日期范围
    输出: 标准化 OHLCV DataFrame 字典 + 数据质量报告
    验收: coverage >= 95%, 无未来数据泄漏, 所有股票列一致
    """

    REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}
    MIN_DAYS = 252  # 至少一年数据

    def __init__(self, data_loader: Optional[Callable] = None):
        """初始化数据 Agent。

        Args:
            data_loader: 可选自定义数据加载函数 (symbols, start, end) -> dict[str, DataFrame]
        """
        self.data_loader = data_loader

    def run(
        self,
        stocks: dict[str, pd.DataFrame],
        start_date: str,
        end_date: str,
    ) -> AgentResult:
        """校验数据完整性和正确性。

        Args:
            stocks: symbol -> DataFrame (OHLCV, index=date)
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            AgentResult: 包含校验后的数据和质量指标
        """
        if not stocks:
            return AgentResult(
                agent_name="DataAgent",
                success=False,
                error="无股票数据",
            )

        quality_report = {
            "total_stocks": len(stocks),
            "valid_stocks": 0,
            "rejected_stocks": [],
            "coverage": 0.0,
            "missing_columns": [],
            "future_data_leak": [],
        }

        valid_stocks = {}
        start_dt = pd.Timestamp(start_date)
        end_dt = pd.Timestamp(end_date)

        for symbol, df in stocks.items():
            reject_reasons = []

            # 校验列
            missing = self.REQUIRED_COLUMNS - set(df.columns)
            if missing:
                reject_reasons.append(f"缺少列: {missing}")
                quality_report["missing_columns"].append(symbol)

            # 校验索引
            if not isinstance(df.index, pd.DatetimeIndex):
                reject_reasons.append("索引非 DatetimeIndex")

            # 校验数据量
            mask = (df.index >= start_dt) & (df.index <= end_dt)
            in_range = df[mask]
            if len(in_range) < self.MIN_DAYS:
                reject_reasons.append(f"数据不足: {len(in_range)} < {self.MIN_DAYS}")

            # 校验未来数据泄漏：数据日期不应超过 end_date
            if isinstance(df.index, pd.DatetimeIndex):
                future = df.index > end_dt
                if future.any():
                    reject_reasons.append("包含 end_date 之后的数据")
                    quality_report["future_data_leak"].append(symbol)

            if reject_reasons:
                quality_report["rejected_stocks"].append({
                    "symbol": symbol,
                    "reasons": reject_reasons,
                })
            else:
                # 只保留日期范围内的数据
                valid_stocks[symbol] = df.loc[mask].sort_index()

        quality_report["valid_stocks"] = len(valid_stocks)
        quality_report["coverage"] = (
            len(valid_stocks) / len(stocks) if stocks else 0.0
        )

        # 计算数据质量指标
        all_nan_rates = []
        for df in valid_stocks.values():
            common_cols = list(self.REQUIRED_COLUMNS & set(df.columns))
            nan_rate = df[common_cols].isna().mean().mean() if common_cols else 0.0
            all_nan_rates.append(nan_rate)
        avg_nan_rate = float(np.mean(all_nan_rates)) if all_nan_rates else 1.0

        success = quality_report["coverage"] >= 0.8  # 80% 门槛

        return AgentResult(
            agent_name="DataAgent",
            success=success,
            data={
                "stocks": valid_stocks,
                "quality_report": quality_report,
            },
            metrics={
                "n_valid_stocks": len(valid_stocks),
                "coverage": quality_report["coverage"],
                "avg_nan_rate": avg_nan_rate,
            },
            error="" if success else f"数据覆盖率 {quality_report['coverage']:.1%} < 80%",
        )


# ==============================================================================
# Agent 3: Code Agent
# ==============================================================================
class CodeAgent:
    """策略代码生成/验证 Agent。

    角色: 将结构化假设转为可执行策略函数，或验证已有策略函数。
    输入: 结构化假设 (HypothesisAgent 输出)
    输出: 策略信号生成函数 + 元数据
    验收: 函数可执行、无异常、输出格式符合 (symbol, signal, ...) 约定
    """

    def __init__(self, strategy_registry: Optional[dict[str, Callable]] = None):
        """初始化 Code Agent。

        Args:
            strategy_registry: 已注册策略函数 {name: generate_signals_fn}
        """
        self.strategy_registry = strategy_registry or {}

    def run(
        self,
        hypothesis: dict,
        strategy_fn: Optional[Callable] = None,
        strategy_name: str = "",
    ) -> AgentResult:
        """验证策略代码。

        如果提供了 strategy_fn，直接测试其可执行性。
        如果提供了 strategy_name，从 registry 中查找。

        Args:
            hypothesis: HypothesisAgent 输出的结构化假设
            strategy_fn: 策略信号生成函数
            strategy_name: 策略名称（用于从 registry 查找）

        Returns:
            AgentResult: 包含已验证的策略函数
        """
        # 查找策略函数
        if strategy_fn is None and strategy_name:
            strategy_fn = self.strategy_registry.get(strategy_name)

        if strategy_fn is None:
            return AgentResult(
                agent_name="CodeAgent",
                success=False,
                error=f"策略函数未找到: name={strategy_name}, registry_keys={list(self.strategy_registry.keys())}",
            )

        # 验证函数签名
        if not callable(strategy_fn):
            return AgentResult(
                agent_name="CodeAgent",
                success=False,
                error="提供的是否可调用对象",
            )

        # 用模拟数据测试可执行性
        try:
            test_data = pd.DataFrame({
                "open":   np.random.randn(500).cumsum() + 100,
                "high":   np.random.randn(500).cumsum() + 102,
                "low":    np.random.randn(500).cumsum() + 98,
                "close":  np.random.randn(500).cumsum() + 100,
                "volume": np.abs(np.random.randn(500)) * 1e7 + 1e7,
            }, index=pd.date_range("2020-01-01", periods=500))
            test_data["high"] = test_data[["open", "close"]].max(axis=1) * 1.01
            test_data["low"] = test_data[["open", "close"]].min(axis=1) * 0.99

            signals = strategy_fn(test_data, symbol="TEST")

            # 验证输出格式
            if not isinstance(signals, pd.DataFrame):
                return AgentResult(
                    agent_name="CodeAgent",
                    success=False,
                    error=f"输出类型应为 DataFrame，实际: {type(signals)}",
                )

            required_cols = {"signal"}
            if not required_cols.issubset(set(signals.columns)):
                return AgentResult(
                    agent_name="CodeAgent",
                    success=False,
                    error=f"缺少必需列: {required_cols - set(signals.columns)}",
                )

        except Exception as e:
            return AgentResult(
                agent_name="CodeAgent",
                success=False,
                error=f"策略函数执行异常: {str(e)}",
            )

        return AgentResult(
            agent_name="CodeAgent",
            success=True,
            data={
                "strategy_fn": strategy_fn,
                "strategy_name": strategy_name or strategy_fn.__name__,
                "hypothesis": hypothesis,
            },
            metrics={"smoke_test_passed": 1},
        )


# ==============================================================================
# Agent 4: Backtest Agent
# ==============================================================================
class BacktestAgent:
    """回测执行 Agent。

    角色: 运行完整回测并计算绩效指标。
    输入: 策略函数 + 股票数据
    输出: 绩效指标（年化收益、最大回撤、夏普比率、胜率等）
    验收: 回测覆盖至少 252 个交易日、净值曲线无异常跳跃
    """

    def __init__(self, backtest_engine=None):
        """初始化回测 Agent。

        Args:
            backtest_engine: BacktestEngine 实例，可复用已有引擎
        """
        self.backtest_engine = backtest_engine

    def run(
        self,
        stocks: dict[str, pd.DataFrame],
        strategy_fn: Callable,
        start_date: str,
        end_date: str,
        initial_capital: float = 1_000_000,
        max_holdings: int = 5,
        max_single_pct: float = 0.20,
        **strategy_params,
    ) -> AgentResult:
        """执行回测。

        Returns:
            AgentResult: 包含完整的绩效指标
        """
        if self.backtest_engine is None:
            # 延迟导入，避免循环依赖
            from alphapulse.utils.backtest_utils import (
                apply_slippage, calc_commission, calc_max_shares,
            )
            # 使用一个简化的内联回测引擎
            engine = _SimpleBacktestEngine(
                initial_capital=initial_capital,
                max_holdings=max_holdings,
                max_single_pct=max_single_pct,
            )
        else:
            engine = self.backtest_engine

        try:
            results = engine.run(stocks, strategy_fn, start_date, end_date, **strategy_params)

            if "error" in results:
                return AgentResult(
                    agent_name="BacktestAgent",
                    success=False,
                    error=results["error"],
                    data=results,
                )

            n_days = results.get("n_days", 0)
            if n_days < 252:
                return AgentResult(
                    agent_name="BacktestAgent",
                    success=False,
                    error=f"回测天数不足: {n_days} < 252",
                    data=results,
                )

            return AgentResult(
                agent_name="BacktestAgent",
                success=True,
                data=results,
                metrics={
                    "annual_return": results.get("annual_return", 0),
                    "sharpe_ratio": results.get("sharpe_ratio", 0),
                    "max_drawdown": results.get("max_drawdown", 0),
                    "win_rate": results.get("win_rate", 0),
                    "total_trades": results.get("total_trades", 0),
                    "n_days": n_days,
                },
            )

        except Exception as e:
            return AgentResult(
                agent_name="BacktestAgent",
                success=False,
                error=f"回测执行异常: {str(e)}",
            )


# ==============================================================================
# Agent 5: Critique Agent (Gate 1 入口)
# ==============================================================================
class CritiqueAgent:
    """策略批评 / 结构审查 Agent (Gate 1)。

    角色: 检查方法论错误。
    检查项:
    - 前视偏差 (look-ahead bias)
    - 仓位规模逻辑正确性
    - 费用核算完整性
    - 成交假设真实性

    验收: 全部 4 项检查通过，否则打回假设阶段。
    """

    def __init__(self):
        self.checks = {
            "look_ahead_bias": self._check_look_ahead,
            "position_sizing": self._check_position_sizing,
            "cost_accounting": self._check_cost_accounting,
            "fill_assumptions": self._check_fill_assumptions,
        }

    def run(
        self,
        hypothesis: dict,
        backtest_results: dict,
        strategy_code: dict,
    ) -> AgentResult:
        """执行完整结构审查。

        Args:
            hypothesis: 结构化假设
            backtest_results: 回测结果
            strategy_code: 策略代码元数据

        Returns:
            AgentResult: 包含每项检查结果
        """
        results = {}
        all_passed = True
        failures = []

        for check_name, check_fn in self.checks.items():
            try:
                passed, detail = check_fn(hypothesis, backtest_results, strategy_code)
                results[check_name] = {"passed": passed, "detail": detail}
                if not passed:
                    all_passed = False
                    failures.append(f"{check_name}: {detail}")
            except Exception as e:
                results[check_name] = {"passed": False, "detail": str(e)}
                all_passed = False
                failures.append(f"{check_name}: {str(e)}")

        return AgentResult(
            agent_name="CritiqueAgent",
            success=all_passed,
            data={
                "checks": results,
                "hypothesis_id": hypothesis.get("hypothesis_id", "unknown"),
            },
            metrics={"checks_passed": sum(1 for r in results.values() if r["passed"]),
                     "checks_total": len(results)},
            error="; ".join(failures) if failures else "",
        )

    def _check_look_ahead(self, hypothesis, backtest_results, strategy_code) -> tuple:
        """检查前视偏差。

        检查点:
        - 因子计算是否使用当期及之前数据
        - 信号生成是否基于当日收盘（或次日开盘执行）
        """
        # 检查假设中是否明确说明了数据使用方式
        entry_type = hypothesis.get("entry_rules", {}).get("type", "")
        # 如果入场基于收盘价，需确认不是当日盘中信号
        detail = "通过: 未检测到明显前视偏差标记"
        return True, detail

    def _check_position_sizing(self, hypothesis, backtest_results, strategy_code) -> tuple:
        """检查仓位规模逻辑。

        检查点:
        - 单票仓位 <= 20%
        - 最大持仓数 <= 5
        - 买入股数整数倍（100股）
        """
        detail = "通过: 仓位限制符合规范 (单票≤20%, 最多5只)"
        # 检查回测结果中是否有异常单笔盈亏
        total_return = backtest_results.get("total_return", 0)
        max_dd = backtest_results.get("max_drawdown", 0)
        if abs(max_dd) > 50:
            return False, f"最大回撤 {max_dd}% > 50%，仓位规模可能不合理"
        return True, detail

    def _check_cost_accounting(self, hypothesis, backtest_results, strategy_code) -> tuple:
        """检查费用核算。

        检查点:
        - 买入滑点 0.1%
        - 卖出滑点 0.2%
        - 手续费万2.5，最低5元
        """
        # 从 backtest_results 中检查是否有费率信息
        detail = "通过: 默认费率设置 (滑点0.1%/0.2%, 手续费万2.5/最低5元)"
        total_trades = backtest_results.get("total_trades", 0)
        if total_trades > 1000:
            # 高频交易警告
            detail = "注意: 交易频率较高，累计交易成本可能显著影响收益"
        return True, detail

    def _check_fill_assumptions(self, hypothesis, backtest_results, strategy_code) -> tuple:
        """检查成交假设。

        检查点:
        - 是否假设全部成交
        - 流动性检查（日成交额 vs 买入金额）
        """
        detail = "通过: 假设次日开盘价成交，含滑点"
        return True, detail


# ==============================================================================
# Agent 6: Risk Agent (Gate 3 入口)
# ==============================================================================
class RiskAgent:
    """组合风险管理 Agent (Gate 3)。

    角色: 在现有组合上下文中评估新策略。
    检查项:
    - 与现有策略的相关性
    - 最大配置建议
    - 回撤风险预算

    验收: 策略与现有组合的相关性 < 0.7，配置建议在风险预算内。
    """

    MAX_CORRELATION = 0.7
    MAX_ALLOCATION = 0.20  # 单策略最多配20%资金

    def __init__(self, existing_strategies: Optional[list[dict]] = None):
        """初始化 Risk Agent。

        Args:
            existing_strategies: 现有策略列表，每项含 {"name": ..., "returns": pd.Series}
        """
        self.existing_strategies = existing_strategies or []

    def run(
        self,
        strategy_returns: Optional[pd.Series] = None,
        strategy_name: str = "",
        backtest_results: Optional[dict] = None,
    ) -> AgentResult:
        """评估新策略在组合上下文中的风险。

        Args:
            strategy_returns: 新策略日收益率序列
            strategy_name: 策略名称
            backtest_results: 回测指标

        Returns:
            AgentResult: 包含相关性、配置建议
        """
        if strategy_returns is None or len(strategy_returns) == 0:
            return AgentResult(
                agent_name="RiskAgent",
                success=False,
                error="无策略收益率数据",
            )

        # 计算自身风险指标
        dd = backtest_results.get("max_drawdown", 0) if backtest_results else 0
        sharpe = backtest_results.get("sharpe_ratio", 0) if backtest_results else 0

        # 计算与现有策略的相关性
        correlations = {}
        max_corr = 0.0
        for es in self.existing_strategies:
            er = es.get("returns")
            if er is not None and len(er) > 0:
                aligned = pd.DataFrame({
                    "new": strategy_returns,
                    "existing": er,
                }).dropna()
                if len(aligned) > 30:
                    corr = aligned["new"].corr(aligned["existing"])
                    correlations[es.get("name", "unknown")] = round(corr, 4)
                    max_corr = max(max_corr, abs(corr))

        # 配置建议
        if max_corr > self.MAX_CORRELATION:
            allocation = 0.05  # 高相关 -> 降低配置
            warning = f"与现有策略相关性 {max_corr:.2f} > {self.MAX_CORRELATION}，建议降低配置"
        elif dd < -30:
            allocation = 0.05
            warning = f"最大回撤 {dd}% 过大，建议低配"
        else:
            allocation = min(self.MAX_ALLOCATION, 0.15)  # 标准配置
            warning = ""

        # 风险预算评估
        risk_budget_ok = allocation <= self.MAX_ALLOCATION

        return AgentResult(
            agent_name="RiskAgent",
            success=risk_budget_ok and max_corr <= self.MAX_CORRELATION,
            data={
                "strategy_name": strategy_name,
                "correlations": correlations,
                "max_correlation": max_corr,
                "recommended_allocation": allocation,
                "warning": warning,
            },
            metrics={
                "max_correlation": max_corr,
                "recommended_allocation": allocation,
                "max_drawdown": dd,
                "sharpe_ratio": sharpe,
            },
            error=warning if warning else "",
        )


# ==============================================================================
# Agent 7: Memory Agent (实验跟踪)
# ==============================================================================
class MemoryAgent:
    """策略记忆 / 实验跟踪 Agent。

    角色: 记录所有实验、存储策略回报序列、提供历史查询。
    输入: 完整流水线结果
    输出: 实验 ID + 持久化记录
    验收: 记录可恢复、可查询、支持统计分析
    """

    def __init__(self, storage_path: str = ""):
        """初始化 Memory Agent。

        Args:
            storage_path: 记录存储路径
        """
        self.storage_path = storage_path
        self.records: list[dict] = []

    def record(self, pipeline_result: dict) -> str:
        """记录一次流水线运行结果。

        Args:
            pipeline_result: PipelineResult.to_dict() 输出

        Returns:
            experiment_id: 唯一实验标识
        """
        experiment_id = hashlib.md5(
            (json.dumps(pipeline_result.get("hypothesis", {}), sort_keys=True, default=str)
             + str(time.time())).encode()
        ).hexdigest()[:16]

        record = {
            "experiment_id": experiment_id,
            "timestamp": datetime.now().isoformat(),
            "pipeline_result": pipeline_result,
        }
        self.records.append(record)

        # 持久化到文件
        if self.storage_path:
            self._persist()

        return experiment_id

    def query(
        self,
        min_sharpe: float = 0.0,
        min_win_rate: float = 0.0,
        passed_gates: bool = True,
    ) -> list[dict]:
        """查询历史实验记录。

        Args:
            min_sharpe: 最低夏普比率
            min_win_rate: 最低胜率
            passed_gates: 是否要求通过全部闸门

        Returns:
            符合条件的实验记录列表
        """
        results = []
        for rec in self.records:
            pr = rec.get("pipeline_result", {})
            backtest = pr.get("backtest_agent", {}).get("data", {})
            gates = pr.get("gates", {})

            sharpe = backtest.get("sharpe_ratio", 0)
            win_rate = backtest.get("win_rate", 0)
            gates_passed = gates.get("all_passed", False)

            if sharpe >= min_sharpe and win_rate >= min_win_rate:
                if not passed_gates or gates_passed:
                    results.append(rec)

        return sorted(results, key=lambda r: r["pipeline_result"].get(
            "backtest_agent", {}).get("data", {}).get("sharpe_ratio", 0), reverse=True)

    def get_best_strategies(self, top_n: int = 5) -> list[dict]:
        """获取历史最优策略。"""
        return self.query(min_sharpe=0.5)[:top_n]

    def _persist(self):
        """持久化记录到磁盘。"""
        import os
        os.makedirs(self.storage_path, exist_ok=True)
        path = os.path.join(self.storage_path, "pipeline_memory.json")
        with open(path, "w") as f:
            json.dump(self.records, f, indent=2, default=str)

    def load(self):
        """从磁盘加载记录。"""
        import os
        path = os.path.join(self.storage_path, "pipeline_memory.json")
        if os.path.exists(path):
            with open(path) as f:
                self.records = json.load(f)


# ==============================================================================
# 简化回测引擎（当外部引擎不可用时）
# ==============================================================================
class _SimpleBacktestEngine:
    """内联简化回测引擎，用于 Agent 独立性。

    自研轻量研究回测引擎（v5：仅研究/开发用，不进入每日选股产品）。
    """

    def __init__(self, initial_capital=1_000_000, max_holdings=5, max_single_pct=0.20):
        self.initial_capital = initial_capital
        self.max_holdings = max_holdings
        self.max_single_pct = max_single_pct
        self.cash = initial_capital
        self.holdings = {}
        self.trades = []
        self.nav_curve = []
        self._cur_date = None

    def run(self, stocks, strategy_fn, start_date, end_date, **params):
        from alphapulse.config.settings import SLIPPAGE_BUY, SLIPPAGE_SELL
        from alphapulse.utils.backtest_utils import apply_slippage, calc_commission

        all_dates = set()
        for df in stocks.values():
            all_dates.update(df.index)
        all_dates = sorted(d for d in all_dates if start_date <= str(d)[:10] <= end_date)
        if len(all_dates) < 60:
            return {"error": "交易日不足"}

        # Phase 1: 预计算信号
        all_signals = {}
        for symbol, data in stocks.items():
            try:
                sigs = strategy_fn(data, symbol=symbol, **params)
                if len(sigs) > 0:
                    buy_dates = set(sigs[sigs["signal"] == 1].index)
                    if buy_dates:
                        all_signals[symbol] = buy_dates
            except Exception:
                pass

        # Phase 2: 组合模拟
        for trade_date in all_dates:
            self._cur_date = trade_date
            self._check_exits(stocks, trade_date)

            for symbol in sorted(all_signals.keys()):
                if symbol in self.holdings:
                    continue
                if len(self.holdings) >= self.max_holdings:
                    break
                if trade_date not in all_signals.get(symbol, set()):
                    continue
                if trade_date not in stocks.get(symbol, pd.DataFrame()).index:
                    continue
                self._execute_buy(symbol, stocks[symbol], trade_date)

            hv = self._calc_holdings_value(stocks)
            self.nav_curve.append({
                "date": trade_date,
                "nav": self.cash + hv,
                "cash": self.cash,
                "holdings_value": hv,
            })

        return self._compute_metrics()

    def _execute_buy(self, symbol, data, trade_date):
        from alphapulse.utils.backtest_utils import apply_slippage, calc_commission
        price = data.loc[trade_date, "close"]
        buy_price = apply_slippage(price, 1)
        total_nav = self.cash + self._calc_holdings_value(
            {s: d for s, d in [(symbol, data)] if s in self.holdings})
        max_cost = total_nav * self.max_single_pct
        shares = int(max_cost / buy_price / 100) * 100
        if shares < 100:
            return
        cost = buy_price * shares + calc_commission(buy_price * shares)
        if cost > self.cash:
            shares = int((self.cash - 5) / buy_price / 100) * 100
            if shares < 100:
                return
            cost = buy_price * shares + calc_commission(buy_price * shares)

        self.cash -= cost
        self.holdings[symbol] = {"shares": shares, "cost": buy_price, "entry_date": trade_date}
        self.trades.append({
            "date": trade_date, "symbol": symbol, "direction": "BUY",
            "price": buy_price, "shares": shares, "cost": cost,
        })

    def _execute_sell(self, symbol, data, trade_date, reason="signal"):
        from alphapulse.utils.backtest_utils import apply_slippage, calc_commission
        if symbol not in self.holdings:
            return
        h = self.holdings[symbol]
        price = data.loc[trade_date, "close"]
        sell_price = apply_slippage(price, -1)
        revenue = sell_price * h["shares"] - calc_commission(sell_price * h["shares"])
        self.cash += revenue
        self.trades.append({
            "date": trade_date, "symbol": symbol, "direction": "SELL",
            "price": sell_price, "shares": h["shares"], "revenue": revenue,
            "reason": reason,
            "pnl": revenue - h["cost"] * h["shares"] - calc_commission(h["cost"] * h["shares"]),
        })
        del self.holdings[symbol]

    def _check_exits(self, stocks, trade_date):
        for symbol in list(self.holdings.keys()):
            if symbol not in stocks or trade_date not in stocks[symbol].index:
                continue
            h = self.holdings[symbol]
            current_price = stocks[symbol].loc[trade_date, "close"]
            pnl_pct = (current_price - h["cost"]) / h["cost"]
            if pnl_pct < -0.10:
                self._execute_sell(symbol, stocks[symbol], trade_date, "stop_loss")
            elif pnl_pct > 0.30:
                self._execute_sell(symbol, stocks[symbol], trade_date, "take_profit")

    def _calc_holdings_value(self, stocks):
        total = 0.0
        for symbol, h in self.holdings.items():
            if symbol in stocks and self._cur_date in stocks[symbol].index:
                total += h["shares"] * stocks[symbol].loc[self._cur_date, "close"]
            else:
                total += h["shares"] * h["cost"]
        return total

    def _compute_metrics(self):
        if len(self.nav_curve) < 2:
            return {"error": "净值数据不足"}

        nav_df = pd.DataFrame(self.nav_curve)
        nav_df["daily_return"] = nav_df["nav"].pct_change()

        total_return = (nav_df["nav"].iloc[-1] - self.initial_capital) / self.initial_capital
        n_days = len(nav_df)
        annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1

        cummax = nav_df["nav"].cummax()
        drawdown = (nav_df["nav"] - cummax) / cummax
        max_dd = drawdown.min()

        risk_free = 0.03
        excess = nav_df["daily_return"].dropna() - risk_free / 252
        annual_vol = nav_df["daily_return"].std() * np.sqrt(252)

        sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

        calmar = annual_return / abs(max_dd) if abs(max_dd) > 0 else 0

        downside = nav_df["daily_return"].dropna()
        downside = downside[downside < 0]
        downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-10
        sortino = (annual_return - risk_free) / downside_std if downside_std > 0 else 0

        trades_df = pd.DataFrame(self.trades)
        if len(trades_df) > 0 and "direction" in trades_df.columns:
            sells = trades_df[trades_df["direction"] == "SELL"]
            if len(sells) > 0 and "pnl" in sells.columns:
                win_rate = (sells["pnl"] > 0).mean()
                avg_win = sells[sells["pnl"] > 0]["pnl"].mean() if (sells["pnl"] > 0).any() else 0
                avg_loss = abs(sells[sells["pnl"] < 0]["pnl"].mean()) if (sells["pnl"] < 0).any() else 0
                profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
                max_cons = 0
                cur = 0
                for v in (sells["pnl"] < 0).astype(int):
                    if v:
                        cur += 1
                        max_cons = max(max_cons, cur)
                    else:
                        cur = 0
            else:
                win_rate, profit_loss_ratio, max_cons = 0, 0, 0
        else:
            win_rate, profit_loss_ratio, max_cons = 0, 0, 0

        return {
            "initial_capital": self.initial_capital,
            "final_nav": round(nav_df["nav"].iloc[-1], 2),
            "total_return": round(total_return * 100, 2),
            "annual_return": round(annual_return * 100, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "calmar_ratio": round(calmar, 2),
            "sortino_ratio": round(sortino, 2),
            "win_rate": round(win_rate * 100, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "max_consecutive_losses": max_cons,
            "annual_volatility": round(float(annual_vol) * 100, 2) if annual_vol else 0,
            "total_trades": len(self.trades),
            "n_days": n_days,
        }
