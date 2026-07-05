# 迷你因子表达式引擎设计（路线图#3）

> 日期：2026-07-06 | 来源：docs/research_journal/00_summary.md 路线图#3（qlib 笔记02）
> 目标：新因子成本从"写 .py"降为"一行字符串"；DeepSeek 生成因子的可靠载体；附送 Alpha158 因子库

## 1. 问题与目标

现状：每个新因子要写一个 `compute(data)->Series` 的 .py 文件，经 AST 白名单 + 沙箱 exec
校验（`llm/factor_gen.py`）。生成代码自由度大 → DeepSeek 输出不稳定、校验面大、复查成本高。

目标：因子 = 一行表达式字符串，如：

```
(close - Mean(close, 20)) / Std(close, 20)
EMA(EMA(close, 10), 10) > (MA(close,14)+MA(close,28)+MA(close,57)+MA(close,114))/4
Corr(close, Log(volume+1), 10)
```

- DeepSeek 只需输出表达式（受限 DSL，幻觉面大幅收窄）
- 表达式天然可网格搜索（数值参数以名字引用，运行时绑定）
- 附送 qlib Alpha158 因子库（158 个表达式，直接入 LGBM/IC 管线）

## 2. 方案选型

| 方案 | 说明 | 结论 |
|---|---|---|
| **A. AST 解释器（选定）** | `ast.parse(mode="eval")` + 节点白名单 + 树遍历求值，算子全部向量化 pandas | 全程无 exec/eval，无沙箱逃逸面；表达式可缓存；错误信息可控（利于 LLM 重试） |
| B. 转译 Python + 沙箱 exec | 复用 factor_gen 现有模式 | 多一层 exec 攻击面，能力不比 A 强，弃 |
| C. 引入 qlib 框架 | 直接用 qlib Expression | 路线图"明确不做清单"已否决（基础设施重复建设） |

## 3. 架构

### 3.1 `alphapulse/factors/expr_engine.py`（核心，无新依赖）

```
validate(expr) -> list[str]          # 问题列表（空=通过），LLM 反馈友好
compile_expr(expr) -> ExprFactor     # 解析+校验+缓存（lru_cache）
compute(data, expr, **params) -> pd.Series   # 注册表兼容入口
smoke_test(expr, params) -> (ok, msg)        # 随机 OHLCV 冒烟
register_expression(name, expr, ...) -> dict # 校验+冒烟+落盘 expressions.json
compute_registered(name, data, **params)     # 按名计算已注册表达式
```

**求值模型**：单股时间序列（与全项目 `compute(df)->Series` 口径一致；截面 rank 类
面板因子仍走 `zoo_bridge`，不在本引擎范围）。

**字段**：`open, high, low, close, volume, amount, turnover, market_cap, vwap`
（vwap = amount/volume，缺 amount 时 (high+low+close)/3）。兼容 qlib 的 `$close`
写法（预处理剥掉 `$`）。

**白名单 AST 节点**：Expression / BinOp(+,-,*,/,**,%) / UnaryOp(-,+,~) /
Compare(>,<,>=,<=,==,!=) / BoolOp(and,or→逐元素 &,|) / BitAnd,BitOr,BitXor /
IfExp(x if c else y → np.where) / Call(仅白名单函数名) / Name / Constant(数值,bool)。
**禁**：Attribute（无属性访问=无逃逸）、下标、lambda、推导式、f-string、海象等一切其余节点。
上限：≤500 节点、深度≤40。

**算子表**（全部因果、向量化；qlib 名为主 + 通达信别名）：

| 类别 | 算子 |
|---|---|
| 时序引用 | `Ref(x,n)`(n≥0，负数拒绝=防未来函数)、`Delta(x,n)` |
| 滚动统计 | `Mean/MA`、`Sum`、`Std`、`Var`、`Max/HHV`、`Min/LLV`、`Med`、`Mad`、`Skew`、`Kurt`、`Quantile(x,n,q)`、`Rank(x,n)`(时序分位)、`IdxMax/IdxMin`(距今bar数)、`Count(cond,n)` |
| 回归 | `Slope(x,n)`、`Rsquare(x,n)`、`Resi(x,n)`（x 对 t 的滚动 OLS） |
| 双序列 | `Corr(x,y,n)`、`Cov(x,y,n)` |
| 平滑 | `EMA(x,n)`(span)、`WMA(x,n)`、`SMA(x,n,m)`(通达信=ewm(alpha=m/n)) |
| 逐元素 | `Abs`、`Log`、`Sign`、`Sqrt`、`Power`、`Greater(a,b)`、`Less(a,b)`(成对max/min)、`If(cond,a,b)`、`Cross(a,b)`(通达信CROSS) |

**歧义规避**：`Max/Min/HHV/LLV` 固定为滚动窗口语义（第二参=窗口）；成对逐元素
max/min 只叫 `Greater/Less`（qlib 惯例）。不注册通达信 `MAX/MIN` 别名，防止静默错义。

**参数绑定**：求值环境 = df 字段 ∪ params。表达式中未识别的 Name 先查 params
（如 `j < j_threshold`），查不到报错并列出可用名。窗口参数须为正整数（常量或参数）。

**NaN 策略**：原样保留（与现有因子模块一致）；注册表达式可声明 `cast: bool`
（`fillna(False).astype(bool)`，选股信号用）。

### 3.2 `alphapulse/factors/alpha158.py`

qlib Alpha158 全套表达式常量 `ALPHA158: dict[str,str]`：
- KBAR 9 个（KMID/KLEN/KMID2/KUP/KUP2/KLOW/KLOW2/KSFT/KSFT2）
- 价格 4 个（OPEN0/HIGH0/LOW0/VWAP0 = 当日价/close）
- 滚动 29 算子 × 窗口 {5,10,20,30,60} = 145 个
  （ROC MA STD BETA RSQR RESI MAX MIN QTLU QTLD RANK RSV IMAX IMIN IMXD
   CORR CORD CNTP CNTN CNTD SUMP SUMN SUMD VMA VSTD WVMA VSUMP VSUMN VSUMD）

`compute_alpha158(df) -> DataFrame(158列)`，逐表达式经引擎求值。

### 3.3 注册表集成（最小侵入）

- 新文件 `alphapulse/factors/expressions.json`：`{name: {expr, description,
  params, cast, enabled, source}}`，与 `generated/registry.json` 平行。
- `factor_registry.compute_factor(name, ...)`：name 不在 FACTOR_REGISTRY 时兜底查
  表达式注册表；报错信息合并两边可用名。
- `llm/factor_gen.py` 新增 `generate_expression(description, name)`：
  DeepSeek 输出**表达式而非 .py**（新 system prompt：算子表 + 知行惯用语 + 少样例），
  `validate → smoke_test → expressions.json（enabled=False）`。校验失败时把问题列表
  回喂 LLM 重试一次。旧 .py 管线保留不动。

### 3.4 `scripts/alpha158_ic.py`

抽样 N 股（默认 600，seed 42）× 近 500 交易日 → 每股 `compute_alpha158` + fwd5 →
逐日截面 Spearman IC（复用 `ic_weight_tuning.daily_ic` 逻辑）→
`reports/alpha158_ic.md`（按 |meanIC| 排序全表 + Top20 摘要，标注候选入模因子）。

## 4. 验收标准（路线图原文）

1. **tests/golden 对拍知行公式**：白线 `EMA(EMA(close,10),10)`、黄线
   `(MA(close,14)+MA(close,28)+MA(close,57)+MA(close,114))/4`、洗盘四线
   `100*(close-LLV(low,n))/(HHV(close,n)-LLV(low,n))`、MACD DIF、KDJ J
   —— 表达式求值与现有模块（zhixing_trend/zhixing_washout/kdj_j_low）逐点 allclose。
2. **Alpha158 批量 IC**：158 因子在真实数据上全部跑通，产出 IC 报告。
3. 安全：import/属性访问/下标/`Ref(x,-n)`/未知函数/超深表达式全部拒绝且报错可读。
4. 现有测试（tests/golden、test_sub_scores 等）不回归。

LGBM 前后 AUC 对比（路线图提到的进阶验证）依赖重训管线，列为后续任务，
本期交付 IC 报告即可支撑筛选入模因子。

## 5. 测试

`tests/test_expr_engine.py`（合成随机游走数据，不依赖外接盘）：
- 每算子 vs pandas 参考实现逐点对拍
- 知行/MACD/KDJ 表达式 vs 现有模块（验收#1）
- 参数绑定、`$close` 兼容、bool cast、错误信息
- 恶意表达式拒绝矩阵（验收#3）
- ALPHA158 全量 parse+compute，长度/有限值比例断言

## 6. 边界与不做

- 不做截面（跨股票）算子——面板因子走 zoo_bridge
- 不做多周期重采样算子（周线因子沿用现有模块）
- 不改 `nlp_factor.py` 正则管线与既有 .py 生成管线
- 表达式注册的因子默认 `enabled=False`，经 validate_signal 验证后手动启用（与生成因子同规）
