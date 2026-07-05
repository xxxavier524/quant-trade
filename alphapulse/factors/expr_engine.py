"""迷你因子表达式引擎（路线图#3，qlib 思想本地化）。

因子 = 一行表达式字符串，AST 白名单解析 + 树遍历求值，全程无 exec/eval。
求值口径：单股时间序列（与全项目 compute(df)->Series 一致）；
截面因子走 zoo_bridge，不在本引擎范围。

示例：
    >>> compute(df, "(close - Mean(close, 20)) / Std(close, 20)")
    >>> compute(df, "EMA(EMA(close,10),10) > (MA(close,14)+MA(close,28)+MA(close,57)+MA(close,114))/4")
    >>> compute(df, "j < j_threshold", j_threshold=13)   # 未知名先查params

DSL 参考（DeepSeek 生成因子时以此为词表）：
- 字段: open high low close volume amount turnover market_cap vwap（兼容 $close 写法）
- 时序: Ref(x,n) Delta(x,n)                       # n≥0，Ref(x,-n) 未来函数一律拒绝
- 滚动: Mean/MA Sum Std Var Max/HHV Min/LLV Med Mad Skew Kurt
        Quantile(x,n,q) Rank(x,n) IdxMax(x,n) IdxMin(x,n) Count(cond,n)
- 回归: Slope(x,n) Rsquare(x,n) Resi(x,n)          # x 对窗口内时间的 OLS
- 双序列: Corr(x,y,n) Cov(x,y,n)
- 平滑: EMA(x,n) WMA(x,n) SMA(x,n,m)               # SMA=通达信 ewm(alpha=m/n)
- 逐元素: Abs Log Sign Sqrt Power(a,b) Greater(a,b) Less(a,b) If(c,a,b) Cross(a,b)
- 运算符: + - * / ** % 比较 & | ^ ~ and or not (x if c else y)
- 歧义规避: Max/Min/HHV/LLV 固定滚动窗口语义；成对 max/min 只用 Greater/Less
"""

from __future__ import annotations

import ast
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

MAX_NODES = 500
MAX_DEPTH = 40

FIELDS = ("open", "high", "low", "close", "volume", "amount",
          "turnover", "market_cap", "vwap")

EXPRESSIONS_FILE = Path(__file__).resolve().parent / "expressions.json"


# ---------------------------------------------------------------- 工具

def _wrap(values, ref):
    """ndarray → Series（借用参考 Series 的 index）；标量原样返回。"""
    if isinstance(values, pd.Series):
        return values
    if np.isscalar(values) or values is None:
        return values
    if isinstance(ref, pd.Series):
        return pd.Series(np.asarray(values), index=ref.index)
    return pd.Series(np.asarray(values))


def _first_series(*args):
    for a in args:
        if isinstance(a, pd.Series):
            return a
    return None


def _window(n, op: str) -> int:
    """滚动窗口参数校验：正整数（容忍 5.0 这类整值浮点）。"""
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if not isinstance(n, (int, np.integer)) or isinstance(n, bool) or n <= 0:
        raise ExprError(f"{op}: 窗口参数须为正整数，得到 {n!r}")
    return int(n)


def _series(x, op: str) -> pd.Series:
    if not isinstance(x, pd.Series):
        raise ExprError(f"{op}: 第一个参数须为序列，得到标量 {x!r}")
    return x


class ExprError(ValueError):
    """表达式解析/求值错误（信息面向 LLM 重试反馈，保持可读）。"""


# ---------------------------------------------------------------- 算子实现

def _op_ref(x, n):
    n = _window(n, "Ref") if n != 0 else 0
    return _series(x, "Ref").shift(n)


def _op_delta(x, n):
    x = _series(x, "Delta")
    return x - x.shift(_window(n, "Delta"))


def _rolling(x, n, op):
    x = _series(x, op)
    if x.dtype == bool:  # 条件序列进滚动统计（如 Mean(close>Ref(close,1), d)）
        x = x.astype(float)
    return x.rolling(_window(n, op))


def _op_mad(x, n):
    return _rolling(x, n, "Mad").apply(
        lambda a: np.mean(np.abs(a - a.mean())), raw=True)


def _op_rank(x, n):
    return _rolling(x, n, "Rank").rank(pct=True)


def _op_quantile(x, n, q):
    if not isinstance(q, (int, float)) or not 0 <= q <= 1:
        raise ExprError(f"Quantile: 分位数须在[0,1]，得到 {q!r}")
    return _rolling(x, n, "Quantile").quantile(float(q))


def _idx_extreme(x, n, op, argfn):
    """窗口内极值位置（1-based，自窗口起点计；同 qlib IdxMax/IdxMin）。"""
    x = _series(x, op)
    n = _window(n, op)
    vals = x.to_numpy(dtype=float)
    if len(vals) < n:
        return pd.Series(np.nan, index=x.index)
    win = np.lib.stride_tricks.sliding_window_view(vals, n)
    idx = argfn(win, axis=1).astype(float) + 1
    idx[np.isnan(win).any(axis=1)] = np.nan
    return pd.Series(np.concatenate([np.full(n - 1, np.nan), idx]), index=x.index)


def _op_idxmax(x, n):
    return _idx_extreme(x, n, "IdxMax", np.argmax)


def _op_idxmin(x, n):
    return _idx_extreme(x, n, "IdxMin", np.argmin)


def _op_count(cond, n):
    return _series(cond, "Count").astype(float).rolling(_window(n, "Count")).sum()


def _linreg_parts(x: pd.Series, n: int):
    """滚动 OLS（x 对窗口内位置 t=0..n-1）的公共中间量。"""
    t = np.arange(n, dtype=float)
    st, stt = t.sum(), (t * t).sum()
    vals = x.to_numpy(dtype=float)
    if len(vals) < n:
        nanpad = np.full(len(vals), np.nan)
        return nanpad, nanpad, nanpad, st, stt, n
    sxy = np.convolve(vals, t[::-1], mode="valid")          # Σ t_i·x_i
    sx = x.rolling(n).sum().to_numpy()[n - 1:]
    sxx = (x * x).rolling(n).sum().to_numpy()[n - 1:]
    pad = np.full(n - 1, np.nan)
    return (np.concatenate([pad, sxy]), np.concatenate([pad, sx]),
            np.concatenate([pad, sxx]), st, stt, n)


def _op_slope(x, n):
    x = _series(x, "Slope"); n = _window(n, "Slope")
    sxy, sx, _, st, stt, n = _linreg_parts(x, n)
    denom = n * stt - st * st
    return pd.Series((n * sxy - st * sx) / denom if denom else np.nan, index=x.index)


def _op_rsquare(x, n):
    x = _series(x, "Rsquare"); n = _window(n, "Rsquare")
    sxy, sx, sxx, st, stt, n = _linreg_parts(x, n)
    denom = (n * stt - st * st) * (n * sxx - sx * sx)
    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = np.square(n * sxy - st * sx) / denom
    return pd.Series(np.where(np.isfinite(r2), r2, np.nan), index=x.index)


def _op_resi(x, n):
    x = _series(x, "Resi"); n = _window(n, "Resi")
    sxy, sx, _, st, stt, n = _linreg_parts(x, n)
    denom = n * stt - st * st
    b = (n * sxy - st * sx) / denom if denom else np.nan
    a = (sx - b * st) / n
    return pd.Series(x.to_numpy(dtype=float) - (a + b * (n - 1)), index=x.index)


def _op_corr(x, y, n):
    r = _rolling(x, n, "Corr").corr(_series(y, "Corr"))
    return r.replace([np.inf, -np.inf], np.nan)


def _op_cov(x, y, n):
    return _rolling(x, n, "Cov").cov(_series(y, "Cov"))


def _op_ema(x, n):
    return _series(x, "EMA").ewm(span=_window(n, "EMA"), adjust=False).mean()


def _op_wma(x, n):
    """线性加权均线（通达信 WMA）：权重 1..n，越近权重越大。"""
    x = _series(x, "WMA"); n = _window(n, "WMA")
    w = np.arange(1, n + 1, dtype=float)
    return x.rolling(n).apply(lambda a: float(np.dot(a, w) / w.sum()), raw=True)


def _op_sma_tdx(x, n, m=1):
    """通达信 SMA(X,N,M) = X.ewm(alpha=M/N, adjust=False).mean()。"""
    x = _series(x, "SMA"); n = _window(n, "SMA")
    if isinstance(m, float) and m.is_integer():
        m = int(m)
    if not isinstance(m, (int, np.integer)) or not 0 < m <= n:
        raise ExprError(f"SMA: 须满足 0 < M ≤ N，得到 M={m!r} N={n}")
    return x.ewm(alpha=m / n, adjust=False).mean()


def _op_if(cond, a, b):
    ref = _first_series(cond, a, b)
    return _wrap(np.where(cond, a, b), ref)


def _op_cross(a, b):
    """通达信 CROSS(A,B)：昨 A≤B 且今 A>B（与 zhixing_washout 口径一致）。"""
    ref = _first_series(a, b)
    if ref is None:
        raise ExprError("Cross: 至少一个参数须为序列")
    pa = a.shift(1) if isinstance(a, pd.Series) else a
    pb = b.shift(1) if isinstance(b, pd.Series) else b
    return ((pa <= pb) & (a > b)).fillna(False)


def _op_log(x):
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.log(x)
    return _wrap(out, _first_series(x))


def _op_sqrt(x):
    with np.errstate(invalid="ignore"):
        out = np.sqrt(x)  # 负数 → NaN（不静默截断）
    return _wrap(out, _first_series(x))


OPERATORS: dict[str, callable] = {
    # 时序
    "Ref": _op_ref, "Delta": _op_delta,
    # 滚动统计
    "Mean": lambda x, n: _rolling(x, n, "Mean").mean(),
    "Sum": lambda x, n: _rolling(x, n, "Sum").sum(),
    "Std": lambda x, n: _rolling(x, n, "Std").std(),
    "Var": lambda x, n: _rolling(x, n, "Var").var(),
    "Max": lambda x, n: _rolling(x, n, "Max").max(),
    "Min": lambda x, n: _rolling(x, n, "Min").min(),
    "Med": lambda x, n: _rolling(x, n, "Med").median(),
    "Mad": _op_mad,
    "Skew": lambda x, n: _rolling(x, n, "Skew").skew(),
    "Kurt": lambda x, n: _rolling(x, n, "Kurt").kurt(),
    "Quantile": _op_quantile, "Rank": _op_rank,
    "IdxMax": _op_idxmax, "IdxMin": _op_idxmin, "Count": _op_count,
    # 回归
    "Slope": _op_slope, "Rsquare": _op_rsquare, "Resi": _op_resi,
    # 双序列
    "Corr": _op_corr, "Cov": _op_cov,
    # 平滑
    "EMA": _op_ema, "WMA": _op_wma, "SMA": _op_sma_tdx,
    # 逐元素
    "Abs": lambda x: _wrap(np.abs(x), _first_series(x)),
    "Log": _op_log,
    "Sign": lambda x: _wrap(np.sign(x), _first_series(x)),
    "Sqrt": lambda x: _op_sqrt(x),
    "Power": lambda a, b: a ** b,
    "Greater": lambda a, b: _wrap(np.maximum(a, b), _first_series(a, b)),
    "Less": lambda a, b: _wrap(np.minimum(a, b), _first_series(a, b)),
    "If": _op_if, "Cross": _op_cross,
}
# 通达信别名（大小写敏感注册，避免 MAX(a,b) 成对语义混入）
ALIASES = {"MA": "Mean", "HHV": "Max", "LLV": "Min", "REF": "Ref",
           "COUNT": "Count", "IF": "If", "CROSS": "Cross", "ABS": "Abs",
           "STD": "Std", "EMA": "EMA", "SMA": "SMA", "SUM": "Sum", "LOG": "Log"}
_ALL_FUNCS = set(OPERATORS) | set(ALIASES)


# ---------------------------------------------------------------- 解析与校验

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)
_ALLOWED_UNARY = (ast.USub, ast.UAdd, ast.Invert, ast.Not)
_ALLOWED_CMP = (ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq)
_ALLOWED_BITOPS = (ast.BitAnd, ast.BitOr, ast.BitXor)


def _preprocess(expr: str) -> str:
    """qlib `$close` 写法兼容：剥掉 $ 前缀。"""
    return re.sub(r"\$([A-Za-z_]\w*)", r"\1", expr)


def _check_node(node: ast.AST, problems: list[str]) -> None:
    if isinstance(node, (ast.Expression, ast.Load,
                         ast.operator, ast.unaryop, ast.cmpop, ast.boolop)):
        return  # 运算符节点在其父节点处校验
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, bool)):
            problems.append(f"禁止常量类型: {type(node.value).__name__}")
    elif isinstance(node, ast.Name):
        pass  # 字段/参数，求值时解析
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS + _ALLOWED_BITOPS):
            problems.append(f"禁止运算符: {type(node.op).__name__}")
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARY):
            problems.append(f"禁止一元运算符: {type(node.op).__name__}")
    elif isinstance(node, ast.Compare):
        for op in node.ops:
            if not isinstance(op, _ALLOWED_CMP):
                problems.append(f"禁止比较符: {type(op).__name__}")
    elif isinstance(node, (ast.BoolOp, ast.IfExp)):
        pass
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            problems.append("函数调用只允许白名单函数名（禁属性调用）")
        elif node.func.id not in _ALL_FUNCS:
            problems.append(f"未知函数: {node.func.id}（可用: {sorted(_ALL_FUNCS)}）")
        if node.keywords:
            problems.append("禁止关键字参数，请用位置参数")
        # Ref/REF 负数常量 = 未来函数，解析期即拒
        if (isinstance(node.func, ast.Name) and node.func.id in ("Ref", "REF")
                and len(node.args) == 2):
            a = node.args[1]
            if isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub):
                problems.append("Ref(x, -n) 为未来函数，禁止")
    else:
        problems.append(f"禁止语法节点: {type(node).__name__}")


def validate(expr: str) -> list[str]:
    """静态校验，返回问题列表（空=通过）。"""
    try:
        tree = ast.parse(_preprocess(expr), mode="eval")
    except SyntaxError as e:
        return [f"语法错误: {e.msg}（位置 {e.offset}）"]

    problems: list[str] = []
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        problems.append(f"表达式过大: {len(nodes)} 节点 > {MAX_NODES}")

    def depth(n, d=0):
        return max([d] + [depth(c, d + 1) for c in ast.iter_child_nodes(n)])
    if depth(tree) > MAX_DEPTH:
        problems.append(f"嵌套过深 > {MAX_DEPTH}")

    for node in nodes:
        _check_node(node, problems)
    return problems


@lru_cache(maxsize=512)
def _compile(expr: str) -> ast.Expression:
    problems = validate(expr)
    if problems:
        raise ExprError("; ".join(problems))
    return ast.parse(_preprocess(expr), mode="eval")


# ---------------------------------------------------------------- 求值

class _Evaluator:
    def __init__(self, env: dict):
        self.env = env

    def visit(self, node):
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            raise ExprError(
                f"未知名称: {node.id}（字段: {[k for k in FIELDS if k in self.env]}，"
                f"参数: {[k for k in self.env if k not in FIELDS]}）")
        if isinstance(node, ast.BinOp):
            left, right = self.visit(node.left), self.visit(node.right)
            return self._binop(node.op, left, right)
        if isinstance(node, ast.UnaryOp):
            v = self.visit(node.operand)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return +v
            return ~_to_bool(v)  # Invert / Not 均为逐元素布尔取反
        if isinstance(node, ast.Compare):
            left = self.visit(node.left)
            result = None
            for op, comparator in zip(node.ops, node.comparators):
                right = self.visit(comparator)
                part = self._compare(op, left, right)
                result = part if result is None else result & part
                left = right
            return result
        if isinstance(node, ast.BoolOp):
            vals = [_to_bool(self.visit(v)) for v in node.values]
            out = vals[0]
            for v in vals[1:]:
                out = (out & v) if isinstance(node.op, ast.And) else (out | v)
            return out
        if isinstance(node, ast.IfExp):
            return _op_if(self.visit(node.test), self.visit(node.body),
                          self.visit(node.orelse))
        if isinstance(node, ast.Call):
            fname = ALIASES.get(node.func.id, node.func.id)
            fn = OPERATORS[fname]
            args = [self.visit(a) for a in node.args]
            return fn(*args)
        raise ExprError(f"不支持的节点: {type(node).__name__}")  # 已由validate兜住

    @staticmethod
    def _binop(op, l, r):
        if isinstance(op, ast.Add):
            return l + r
        if isinstance(op, ast.Sub):
            return l - r
        if isinstance(op, ast.Mult):
            return l * r
        if isinstance(op, ast.Div):
            with np.errstate(divide="ignore", invalid="ignore"):
                return l / r
        if isinstance(op, ast.Pow):
            return l ** r
        if isinstance(op, ast.Mod):
            return l % r
        if isinstance(op, ast.BitAnd):
            return _to_bool(l) & _to_bool(r)
        if isinstance(op, ast.BitOr):
            return _to_bool(l) | _to_bool(r)
        if isinstance(op, ast.BitXor):
            return _to_bool(l) ^ _to_bool(r)
        raise ExprError(f"禁止运算符: {type(op).__name__}")

    @staticmethod
    def _compare(op, l, r):
        if isinstance(op, ast.Gt):
            return l > r
        if isinstance(op, ast.Lt):
            return l < r
        if isinstance(op, ast.GtE):
            return l >= r
        if isinstance(op, ast.LtE):
            return l <= r
        if isinstance(op, ast.Eq):
            return l == r
        return l != r


def _to_bool(v):
    """布尔上下文归一：数值序列视为非零，bool 序列原样。"""
    if isinstance(v, pd.Series) and v.dtype != bool:
        return v.fillna(0) != 0
    return v


def _build_env(data: pd.DataFrame, params: dict) -> dict:
    env = {}
    for col in FIELDS:
        if col in data.columns:
            env[col] = data[col].astype(float)
    if "vwap" not in env:
        if "amount" in env and "volume" in env:
            env["vwap"] = env["amount"] / env["volume"].replace(0, np.nan)
        elif all(k in env for k in ("high", "low", "close")):
            env["vwap"] = (env["high"] + env["low"] + env["close"]) / 3
    for k, v in params.items():
        if k in env:
            raise ExprError(f"参数名与字段冲突: {k}")
        env[k] = v
    return env


def compute(data: pd.DataFrame, expr: str, **params) -> pd.Series:
    """求值表达式 → 与 data 等长的 Series（NaN 原样保留）。

    与 factor_registry 的 compute(data, **params) 口径兼容：
    表达式中未识别的名称按 params 解析（如阈值 j_threshold）。
    """
    tree = _compile(expr)
    result = _Evaluator(_build_env(data, params)).visit(tree)
    if not isinstance(result, pd.Series):
        # 常量表达式 → 广播
        result = pd.Series(result, index=data.index, dtype=float)
    return result


def smoke_test(expr: str, params: dict | None = None) -> tuple[bool, str]:
    """随机 OHLCV 冒烟（与 factor_gen.sandbox_test 同构）。"""
    rng = np.random.default_rng(42)
    n = 300
    c = pd.Series(20 + rng.standard_normal(n).cumsum() * 0.2).clip(lower=1)
    vol = rng.integers(1e5, 1e6, n).astype(float)
    df = pd.DataFrame({"open": c * 0.995, "high": c * 1.02, "low": c * 0.98,
                       "close": c, "volume": vol, "amount": vol * c,
                       "turnover": rng.uniform(0.5, 5, n),
                       "market_cap": c * 1e8})
    try:
        out = compute(df, expr, **(params or {}))
    except ExprError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001 求值内部的 pandas 报错也回喂
        return False, f"求值失败: {e}"
    if len(out) != n:
        return False, f"返回长度 {len(out)} != {n}"
    finite = out.notna().mean() if out.dtype != bool else 1.0
    return True, f"冒烟通过（非NaN比例 {finite:.0%}）"


# ---------------------------------------------------------------- 表达式注册表

def load_expression_registry() -> dict:
    try:
        return json.loads(EXPRESSIONS_FILE.read_text())
    except Exception:
        return {}


def register_expression(name: str, expr: str, description: str = "",
                        params: dict | None = None, cast: str | None = None,
                        source: str = "manual", enabled: bool = False) -> dict:
    """校验+冒烟通过后写入 expressions.json（默认 enabled=False，与生成因子同规）。"""
    problems = validate(expr)
    if problems:
        return {"ok": False, "message": "校验失败: " + "; ".join(problems)}
    ok, note = smoke_test(expr, params)
    if not ok:
        return {"ok": False, "message": note}
    reg = load_expression_registry()
    reg[name] = {"expr": expr, "description": description,
                 "params": params or {}, "cast": cast,
                 "source": source, "enabled": enabled}
    EXPRESSIONS_FILE.write_text(json.dumps(reg, ensure_ascii=False, indent=2))
    return {"ok": True, "name": name, "message": f"已注册。{note}"}


def compute_registered(name: str, data: pd.DataFrame, **overrides) -> pd.Series:
    """按名计算已注册表达式（factor_registry 兜底入口）。"""
    reg = load_expression_registry()
    if name not in reg:
        raise ExprError(f"表达式注册表中无因子: {name}（可用: {sorted(reg)}）")
    entry = reg[name]
    merged = {**entry.get("params", {}), **overrides}
    out = compute(data, entry["expr"], **merged)
    if entry.get("cast") == "bool":
        out = out.fillna(False).astype(bool)
    return out
