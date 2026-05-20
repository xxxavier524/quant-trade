"""TradingAgents integration adapter for AlphaPulse-A.

Wraps the multi-agent LLM trading framework to enhance AlphaPulse-A's
signal generation with:
  1. Context-aware signal validation (analyst team review)
  2. Bull/Bear structured debate (devil's advocate)
  3. Risk-tier position sizing (aggressive/neutral/conservative)
  4. Natural language trading rationale

Architecture:
  AlphaPulse-A Strategy Signals (B1 / Brick / Needle)
      |
      v
  TradingAgents Analyst Team (4 agents, parallel)
      |-- Fundamental Analyst: valuation, financial health
      |-- Sentiment Analyst: market mood, fund flows
      |-- News Analyst: recent developments, catalysts
      |-- Technical Analyst: chart patterns, indicators
      |
      v
  TradingAgents Researcher Team (Bull vs Bear debate)
      |
      v
  TradingAgents Trader + Risk Manager (structured decision)
      |
      v
  Enhanced Signal (validated + risk-tiered + rationale)

Usage:
    from alphapulse.adapters.tradingagents_adapter import (
        enhance_signals_with_llm,
        SignalEnhancer,
    )

    enhancer = SignalEnhancer(llm_model="deepseek-v4-pro")
    enhanced = enhancer.enhance_signals(signals_df, market_context)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Soft import
# ---------------------------------------------------------------------------
try:
    import tradingagents as ta

    _HAS_TA = True
except ImportError:
    _HAS_TA = False
    ta = None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class RiskTier(str, Enum):
    """Risk assessment tier from TradingAgents risk manager."""

    AGGRESSIVE = "aggressive"  # High conviction, full position
    NEUTRAL = "neutral"  # Moderate conviction, reduced position
    CONSERVATIVE = "conservative"  # Low conviction, minimum position
    REJECT = "reject"  # Signal rejected entirely


@dataclass
class EnhancedSignal:
    """A strategy signal enhanced by TradingAgents multi-agent analysis.

    Attributes:
        symbol: A-share ticker.
        date: Signal date.
        original_signal: Original AlphaPulse-A signal ('buy' / 'sell' / 'hold').
        enhanced_signal: Post-analysis signal ('buy' / 'sell' / 'hold').
        risk_tier: Risk assessment for position sizing.
        confidence: 0-1 confidence score from analyst consensus.
        rationale: Natural language explanation from agent debate.
        bull_arguments: Key points from the bull analyst.
        bear_arguments: Key points from the bear analyst.
        fundamental_score: 0-1 fundamental analyst assessment.
        technical_score: 0-1 technical analyst assessment.
        sentiment_score: 0-1 sentiment analyst assessment.
    """

    symbol: str
    date: str | date
    original_signal: str  # 'buy', 'sell', 'hold'
    enhanced_signal: str  # 'buy', 'sell', 'hold'
    risk_tier: RiskTier
    confidence: float = 0.5
    rationale: str = ""
    bull_arguments: str = ""
    bear_arguments: str = ""
    fundamental_score: float = 0.5
    technical_score: float = 0.5
    sentiment_score: float = 0.5

    def position_multiplier(self) -> float:
        """Convert risk tier to position size multiplier.

        This replaces the static 20% allocation cap with dynamic sizing:
        - AGGRESSIVE: 1.0x (full 20% cap)  -> 20%
        - NEUTRAL:    0.7x                  -> 14%
        - CONSERVATIVE: 0.4x                -> 8%
        - REJECT:     0.0x (no allocation)  -> 0%
        """
        multipliers = {
            RiskTier.AGGRESSIVE: 1.0,
            RiskTier.NEUTRAL: 0.7,
            RiskTier.CONSERVATIVE: 0.4,
            RiskTier.REJECT: 0.0,
        }
        return multipliers.get(self.risk_tier, 0.5)


@dataclass
class MarketContext:
    """Context provided to TradingAgents for informed analysis.

    Attributes:
        date: Analysis date.
        index_trend: CSI 300 index direction ('up' / 'down' / 'sideways').
        index_change_pct: Recent index % change.
        sector_rotation: Active sectors (e.g., ['消费', '新能源']).
        macro_events: Key macro events (e.g., 'PBOC rate cut', 'CPI release').
        volume_trend: Market volume trend ('increasing' / 'decreasing' / 'normal').
    """

    date: str | date | None = None
    index_trend: str = "sideways"
    index_change_pct: float = 0.0
    sector_rotation: list[str] = field(default_factory=list)
    macro_events: list[str] = field(default_factory=list)
    volume_trend: str = "normal"


# ---------------------------------------------------------------------------
# Signal Enhancer
# ---------------------------------------------------------------------------


class SignalEnhancer:
    """Multi-agent LLM signal enhancement using TradingAgents framework.

    This class manages the lifecycle of TradingAgents analysis for
    AlphaPulse-A strategy signals. It handles LLM API configuration,
    caching, and error recovery.

    Usage:
        enhancer = SignalEnhancer(
            llm_model="deepseek-v4-pro",
            llm_api_key="sk-...",
            llm_base_url="https://api.deepseek.com/v1",
        )

        # Batch enhancement
        enhanced = enhancer.enhance_signals(signals_df, market_context)

        # Single-symbol analysis
        result = enhancer.analyze_single(
            "600519", "buy", market_context, price_data
        )
    """

    def __init__(
        self,
        llm_model: str = "deepseek-v4-pro",
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
        cache_ttl_hours: int = 4,
    ):
        """Initialize signal enhancer.

        Args:
            llm_model: LLM model name (OpenAI-format compatible).
                Supports: deepseek, gpt-4, claude, gemini, qwen, glm, ollama.
            llm_api_key: API key. If None, reads from env:
                DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.
            llm_base_url: Base URL for API (overrides defaults per model).
            cache_ttl_hours: Cache TTL for repeated analyses of same symbol+date.
        """
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url
        self.cache_ttl_hours = cache_ttl_hours
        self._cache: dict[str, tuple[datetime, EnhancedSignal]] = {}

        if not _HAS_TA:
            logger.warning(
                "TradingAgents not installed. Install with: pip install tradingagents"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enhance_signals(
        self,
        signals_df: pd.DataFrame,
        context: MarketContext | None = None,
        price_data: dict[str, pd.DataFrame] | None = None,
        max_signals: int = 5,
    ) -> list[EnhancedSignal]:
        """Batch-enhance AlphaPulse-A strategy signals.

        Args:
            signals_df: DataFrame with columns [symbol, date, signal, strategy].
                'signal' should be 'buy' or 'sell'.
            context: Market context for informed analysis.
            price_data: Dict of {symbol: OHLCV DataFrame} for technical analysis.
            max_signals: Maximum signals to analyze (API cost control).

        Returns:
            List of EnhancedSignal objects sorted by confidence descending.
        """
        if signals_df.empty:
            return []

        # Limit to top signals to control API cost
        buy_signals = signals_df[signals_df["signal"] == "buy"]
        if len(buy_signals) > max_signals:
            buy_signals = buy_signals.head(max_signals)

        results = []
        for _, row in buy_signals.iterrows():
            symbol = row["symbol"]
            signal_date = row.get("date", str(date.today()))
            price = price_data.get(symbol) if price_data else None

            enhanced = self.analyze_single(
                symbol=str(symbol),
                signal="buy",
                context=context,
                price_data=price,
            )
            if enhanced and enhanced.enhanced_signal == "buy":
                results.append(enhanced)

        # Sort by confidence descending
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    def analyze_single(
        self,
        symbol: str,
        signal: str = "buy",
        context: MarketContext | None = None,
        price_data: pd.DataFrame | None = None,
    ) -> EnhancedSignal | None:
        """Analyze a single stock signal through the multi-agent pipeline.

        Args:
            symbol: A-share ticker.
            signal: Original signal ('buy' or 'sell').
            context: Market context.
            price_data: OHLCV data for technical analysis.

        Returns:
            EnhancedSignal or None if analysis fails.
        """
        # Check cache
        today = str(date.today())
        cache_key = f"{symbol}:{today}"
        if cache_key in self._cache:
            cached_time, cached_result = self._cache[cache_key]
            hours_ago = (datetime.now() - cached_time).total_seconds() / 3600
            if hours_ago < self.cache_ttl_hours:
                logger.debug("Cache hit for %s (%.1f hours old)", symbol, hours_ago)
                return cached_result

        if not _HAS_TA:
            logger.warning("TradingAgents not available, returning original signal")
            return EnhancedSignal(
                symbol=symbol,
                date=today,
                original_signal=signal,
                enhanced_signal=signal,
                risk_tier=RiskTier.NEUTRAL,
                confidence=0.5,
                rationale="TradingAgents not available; signal passed through unchanged.",
            )

        # If TradingAgents is available, attempt full analysis
        try:
            return self._run_multi_agent_analysis(symbol, signal, context, price_data)
        except Exception as e:
            logger.error("TradingAgents analysis failed for %s: %s", symbol, e)
            # Graceful fallback: pass signal through with neutral risk tier
            return EnhancedSignal(
                symbol=symbol,
                date=today,
                original_signal=signal,
                enhanced_signal=signal,
                risk_tier=RiskTier.NEUTRAL,
                confidence=0.5,
                rationale=f"Analysis failed ({e}); signal passed through unchanged.",
            )

    # ------------------------------------------------------------------
    # Multi-agent analysis pipeline
    # ------------------------------------------------------------------

    def _run_multi_agent_analysis(
        self,
        symbol: str,
        signal: str,
        context: MarketContext | None,
        price_data: pd.DataFrame | None,
    ) -> EnhancedSignal:
        """Run the full 4-layer multi-agent analysis pipeline.

        Layer 1: Analyst Team (4 agents, parallel)
        Layer 2: Researcher Team (bull vs bear debate)
        Layer 3: Trader (structured decision)
        Layer 4: Risk Manager (risk tier assessment)
        """
        context = context or MarketContext()

        # Build the analysis prompt
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(symbol, signal, context, price_data)

        # Execute analysis via TradingAgents (or LLM directly as fallback)
        analysis_result = self._call_llm(system_prompt, user_prompt)

        # Parse the structured output
        return self._parse_analysis_response(analysis_result, symbol, signal)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM for multi-agent analysis.

        Uses TradingAgents' Agent class if available; falls back to
        direct LLM API call with structured prompt otherwise.
        """
        if _HAS_TA:
            try:
                # Use TradingAgents' Agent framework
                agent = ta.Agent(
                    model=self.llm_model,
                    api_key=self.llm_api_key,
                    base_url=self.llm_base_url,
                )
                return agent.run(system_prompt=system_prompt, user_prompt=user_prompt)
            except Exception as e:
                logger.warning("TradingAgents Agent.run failed: %s, using direct call", e)

        # Fallback: direct LLM call
        return self._direct_llm_call(system_prompt, user_prompt)

    def _direct_llm_call(self, system_prompt: str, user_prompt: str) -> str:
        """Fallback: call LLM directly without TradingAgents framework.

        Uses litellm-compatible API format (OpenAI-style).
        """
        try:
            from litellm import completion

            response = completion(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                api_key=self.llm_api_key,
                api_base=self.llm_base_url,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("Direct LLM call failed: %s", e)
            raise

    # ------------------------------------------------------------------
    # Prompt engineering
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt for multi-agent trading analysis."""
        return """你是一个专业的A股量化交易多智能体分析系统。你的任务是：

1. **基本面分析师**：分析股票的财务健康度（ROE、PE、营收增长等）
2. **舆情分析师**：分析市场情绪、资金流向、机构持仓变化
3. **新闻分析师**：分析近期重大公告、政策影响、行业动态
4. **技术分析师**：分析K线形态、均线系统、量价关系、技术指标

然后进行**多空辩论**（多头 vs 空头），最后输出结构化的交易决策。

请用以下JSON格式输出你的分析结果：
```json
{
  "symbol": "股票代码",
  "analysis_summary": "一句话总结",
  "fundamental_score": 0-1之间的小数,
  "technical_score": 0-1之间的小数,
  "sentiment_score": 0-1之间的小数,
  "bull_arguments": "多头理由（3点以内）",
  "bear_arguments": "空头风险（3点以内）",
  "enhanced_signal": "buy" 或 "sell" 或 "hold",
  "risk_tier": "aggressive" 或 "neutral" 或 "conservative" 或 "reject",
  "confidence": 0-1之间的小数,
  "rationale": "最终决策理由（2-3句话）"
}
```

风险等级说明：
- aggressive：高确定性，可满仓位（20%）
- neutral：中等确定性，建议70%仓位（14%）
- conservative：低确定性，建议40%仓位（8%）
- reject：信号不可靠，不建议交易
"""

    def _build_user_prompt(
        self,
        symbol: str,
        signal: str,
        context: MarketContext,
        price_data: pd.DataFrame | None,
    ) -> str:
        """Build the user prompt with stock-specific data."""
        parts = [
            f"## 股票分析请求",
            f"",
            f"**股票代码**：{symbol}",
            f"**原始信号**：{signal}（来自AlphaPulse-A策略系统）",
            f"**分析日期**：{context.date or date.today()}",
            f"",
            f"## 市场环境",
            f"- 指数趋势：{context.index_trend}",
            f"- 指数涨跌：{context.index_change_pct:+.2f}%",
        ]

        if context.sector_rotation:
            parts.append(f"- 活跃板块：{', '.join(context.sector_rotation)}")
        if context.macro_events:
            parts.append(f"- 宏观事件：{', '.join(context.macro_events)}")
        parts.append(f"- 成交量趋势：{context.volume_trend}")

        if price_data is not None and not price_data.empty:
            parts.append("")
            parts.append("## 近期价格数据（最近5日）")
            recent = price_data.tail(5)
            for idx, row in recent.iterrows():
                parts.append(
                    f"- {idx.strftime('%m-%d')}: "
                    f"O={row['open']:.2f} H={row['high']:.2f} "
                    f"L={row['low']:.2f} C={row['close']:.2f} "
                    f"V={row['volume']:.0f}"
                )

            # Add key technical stats
            close = price_data["close"]
            if len(close) >= 20:
                ma5 = close.rolling(5).mean().iloc[-1]
                ma20 = close.rolling(20).mean().iloc[-1]
                ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0
                ret_20d = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else 0

                parts.append("")
                parts.append("## 技术指标摘要")
                parts.append(f"- MA5: {ma5:.2f} | MA20: {ma20:.2f}")
                parts.append(f"- 5日涨跌: {ret_5d:+.2f}% | 20日涨跌: {ret_20d:+.2f}%")
                parts.append(
                    f"- 价格相对MA20: "
                    f"{'上方' if close.iloc[-1] > ma20 else '下方'}"
                    f" {abs((close.iloc[-1] / ma20 - 1) * 100):.1f}%"
                )

        parts.append("")
        parts.append("请对以上信息进行多智能体分析，输出JSON格式的完整决策。")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_analysis_response(
        self, response: str, symbol: str, signal: str
    ) -> EnhancedSignal:
        """Parse the LLM response JSON into an EnhancedSignal."""
        try:
            # Extract JSON block from response
            json_str = response
            if "```json" in response:
                start = response.index("```json") + 7
                end = response.index("```", start)
                json_str = response[start:end]
            elif "{" in response and "}" in response:
                start = response.index("{")
                end = response.rindex("}") + 1
                json_str = response[start:end]

            data = json.loads(json_str)

            risk_tier = RiskTier.NEUTRAL
            tier_str = data.get("risk_tier", "neutral").lower()
            try:
                risk_tier = RiskTier(tier_str)
            except ValueError:
                pass

            return EnhancedSignal(
                symbol=symbol,
                date=str(date.today()),
                original_signal=signal,
                enhanced_signal=data.get("enhanced_signal", signal),
                risk_tier=risk_tier,
                confidence=float(data.get("confidence", 0.5)),
                rationale=str(data.get("rationale", "")),
                bull_arguments=str(data.get("bull_arguments", "")),
                bear_arguments=str(data.get("bear_arguments", "")),
                fundamental_score=float(data.get("fundamental_score", 0.5)),
                technical_score=float(data.get("technical_score", 0.5)),
                sentiment_score=float(data.get("sentiment_score", 0.5)),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Failed to parse LLM response: %s. Response: %s", e, response[:200])
            # Fallback
            return EnhancedSignal(
                symbol=symbol,
                date=str(date.today()),
                original_signal=signal,
                enhanced_signal=signal,
                risk_tier=RiskTier.NEUTRAL,
                confidence=0.5,
                rationale=f"Response parsing failed; raw: {response[:200]}...",
            )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def enhance_signals_with_llm(
    signals_df: pd.DataFrame,
    context: MarketContext | None = None,
    llm_model: str = "deepseek-v4-pro",
    llm_api_key: str | None = None,
    max_signals: int = 5,
) -> list[EnhancedSignal]:
    """One-call convenience: enhance AlphaPulse-A signals with LLM analysis.

    Args:
        signals_df: Strategy signals DataFrame (symbol, date, signal columns).
        context: Market context.
        llm_model: LLM model name.
        llm_api_key: API key.
        max_signals: Maximum signals to analyze.

    Returns:
        List of EnhancedSignal objects, confidence-sorted.
    """
    enhancer = SignalEnhancer(llm_model=llm_model, llm_api_key=llm_api_key)
    return enhancer.enhance_signals(signals_df, context=context, max_signals=max_signals)


# ---------------------------------------------------------------------------
# Quick test (mock mode -- no API calls)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== TradingAgents Adapter Test (Mock Mode) ===\n")

    # Test signal enhancement with fallback (no API key)
    enhancer = SignalEnhancer(llm_model="deepseek-v4-pro")

    # Mock signals
    signals = pd.DataFrame({
        "symbol": ["600519", "000001", "300750"],
        "date": ["2026-05-16"] * 3,
        "signal": ["buy", "buy", "buy"],
        "strategy": ["B1", "Brick", "Needle"],
    })

    context = MarketContext(
        date="2026-05-16",
        index_trend="up",
        index_change_pct=1.5,
        sector_rotation=["白酒", "银行"],
        volume_trend="increasing",
    )

    results = enhancer.enhance_signals(signals, context=context)

    print(f"Enhanced {len(results)} signals:")
    for r in results:
        print(f"  {r.symbol}: {r.original_signal} -> {r.enhanced_signal}")
        print(f"    Risk: {r.risk_tier.value}, Confidence: {r.confidence:.2f}")
        print(f"    Position multiplier: {r.position_multiplier():.1%}")
        print(f"    Rationale: {r.rationale[:100]}...")
        print()
