"""人格角色（skill驱动，阶段二辩论庭扩展）。

config/personas/ 下每个 .md 文件 = 一个人格角色（如 金渐成）：
- 文件内容作为 system prompt（人格的方法论/口诀/纪律）
- 辩论时人格基于量化 evidence 独立出观点 {signal, confidence, reasoning}
- 人格观点注入 Referee 仲裁上下文，并作为 opinion 展示在报告/GUI

文件名（去扩展名）即角色名。无文件/无key时静默跳过，不影响主链路。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from alphapulse.agent_team.contract import StockOpinion, TeamVerdict
from alphapulse.agent_team.debate import parse_referee, _evidence_json

logger = logging.getLogger("agent_team.persona")

PERSONA_DIR = Path(__file__).resolve().parents[2] / "config" / "personas"

_PROMPT = """以下是 {symbol} {name} 的量化团队证据（JSON）：
{evidence}

请以你的方法论审视该股当前状态，输出严格 JSON（不要多余文字）：
{{"signal": "bullish|bearish|neutral", "confidence": 0到100的数字, "reasoning": "不超过80字，按你的体系给出关键依据"}}"""


def load_personas() -> list[tuple[str, str]]:
    """[(角色名, system_prompt)]。目录不存在返回空。"""
    if not PERSONA_DIR.exists():
        return []
    out = []
    for f in sorted(PERSONA_DIR.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8").strip()
            if text:
                out.append((f.stem, text))
        except Exception:
            continue
    return out


def persona_opinions(verdict: TeamVerdict, chat_fn=None) -> list[StockOpinion]:
    """全部人格对单股出观点（每人格1次调用）。失败的静默跳过。"""
    personas = load_personas()
    if not personas:
        return []
    if chat_fn is None:
        try:
            from alphapulse.llm.client import chat, is_configured, MODEL_REASONING
            if not is_configured():
                return []
        except Exception:
            return []

    ev = _evidence_json(verdict)
    out = []
    for pname, system in personas:
        prompt = _PROMPT.format(symbol=verdict.symbol, name=verdict.name, evidence=ev)
        try:
            if chat_fn is not None:
                raw = chat_fn(prompt, system)
            else:
                raw = chat(prompt, system=system, model=MODEL_REASONING,
                           temperature=0.4, max_tokens=400)
            r = parse_referee(raw)
            if r is None:
                logger.warning(f"{verdict.symbol} 人格[{pname}] JSON解析失败")
                continue
            out.append(StockOpinion(f"persona:{pname}", r["signal"],
                                    r["confidence"], {}, r["reasoning"]))
        except Exception as e:
            logger.warning(f"{verdict.symbol} 人格[{pname}] 调用失败: {e}")
    return out
