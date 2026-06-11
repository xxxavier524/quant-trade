"""自然语言指导ML学习K线形态（用户需求 2026-06-12）。

闭环：
1. 用户中文描述形态（如"N型结构：先涨≥15%，缩量回调不破前低，再放量转强"）
2. DeepSeek 生成标注函数（复用 factor_gen 的 AST 白名单+沙箱安全链）
3. 历史全量标注 → 出现次数 + 前向收益验证（这个形态历史上赚不赚钱）
4. 用户视觉确认（GUI展示命中的K线案例）后启用 →
   该形态标签进入 pattern_model.feature_frame 作为特征列，
   GBDT 重训时学习"该形态与其他量价特征的交互"——这就是"教ML认形态"

形态注册表：models/taught_patterns.json
  {slug: {name, description, file, enabled, taught_at, stats}}
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TAUGHT_REGISTRY = PROJECT_ROOT / "models" / "taught_patterns.json"
GENERATED_DIR = PROJECT_ROOT / "alphapulse" / "factors" / "generated"

TEACH_SYSTEM_HINT = """补充背景（用户的形态语言体系）：
- N型结构 = 上涨一波→回调（不破前低、通常缩量）→再上涨创新高的三段结构
- 横盘 = 连续N日振幅极小（区间总振幅≤15%）
- 机构票/主力控盘 = 长期运行在知行黄线上方、回调缩量有承接、放量阳推动、
  很少出现巨量阴线；反之"主力不控盘"=频繁跌破黄线、放量下跌无修复
- 知行白线=EMA(EMA(C,10),10)；黄线=(MA14+MA28+MA57+MA114)/4
把这些口语概念翻译成可计算条件时，量化阈值写成 params.get() 可调参数。"""


def load_taught() -> dict:
    try:
        return json.loads(TAUGHT_REGISTRY.read_text())
    except Exception:
        return {}


def _save_taught(reg: dict) -> None:
    TAUGHT_REGISTRY.parent.mkdir(exist_ok=True)
    TAUGHT_REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2))


def load_labeler(slug: str):
    """加载已教形态的标注函数（受限命名空间执行，与生成时同等安全约束）。"""
    reg = load_taught()
    entry = reg.get(slug)
    if not entry:
        return None
    path = GENERATED_DIR / entry["file"]
    if not path.exists():
        return None
    from alphapulse.llm.factor_gen import validate_code
    import numpy as np
    code = path.read_text()
    # 落盘文件 = 头部docstring + import行 + 函数体；剥离前两者再过AST白名单
    lines = [l for l in code.splitlines()
             if not l.startswith(("import ", "from "))]
    body = "\n".join(lines)
    if '"""' in body:  # 去掉文件头docstring（取第二个"""之后）
        parts = body.split('"""')
        if len(parts) >= 3:
            body = '"""'.join(parts[2:]).lstrip()
    if validate_code(body):
        return None
    ns = {"pd": pd, "np": np, "__builtins__": {
        "abs": abs, "min": min, "max": max, "round": round, "float": float,
        "int": int, "bool": bool, "len": len, "range": range, "sum": sum,
        "all": all, "any": any, "True": True, "False": False, "None": None}}
    exec(compile(body, f"<taught_{slug}>", "exec"), ns)  # noqa: S102 AST已校验
    return ns.get("compute")


def teach_pattern(name: str, description: str,
                  stocks: dict[str, pd.DataFrame] | None = None) -> dict:
    """教学主流程：生成标注器→历史验证→注册（默认不启用，等用户确认）。

    Returns:
        dict: ok/slug/message/stats/examples（命中案例 [(symbol, date), ...]）
    """
    from alphapulse.llm.factor_gen import generate_factor
    from alphapulse.llm import factor_gen

    # 借用 factor_gen 管线，注入形态语言体系背景
    orig_prompt = factor_gen.SYSTEM_PROMPT
    factor_gen.SYSTEM_PROMPT = orig_prompt + "\n\n" + TEACH_SYSTEM_HINT
    try:
        r = generate_factor(description, name, use_llm=True)
    finally:
        factor_gen.SYSTEM_PROMPT = orig_prompt
    if not r["ok"]:
        return {"ok": False, "message": r["message"], "code": r.get("code")}

    slug = r["name"]
    result = {"ok": True, "slug": slug, "code": r["code"], "message": r["message"],
              "stats": None, "examples": []}

    # 历史验证（提供了股票池才做）
    if stocks:
        labeler = _compile(r["code"])
        if labeler is not None:
            stats, examples = _validate_labeler(labeler, stocks)
            result["stats"] = stats
            result["examples"] = examples

    reg = load_taught()
    reg[slug] = {"name": name, "description": description,
                 "file": f"{slug}.py", "enabled": False,
                 "taught_at": date.today().isoformat(),
                 "stats": result["stats"]}
    _save_taught(reg)
    result["message"] += " 已登记为待确认形态——在GUI确认案例后启用，重训ML即生效。"
    return result


def _compile(code: str):
    import numpy as np
    ns = {"pd": pd, "np": np, "__builtins__": {
        "abs": abs, "min": min, "max": max, "round": round, "float": float,
        "int": int, "bool": bool, "len": len, "range": range, "sum": sum,
        "all": all, "any": any, "True": True, "False": False, "None": None}}
    try:
        exec(compile(code, "<labeler>", "exec"), ns)  # noqa: S102
        return ns.get("compute")
    except Exception:
        return None


def _validate_labeler(labeler, stocks: dict[str, pd.DataFrame],
                      max_examples: int = 12) -> tuple[dict, list]:
    """历史标注 + 前向收益统计 + 命中案例采样。"""
    from alphapulse.backtest.signal_validator import forward_returns, summarize
    events, examples = [], []
    for sym, df in stocks.items():
        try:
            sig = labeler(df).fillna(False).astype(bool)
        except Exception:
            continue
        if not sig.any():
            continue
        fwd = forward_returns(df["close"].astype(float), [5, 10])
        ev = fwd[sig].copy()
        dates = df["date"] if "date" in df.columns else df.index.astype(str)
        ev.insert(0, "date", pd.Series(dates)[sig].values)
        ev.insert(0, "symbol", sym)
        events.append(ev)
        if len(examples) < max_examples:
            examples.append((sym, str(pd.Series(dates)[sig].iloc[-1])))
    if not events:
        return {"n_signals": 0}, []
    allev = pd.concat(events, ignore_index=True)
    return summarize(allev, [5, 10]), examples


def set_enabled(slug: str, enabled: bool) -> bool:
    reg = load_taught()
    if slug not in reg:
        return False
    reg[slug]["enabled"] = enabled
    _save_taught(reg)
    return True


def enabled_pattern_features(df: pd.DataFrame) -> dict[str, pd.Series]:
    """已启用形态 → 特征列（pattern_model.feature_frame 调用）。

    每个形态贡献两列：当日命中(0/1) + 近20日命中次数（形态密度）。
    """
    out = {}
    for slug, entry in load_taught().items():
        if not entry.get("enabled"):
            continue
        labeler = load_labeler(slug)
        if labeler is None:
            continue
        try:
            sig = labeler(df).fillna(False).astype(float)
            out[f"pt_{slug}"] = sig
            out[f"pt_{slug}_20d"] = sig.rolling(20).sum()
        except Exception:
            continue
    return out
