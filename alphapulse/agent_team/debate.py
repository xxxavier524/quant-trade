"""多空辩论角色（阶段二，DeepSeek v4-pro）。

流程（TradingAgents 蓝本，分层不重读原则——只喂 P0 结构化 evidence，不传原始K线）：
  Bull（做多研究员）→ Bear（专职唱反调）→ Referee（研究经理仲裁，输出 JSON 三元组）

任何一步失败（未配 key / 网络 / JSON 不合法）返回 None → 调用方保持 P0 结论，永不阻塞。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from alphapulse.agent_team.contract import TeamVerdict

logger = logging.getLogger("agent_team.debate")

_SYSTEM = ("你是A股短线量化投研团队的研究员。团队风格：底部挖掘（B1超跌回调买点体系），"
           "严守知行多空线纪律。基于给定的量化证据发言，不编造证据之外的数据。")

_BULL_TMPL = """以下是 {symbol} {name} 的量化团队证据（JSON）：
{evidence}

你是做多研究员。基于以上证据，用不超过150字陈述做多论点：买点性质、最强的2-3条依据、预期路径。"""

_BEAR_TMPL = """以下是 {symbol} {name} 的量化团队证据（JSON）：
{evidence}

做多研究员的观点：
{bull}

你是专职唱反调的做空研究员。用不超过150字反驳：指出证据中的矛盾/薄弱环节（如板块弱、GBDT胜率低、
量能不足、大盘档位风险），以及该买点最可能的失败路径。"""

_REFEREE_TMPL = """{symbol} {name} 的量化证据（JSON）：
{evidence}

多方观点：{bull}

空方观点：{bear}
{extra}
你是研究经理，仲裁多空辩论。综合量化证据与双方论点，输出严格 JSON（不要多余文字）：
{{"signal": "bullish|bearish|neutral", "confidence": 0到100的数字, "reasoning": "不超过80字的裁决理由"}}"""


@dataclass
class DebateOutcome:
    bull: str
    bear: str
    signal: str            # 仲裁方向
    confidence: float      # 仲裁置信度 0-100
    reasoning: str         # 仲裁理由


def _evidence_json(verdict: TeamVerdict) -> str:
    ev = {op.agent: {"signal": op.signal, "confidence": op.confidence,
                     **{k: v for k, v in op.evidence.items() if k != "weights"}}
          for op in verdict.opinions}
    ev["team_score_p0"] = verdict.score
    return json.dumps(ev, ensure_ascii=False, default=str)


def parse_referee(text: str) -> dict | None:
    """从仲裁回复提取 JSON（容忍代码块/前后缀文本），校验字段。失败返回 None。"""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    sig = str(d.get("signal", "")).lower().strip()
    if sig not in ("bullish", "bearish", "neutral"):
        return None
    try:
        conf = float(d.get("confidence"))
    except (TypeError, ValueError):
        return None
    if not (0.0 <= conf <= 100.0):
        return None
    return {"signal": sig, "confidence": conf,
            "reasoning": str(d.get("reasoning", ""))[:200]}


def run_debate(verdict: TeamVerdict, chat_fn=None,
               extra_views: list[tuple[str, str]] | None = None) -> DebateOutcome | None:
    """对单股跑 Bull→Bear→Referee 三轮（v4-pro）。失败返回 None。

    chat_fn: 注入点（测试 mock 用）；默认 llm.client.chat + MODEL_REASONING。
    extra_views: 额外观点（如人格角色），注入仲裁上下文 [(角色名, 观点文本)]。
    """
    if chat_fn is None:
        try:
            from alphapulse.llm.client import chat, is_configured, MODEL_REASONING
            if not is_configured():
                logger.info("未配置 DEEPSEEK_API_KEY，跳过辩论")
                return None
            def chat_fn(prompt):  # noqa: E306
                return chat(prompt, system=_SYSTEM, model=MODEL_REASONING,
                            temperature=0.4, max_tokens=600)
        except Exception as e:
            logger.warning(f"LLM 客户端不可用: {e}")
            return None

    ev = _evidence_json(verdict)
    args = {"symbol": verdict.symbol, "name": verdict.name, "evidence": ev}
    extra = ""
    if extra_views:
        extra = "\n" + "\n".join(f"{n}的观点：{t}" for n, t in extra_views) + "\n"
    try:
        bull = chat_fn(_BULL_TMPL.format(**args))
        bear = chat_fn(_BEAR_TMPL.format(**args, bull=bull))
        ref_raw = chat_fn(_REFEREE_TMPL.format(**args, bull=bull, bear=bear,
                                               extra=extra))
    except Exception as e:
        logger.warning(f"{verdict.symbol} 辩论调用失败: {e}")
        return None

    ref = parse_referee(ref_raw)
    if ref is None:
        logger.warning(f"{verdict.symbol} 仲裁 JSON 解析失败: {ref_raw[:80]!r}")
        return None
    return DebateOutcome(bull=str(bull).strip(), bear=str(bear).strip(),
                         signal=ref["signal"], confidence=ref["confidence"],
                         reasoning=ref["reasoning"])
