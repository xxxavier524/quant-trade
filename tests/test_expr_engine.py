"""因子表达式引擎测试（路线图#3 验收）。

1. 算子 vs pandas 参考实现逐点对拍
2. 知行公式对拍（验收标准#1：白线/黄线/洗盘四线/MACD DIF/KDJ J）
3. 恶意表达式拒绝矩阵（验收标准#3）
4. Alpha158 全量跑通（验收标准#2 的本地部分）
5. 表达式注册表 + factor_registry 兜底

全部使用合成数据，不依赖外接盘。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alphapulse.factors import expr_engine as ee  # noqa: E402
from alphapulse.factors.alpha158 import ALPHA158, compute_alpha158  # noqa: E402


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 500
    c = pd.Series(20 + rng.standard_normal(n).cumsum() * 0.2).clip(lower=1)
    v = rng.integers(1e5, 1e6, n).astype(float)
    return pd.DataFrame({"open": c * 0.995, "high": c * 1.02, "low": c * 0.98,
                         "close": c, "volume": v, "amount": v * c,
                         "turnover": rng.uniform(0.5, 5, n)})


def _close(a, b, atol=1e-10):
    assert np.allclose(a, b, equal_nan=True, atol=atol), \
        f"max diff {np.nanmax(np.abs(np.asarray(a) - np.asarray(b)))}"


# ---------------------------------------------------------------- 算子对拍

def test_rolling_ops_parity(df):
    c = df["close"]
    cases = {
        "Mean(close, 20)": c.rolling(20).mean(),
        "Sum(close, 10)": c.rolling(10).sum(),
        "Std(close, 20)": c.rolling(20).std(),
        "Var(close, 20)": c.rolling(20).var(),
        "Max(close, 20)": c.rolling(20).max(),
        "Min(close, 20)": c.rolling(20).min(),
        "HHV(close, 20)": c.rolling(20).max(),
        "LLV(low, 9)": df["low"].rolling(9).min(),
        "Med(close, 15)": c.rolling(15).median(),
        "Skew(close, 30)": c.rolling(30).skew(),
        "Kurt(close, 30)": c.rolling(30).kurt(),
        "Ref(close, 5)": c.shift(5),
        "REF(close, 1)": c.shift(1),
        "Delta(close, 5)": c - c.shift(5),
        "Quantile(close, 20, 0.8)": c.rolling(20).quantile(0.8),
        "Rank(close, 20)": c.rolling(20).rank(pct=True),
        "EMA(close, 10)": c.ewm(span=10, adjust=False).mean(),
        "SMA(close, 3, 1)": c.ewm(alpha=1 / 3, adjust=False).mean(),
        "Corr(close, volume, 20)": c.rolling(20).corr(df["volume"]),
        "Cov(close, volume, 20)": c.rolling(20).cov(df["volume"]),
        "Count(close > Ref(close,1), 10)":
            (c > c.shift(1)).astype(float).rolling(10).sum(),
        "Abs(close - open)": (c - df["open"]).abs(),
        "Greater(open, close)": np.maximum(df["open"], c),
        "Less(open, close)": np.minimum(df["open"], c),
        "Log(volume + 1)": np.log(df["volume"] + 1),
        "Sign(close - Ref(close,1))": np.sign(c - c.shift(1)),
        "Sqrt(volume)": np.sqrt(df["volume"]),
    }
    for expr, ref in cases.items():
        _close(ee.compute(df, expr), ref)


def test_wma_parity(df):
    c, n = df["close"], 10
    w = np.arange(1, n + 1, dtype=float)
    ref = c.rolling(n).apply(lambda a: np.dot(a, w) / w.sum(), raw=True)
    _close(ee.compute(df, "WMA(close, 10)"), ref)


def test_idx_ops_parity(df):
    h, n = df["high"], 20
    ref_max = h.rolling(n).apply(lambda a: float(np.argmax(a) + 1), raw=True)
    ref_min = df["low"].rolling(n).apply(lambda a: float(np.argmin(a) + 1), raw=True)
    _close(ee.compute(df, "IdxMax(high, 20)"), ref_max)
    _close(ee.compute(df, "IdxMin(low, 20)"), ref_min)


def test_regression_ops_parity(df):
    c, n = df["close"], 10
    t = np.arange(n)
    slope_ref = c.rolling(n).apply(lambda a: np.polyfit(t, a, 1)[0], raw=True)
    _close(ee.compute(df, "Slope(close, 10)"), slope_ref, atol=1e-8)

    def _r2(a):
        p = np.polyfit(t, a, 1)
        fit = np.polyval(p, t)
        return 1 - ((a - fit) ** 2).sum() / ((a - a.mean()) ** 2).sum()
    _close(ee.compute(df, "Rsquare(close, 10)"),
           c.rolling(n).apply(_r2, raw=True), atol=1e-8)

    def _resi(a):
        return a[-1] - np.polyval(np.polyfit(t, a, 1), n - 1)
    _close(ee.compute(df, "Resi(close, 10)"),
           c.rolling(n).apply(_resi, raw=True), atol=1e-8)


def test_rank_is_causal(df):
    """Rank 只用过去窗口：截断数据尾部不改变前段值。"""
    full = ee.compute(df, "Rank(close, 20)")
    part = ee.compute(df.iloc[:300], "Rank(close, 20)")
    _close(full.iloc[:300], part)


# ---------------------------------------------------------------- 知行公式对拍（验收#1）

def test_zhixing_white_line_parity(df):
    from alphapulse.factors.zhixing_trend import compute_short_trend
    _close(ee.compute(df, "EMA(EMA(close, 10), 10)"),
           compute_short_trend(df["close"]))


def test_zhixing_yellow_line_parity(df):
    from alphapulse.factors.zhixing_trend import compute_bull_bear_line
    expr = "(MA(close,14)+MA(close,28)+MA(close,57)+MA(close,114))/4"
    _close(ee.compute(df, expr), compute_bull_bear_line(df["close"]))


def test_zhixing_washout_lines_parity(df):
    from alphapulse.factors.zhixing_washout import compute_lines
    lines = compute_lines(df)
    for col, n in [("short", 3), ("medium", 10), ("med_long", 20), ("long", 21)]:
        expr = f"100*(close-LLV(low,{n}))/(HHV(close,{n})-LLV(low,{n}))"
        _close(ee.compute(df, expr), lines[col], atol=1e-9)


def test_macd_dif_parity(df):
    from alphapulse.factors.zhixing_trend import compute_macd_dif
    _close(ee.compute(df, "EMA(close,12)-EMA(close,26)"),
           compute_macd_dif(df["close"]))


def test_kdj_j_tail_parity(df):
    """KDJ J：模块版 warmup 期 rsv.fillna(50)，ewm 初值差异随 alpha=1/3 快速衰减，
    尾段应完全一致。"""
    from alphapulse.factors.kdj_j_low import compute_kdj
    _, _, j_ref = compute_kdj(df["high"], df["low"], df["close"])
    rsv = "100*(close-LLV(low,9))/(HHV(high,9)-LLV(low,9))"
    j = ee.compute(df, f"3*SMA({rsv},3,1) - 2*SMA(SMA({rsv},3,1),3,1)")
    _close(j.iloc[100:], j_ref.iloc[100:], atol=1e-6)


def test_cross_matches_washout_convention(df):
    """Cross 口径与 zhixing_washout 一致：昨≤且今>。

    参考值用引擎求值的同一批序列构造（避免 (x/y)*100 与 100*x/y
    的浮点运算顺序差异在 100 值平局处翻转比较结果）。
    """
    s_expr = "100*(close-LLV(low,3))/(HHV(close,3)-LLV(low,3))"
    l_expr = "100*(close-LLV(low,21))/(HHV(close,21)-LLV(low,21))"
    s, l = ee.compute(df, s_expr), ee.compute(df, l_expr)
    ref = ((s.shift(1) <= l.shift(1)) & (s > l)).fillna(False)
    got = ee.compute(df, f"Cross({s_expr}, {l_expr})")
    assert (got == ref).all()
    assert got.any(), "测试数据应至少出现一次上穿"


# ---------------------------------------------------------------- 安全（验收#3）

BAD_EXPRESSIONS = [
    "__import__('os').system('id')",       # import
    "open('/etc/passwd')",                  # open 不在白名单函数
    "close.shift(-5)",                      # 属性调用
    "close.T",                              # 属性访问
    "close[0]",                             # 下标
    "Ref(close, -1)",                       # 未来函数
    "REF(close, -3)",                       # 未来函数（别名）
    "lambda x: x",                          # lambda
    "[x for x in close]",                   # 推导式
    "(x := close)",                         # 海象
    "f'{close}'",                           # f-string
    "'abc'",                                # 字符串常量
    "Foo(close)",                           # 未知函数
    "Mean(close, n=20)",                    # 关键字参数
    "close; volume",                        # 多语句（语法错误）
    "eval('1')",                            # eval 不在白名单
    "getattr(close, 'shift')",              # getattr 不在白名单
]


@pytest.mark.parametrize("expr", BAD_EXPRESSIONS)
def test_rejects_malicious(expr):
    assert ee.validate(expr), f"应拒绝: {expr}"
    with pytest.raises(ee.ExprError):
        ee._compile(expr)


def test_rejects_runtime_future_ref(df):
    """窗口参数经 params 传入负数 → 运行时拒绝。"""
    with pytest.raises(ee.ExprError):
        ee.compute(df, "Ref(close, n)", n=-1)


def test_rejects_oversized():
    expr = "+".join(["close"] * 300)
    assert any("过大" in p for p in ee.validate(expr))


def test_unknown_name_message(df):
    with pytest.raises(ee.ExprError, match="未知名称"):
        ee.compute(df, "close > nonexistent_param")


# ---------------------------------------------------------------- 参数与接口

def test_param_binding_and_bool(df):
    out = ee.compute(df, "close > th", th=20)
    assert out.dtype == bool
    assert (out == (df["close"] > 20)).all()


def test_param_field_conflict(df):
    with pytest.raises(ee.ExprError, match="冲突"):
        ee.compute(df, "close > 1", close=1)


def test_dollar_syntax(df):
    _close(ee.compute(df, "$close / Ref($close, 1)"),
           df["close"] / df["close"].shift(1))


def test_vwap_from_amount(df):
    _close(ee.compute(df, "vwap"), df["amount"] / df["volume"])


def test_constant_expression_broadcast(df):
    out = ee.compute(df, "1 + 1")
    assert len(out) == len(df) and (out == 2).all()


def test_boolop_and_chained_compare(df):
    out = ee.compute(df, "close > 20 and volume > 0 or not (close > 19)")
    assert out.dtype == bool
    ch = ee.compute(df, "19 < close < 21")
    assert (ch == ((df["close"] > 19) & (df["close"] < 21))).all()


def test_ifexp_and_if(df):
    a = ee.compute(df, "1 if close > Mean(close,5) else -1")
    b = ee.compute(df, "If(close > Mean(close,5), 1, -1)")
    assert (a.fillna(0) == b.fillna(0)).all()


# ---------------------------------------------------------------- 注册表

def test_registry_roundtrip(df, tmp_path, monkeypatch):
    monkeypatch.setattr(ee, "EXPRESSIONS_FILE", tmp_path / "expressions.json")
    r = ee.register_expression(
        "TEST_ZSCORE20", "(close - Mean(close, 20)) / Std(close, 20)",
        description="20日zscore")
    assert r["ok"], r["message"]
    out = ee.compute_registered("TEST_ZSCORE20", df)
    _close(out, (df["close"] - df["close"].rolling(20).mean())
           / df["close"].rolling(20).std())

    # cast bool + 参数默认值 + 覆盖
    r = ee.register_expression("TEST_JLOW", "close < th",
                               params={"th": 20}, cast="bool")
    assert r["ok"]
    out = ee.compute_registered("TEST_JLOW", df)
    assert out.dtype == bool and (out == (df["close"] < 20)).all()
    out2 = ee.compute_registered("TEST_JLOW", df, th=25)
    assert (out2 == (df["close"] < 25)).all()


def test_register_rejects_bad(tmp_path, monkeypatch):
    monkeypatch.setattr(ee, "EXPRESSIONS_FILE", tmp_path / "expressions.json")
    r = ee.register_expression("BAD", "Ref(close, -1)")
    assert not r["ok"] and "未来函数" in r["message"]
    assert not ee.load_expression_registry()


def test_factor_registry_fallback(df, tmp_path, monkeypatch):
    monkeypatch.setattr(ee, "EXPRESSIONS_FILE", tmp_path / "expressions.json")
    ee.register_expression("EXPR_MOMENTUM5", "close / Ref(close, 5) - 1")
    from alphapulse.factors.factor_registry import compute_factor
    out = compute_factor("EXPR_MOMENTUM5", df)
    _close(out, df["close"] / df["close"].shift(5) - 1)
    with pytest.raises(ValueError, match="未知因子"):
        compute_factor("NOT_EXIST_ANYWHERE", df)


# ---------------------------------------------------------------- Alpha158（验收#2本地部分）

def test_alpha158_inventory():
    assert len(ALPHA158) == 158
    for name, expr in ALPHA158.items():
        assert not ee.validate(expr), f"{name} 表达式非法: {expr}"


def test_alpha158_full_compute(df):
    frame = compute_alpha158(df)
    assert frame.shape == (len(df), 158)
    warm = frame.iloc[120:]
    finite = warm.notna().mean()
    low = finite[finite < 0.9]
    assert low.empty, f"NaN过多: {low.to_dict()}"
    assert not np.isinf(warm.to_numpy()).any(), "存在inf"


def test_alpha158_causality(df):
    """截断因果性：截掉尾部数据，前段每个因子值必须逐点不变（未来函数=致命）。

    这是防止未来数据泄漏最强的回归锚——任何算子若窥探了 t 之后的数据，
    截断后前段的值就会变化。含 volume=0（停牌样）极端样本。
    """
    d = df.copy()
    d.loc[50, "volume"] = 0.0
    d.loc[51, "volume"] = 0.0
    cut = 300
    full = compute_alpha158(d)
    part = compute_alpha158(d.iloc[:cut])
    for col in ALPHA158:
        a = full[col].iloc[:cut].to_numpy(dtype=float)
        b = part[col].to_numpy(dtype=float)
        # NaN 掩码必须一致（截断不应改变有值/无值的位置）
        na, nb = np.isnan(a), np.isnan(b)
        assert (na == nb).all(), f"{col}: NaN掩码因截断而变化（结构性未来泄漏）"
        m = ~na
        assert np.allclose(a[m], b[m], atol=1e-9, rtol=1e-6), \
            f"{col}: 截断改变前段值 maxdiff={np.max(np.abs(a[m]-b[m])):.3e}（未来函数）"


def test_operator_causality(df):
    """逐算子截断因果性。"""
    ops = ["Mean(close,20)", "Std(close,20)", "Max(high,20)", "Min(low,20)",
           "Mad(close,20)", "Skew(close,30)", "Quantile(close,20,0.7)",
           "Rank(close,20)", "IdxMax(high,20)", "IdxMin(low,20)",
           "Count(close>Ref(close,1),10)", "Slope(close,10)", "Rsquare(close,10)",
           "Resi(close,10)", "Corr(close,volume,20)", "Cov(close,volume,20)",
           "EMA(close,10)", "WMA(close,10)", "SMA(close,5,2)", "Delta(close,5)",
           "Cross(EMA(close,5), EMA(close,20))"]
    cut = 200
    for op in ops:
        a = ee.compute(df, op).iloc[:cut].to_numpy(dtype=float)
        b = ee.compute(df.iloc[:cut], op).to_numpy(dtype=float)
        m = ~(np.isnan(a) | np.isnan(b))
        assert np.allclose(a[m], b[m], atol=1e-9, rtol=1e-6), f"{op} 非因果"


def test_sandbox_escape_matrix(df):
    """沙箱逃逸攻击矩阵：属性/魔术方法/内省/内建全部拦截。"""
    escapes = [
        "__import__('os').system('echo pwned')",
        "().__class__.__bases__[0].__subclasses__()",
        "close.__class__", "close.values", "close.__reduce__()",
        "getattr(close,'to_csv')('/x')", "close.rolling(5).apply(__import__)",
        "[].append(1)", "{1:2}[1]", "type(close)", "globals()", "vars()",
        "close.shift(-1)", "exec('x=1')", "eval('1')", "compile('1','','eval')",
        "close.map(print)", "open('/etc/passwd')", "Ref(close, -(1))",
    ]
    for e in escapes:
        with pytest.raises(ee.ExprError):
            ee.compute(df, e)


def test_alpha158_no_inf(df):
    """Alpha158 全部有 1e-12 分母保护，暖机后不应出现 inf。"""
    d = df.copy()
    d.loc[50, "volume"] = 0.0  # 零成交量不应产生 inf
    warm = compute_alpha158(d).iloc[120:]
    assert not np.isinf(warm.to_numpy()).any()


def test_alpha158_spotchecks(df):
    frame = compute_alpha158(df, names=["KMID", "ROC5", "MA20", "RSV10", "RANK20"])
    c = df["close"]
    _close(frame["KMID"], (c - df["open"]) / df["open"])
    _close(frame["ROC5"], c.shift(5) / c)
    _close(frame["MA20"], c.rolling(20).mean() / c)
    rsv = ((c - df["low"].rolling(10).min())
           / (df["high"].rolling(10).max() - df["low"].rolling(10).min() + 1e-12))
    _close(frame["RSV10"], rsv)
    _close(frame["RANK20"], c.rolling(20).rank(pct=True))
