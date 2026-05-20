"""AlphaPulse-A 量化策略流水线 (6-Agent + 3-Gate)。

基于 "How to Build an AI Quant System" 框架：
6-Agent 流水线: Hypothesis -> Data -> Code -> Backtest -> Critique -> Risk -> Memory -> Next Hypothesis
3 验证闸门: Critic Agent, Deflated Sharpe Ratio, Risk Agent
Layer 2 验证: Walk-Forward, Combinatorial Purged CV, DSR

用法:
    python scripts/run_pipeline.py --config config/pipeline_config.json
    python scripts/run_pipeline.py --hypothesis "均值回归+放量确认" --data-dir data/day
"""

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

from alphapulse.pipeline.orchestrator import (
    PipelineOrchestrator,
    PipelineConfig,
    PipelineResult,
)

__all__ = [
    # Agents
    "AgentResult",
    "HypothesisAgent",
    "DataAgent",
    "CodeAgent",
    "BacktestAgent",
    "CritiqueAgent",
    "RiskAgent",
    "MemoryAgent",
    # Gates
    "GateResult",
    "CriticGate",
    "DSRGate",
    "RiskGate",
    # Validation
    "walk_forward_analysis",
    "combinatorial_purged_cv",
    "deflated_sharpe_ratio",
    "compute_degradation_ratio",
    # Memory
    "ExperimentRecord",
    "StrategyMemory",
    # Orchestrator
    "PipelineOrchestrator",
    "PipelineConfig",
    "PipelineResult",
]
