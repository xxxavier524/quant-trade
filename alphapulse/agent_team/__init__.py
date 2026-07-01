"""AlphaPulse-A agent team — 多角色分工投研（P0 纯量化）。

来源设计：docs/research_journal/09_multiagent_research_2026-06-17.md §4
规格：docs/superpowers/specs/2026-06-21-agent-team-design.md

P0：DataAgent/FactorAgent/PatternAgent/SectorAgent + PortfolioAgent 规则聚合，
把已有确定性模块串成"单股多角色投研结论"，无 LLM、零新依赖。
阶段二再叠加 DeepSeek 多空辩论 + 贝叶斯融合。
"""

from alphapulse.agent_team.contract import StockOpinion, TeamVerdict
from alphapulse.agent_team.core import analyze_stock, analyze_batch
from alphapulse.agent_team.context import TeamContext, build_context

__all__ = ["StockOpinion", "TeamVerdict", "TeamContext",
           "build_context", "analyze_stock", "analyze_batch"]
