"""DeepSeek 客户端 — openai SDK 直连（不引入 LangChain，规避 Py3.14 兼容风险）。

模型路由（CLAUDE.md）：
- deepseek-v4-pro：重推理（因子设计、策略逻辑、案例分析）
- deepseek-v4-flash：批量（报告生成、摘要、AI研判）

密钥来源（优先级）：环境变量 DEEPSEEK_API_KEY > 项目根 .env 文件（gitignored）
"""

import os
from pathlib import Path

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
MODEL_REASONING = "deepseek-v4-pro"
MODEL_BATCH = "deepseek-v4-flash"

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class LLMNotConfigured(RuntimeError):
    pass


def _read_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    try:
        for line in _ENV_FILE.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def get_client():
    """惰性创建 openai 客户端（key 缺失时抛 LLMNotConfigured）。"""
    api_key = _read_key()
    if not api_key:
        raise LLMNotConfigured(
            "未配置 DEEPSEEK_API_KEY。在项目根 .env 写入 DEEPSEEK_API_KEY=sk-... "
            "或 export 环境变量")
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def chat(prompt: str, system: str = "", model: str = MODEL_BATCH,
         temperature: float = 0.3, max_tokens: int = 4000) -> str:
    """单轮对话，返回文本。"""
    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model, messages=messages,
        temperature=temperature, max_tokens=max_tokens)
    return resp.choices[0].message.content or ""


def is_configured() -> bool:
    return bool(_read_key())
