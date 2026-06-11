"""自然语言 → 因子生成管线（vibe-trading 思路本地化 + DeepSeek）。

流程：
1. 先走 alphapulse/utils/nlp_factor.py 正则解析器（免费、确定性）
2. 不命中则 DeepSeek (v4-pro) 生成 compute(data)->pd.Series 代码
3. 安全门：AST 白名单（仅 pandas/numpy；禁 import/exec/eval/open/属性逃逸）
4. 沙箱冒烟：随机OHLCV跑通 + 输出类型/长度校验
5. 落盘 alphapulse/factors/generated/{name}.py + generated/registry.json
   （生成因子默认不进每日选股，需用户在 GUI/配置中显式启用）
"""

import ast
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATED_DIR = PROJECT_ROOT / "alphapulse" / "factors" / "generated"
GENERATED_REGISTRY = GENERATED_DIR / "registry.json"

SYSTEM_PROMPT = """你是A股量化因子工程师。把用户的中文选股描述翻译成一个Python函数。

严格约束：
1. 只输出一个 python 代码块，函数签名必须是：
   def compute(data: pd.DataFrame, **params) -> pd.Series
2. data 列：open/high/low/close/volume（float），可能有 amount/turnover/market_cap
3. 返回与 data 等长的 pd.Series[bool]（选股信号）
4. 只能用 pandas(pd)/numpy(np)，禁止 import、文件、网络
5. 禁止未来函数：只能用 rolling/shift(正数)/ewm/cumsum 等因果操作，
   绝不允许 shift(-n) 或用未来数据
6. 通达信语义对照：SMA(X,N,M)=X.ewm(alpha=M/N,adjust=False).mean()；
   LLV/HHV=rolling(N).min()/max()；REF(X,N)=X.shift(N)；
   KDJ: RSV=(C-LLV(L,9))/(HHV(H,9)-LLV(L,9))*100, K=SMA(RSV,3,1), D=SMA(K,3,1), J=3K-2D
7. 知行白线=close.ewm(span=10,adjust=False).mean().ewm(span=10,adjust=False).mean()；
   知行黄线=(MA14+MA28+MA57+MA114)/4
8. 阈值写成 params.get("xxx", 默认值)，方便网格搜索

示例（"J值小于15且缩量"）：
```python
def compute(data: pd.DataFrame, **params) -> pd.Series:
    j_th = params.get("j_threshold", 15.0)
    shrink = params.get("shrink_ratio", 0.5)
    c, h, l, v = data["close"], data["high"], data["low"], data["volume"]
    rsv = (c - l.rolling(9).min()) / (h.rolling(9).max() - l.rolling(9).min()) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d
    vol_ok = v <= shrink * v.rolling(5).mean()
    return ((j < j_th) & vol_ok).fillna(False).astype(bool)
```"""

# AST 白名单
_ALLOWED_CALL_NAMES = {"compute", "abs", "min", "max", "round", "float", "int", "bool", "len", "range"}
_ALLOWED_MODULES = {"pd", "np"}
_BANNED_NODES = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal,
                 ast.AsyncFunctionDef, ast.Await, ast.Lambda)
_BANNED_NAMES = {"exec", "eval", "open", "input", "compile", "__import__",
                 "globals", "locals", "vars", "getattr", "setattr", "delattr",
                 "breakpoint", "exit", "quit", "os", "sys", "subprocess"}


def validate_code(code: str) -> list[str]:
    """AST 安全校验，返回问题列表（空=通过）。"""
    problems = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"语法错误: {e}"]

    has_compute = False
    for node in ast.walk(tree):
        if isinstance(node, _BANNED_NODES):
            problems.append(f"禁止节点: {type(node).__name__}")
        if isinstance(node, ast.FunctionDef) and node.name == "compute":
            has_compute = True
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            problems.append(f"禁止名称: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"禁止双下划线属性: {node.attr}")
        # 禁止 shift(负数)（未来函数）
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "shift"):
            for a in node.args:
                if isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub):
                    problems.append("禁止 shift(-n) 未来函数")
    if not has_compute:
        problems.append("缺少 compute 函数")
    return problems


def sandbox_test(code: str) -> tuple[bool, str]:
    """受限命名空间内执行并用随机数据冒烟。"""
    ns = {"pd": pd, "np": np, "__builtins__": {
        "abs": abs, "min": min, "max": max, "round": round, "float": float,
        "int": int, "bool": bool, "len": len, "range": range, "sum": sum,
        "all": all, "any": any, "sorted": sorted, "enumerate": enumerate,
        "zip": zip, "list": list, "dict": dict, "tuple": tuple, "set": set,
        "True": True, "False": False, "None": None}}
    try:
        exec(compile(code, "<generated_factor>", "exec"), ns)  # noqa: S102 AST已白名单校验
        fn = ns.get("compute")
        rng = np.random.default_rng(42)
        n = 300
        c = pd.Series(20 + rng.standard_normal(n).cumsum() * 0.2).clip(lower=1)
        df = pd.DataFrame({"open": c * 0.995, "high": c * 1.02, "low": c * 0.98,
                           "close": c, "volume": rng.integers(1e5, 1e6, n).astype(float)})
        out = fn(df)
        if not isinstance(out, pd.Series):
            return False, f"返回类型 {type(out).__name__}，应为 pd.Series"
        if len(out) != n:
            return False, f"返回长度 {len(out)} != {n}"
        return True, f"冒烟通过（随机数据信号数 {int(out.astype(bool).sum())}）"
    except Exception as e:
        return False, f"沙箱执行失败: {e}"


def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
    return s or "gen_factor"


def load_generated_registry() -> dict:
    try:
        return json.loads(GENERATED_REGISTRY.read_text())
    except Exception:
        return {}


def generate_factor(description: str, name: str, use_llm: bool = True) -> dict:
    """中文描述 → 安全校验过的因子文件。

    Returns:
        dict: {ok, name, path, code, message}
    """
    slug = _slugify(name)

    # 1. 正则解析器优先（零成本）；捕获条件数 < 描述子句数说明理解不完整→走LLM
    code = None
    source = "regex"
    try:
        from alphapulse.utils.nlp_factor import parse_description
        parsed = parse_description(description)
        n_clauses = len([c for c in re.split(r"且|并且|同时|或|或者", description)
                         if len(c.strip()) >= 4])
        if parsed.get("conditions") and len(parsed["conditions"]) >= n_clauses:
            code = parsed["code"]
            # 去掉解析器自带的import行（沙箱白名单不允许import）
            code = "\n".join(l for l in code.splitlines()
                             if not l.startswith("import "))
    except Exception:
        code = None

    # 2. LLM 兜底
    if not code and use_llm:
        from alphapulse.llm.client import chat, MODEL_REASONING
        raw = chat(description, system=SYSTEM_PROMPT,
                   model=MODEL_REASONING, temperature=0.1)
        code = _extract_code(raw)
        source = "deepseek"
    if not code:
        return {"ok": False, "message": "正则未命中且未启用LLM"}

    # 3. 安全门
    problems = validate_code(code)
    if problems:
        return {"ok": False, "message": "安全校验失败: " + "; ".join(problems), "code": code}

    # 4. 沙箱
    ok, note = sandbox_test(code)
    if not ok:
        return {"ok": False, "message": note, "code": code}

    # 5. 落盘 + 注册（默认 enabled=False，不自动进每日选股）
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    init_py = GENERATED_DIR / "__init__.py"
    if not init_py.exists():
        init_py.write_text("")
    path = GENERATED_DIR / f"{slug}.py"
    header = (f'"""生成因子: {name}\n\n描述: {description}\n来源: {source}\n'
              f'状态: 待验证（validate_signal 后手动启用）\n"""\n\n'
              "import pandas as pd\nimport numpy as np\n\n\n")
    path.write_text(header + code)

    reg = load_generated_registry()
    reg[slug] = {"name": name, "description": description, "source": source,
                 "enabled": False, "file": path.name}
    GENERATED_REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2))

    return {"ok": True, "name": slug, "path": str(path), "code": code,
            "message": f"已生成（{source}）。{note}。用 validate_signal 验证后再启用。"}
