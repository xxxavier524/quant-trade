# 精读笔记 02：Microsoft Qlib — AI量化平台

> 研究日期：2026-06-11 | 研究目的：为 AlphaPulse-A 寻找因子工程与ML工作流的可借鉴架构

## 一、项目卡片

| 项 | 内容 |
|---|---|
| 地址 | https://github.com/microsoft/qlib |
| Star | ~37k+（2026年仍在增长，量化类第一梯队） |
| 语言 | Python（核心计算含Cython加速） |
| 最近更新 | 2026-02（活跃，并已接入 RD-Agent 自动化研发） |
| 定位 | AI-first 量化研究全栈平台：数据→因子→模型→回测→组合执行 |
| 选择理由 | 工业级因子表达式引擎 + LightGBM基准工作流，与我们已有的 LightGBM 胜率模型和 452 alpha 桥接直接互补 |

## 二、核心架构与关键模块精读

### 2.1 表达式引擎（最核心的资产）

Qlib 的因子不是函数，而是**字符串表达式**，由 `qlib/data/ops.py` 中注册的算子树解析执行：

- 基础数据引用：`$open / $close / $high / $low / $volume / $vwap`
- 时序算子：`Ref(x, n)`（n日前取值）、`Mean/Std/Max/Min/Sum(x, n)`、`Slope/Rsquare/Resi(x, n)`（滚动回归）、`Quantile/Rank/IdxMax/IdxMin`
- 截面与逻辑：`Greater/Less/Abs/Log`、`Corr(x, y, n)`

示例（`qlib/contrib/data/loader.py` 中 `Alpha158DL.get_feature_config()`）：

```python
"KMID":  "($close-$open)/$open"                 # K线实体相对幅度
"KLEN":  "($high-$low)/$open"                   # 振幅（即用户B1的振幅<9%条件）
"KSFT":  "(2*$close-$high-$low)/$open"          # 收盘位置偏移（影线结构）
"RSV":   "($close-Min($low,5))/(Max($high,5)-Min($low,5)+1e-12)"  # KDJ的RSV原型
"CORR":  "Corr($close, Log($volume+1), 5)"      # 量价相关性
"SUMP":  "Sum(Greater($close-Ref($close,1),0),5)/(Sum(Abs($close-Ref($close,1)),5)+1e-12)"  # 涨日动量占比
```

### 2.2 Alpha158 因子库的结构化分类

`Alpha158DL` 按四类生成158个因子，每类带 `windows` 参数（默认 [5,10,20,30,60]）：

1. **kbar 类（9个）**：单根K线形态学（实体、上下影、收盘位置）——硬编码表达式
2. **price 类**：`Ref($open, w)/$close` 形式的历史价格归一化
3. **volume 类**：`Ref($volume, w)/($volume+1e-12)` 量能时序结构
4. **rolling 类（23种算子 × 5窗口）**：ROC/MA/STD/BETA/RSQR/RESI/MAX/MIN/QTLU/QTLD/RANK/RSV/IMAX/IMIN/CORR/CORD/CNTP/CNTN/SUMP/SUMN/VMA/VSTD/WVMA 等

**关键设计思想：所有因子都除以 `$close` 或自身均值做归一化**，保证截面可比——这是我们 0-100 加权评分体系目前缺失的严谨性来源。

### 2.3 ML工作流（workflow/qrun）

`qlib/contrib/model/gbdt.py`（LGBModel）+ `DataHandlerLP`（含 `learn_processors`：DropnaLabel、CSRankNorm 截面排序归一化）+ `SignalRecord/PortAnaRecord` 回测记录器，整条链路由一个 YAML 驱动。标签定义同样是表达式：`Ref($close, -2)/Ref($close, -1) - 1`（避开T+1的未来收益标签）。

## 三、亮点技术拆解

### 亮点1：字符串因子表达式引擎（DSL）

原理：表达式解析为算子树，每个算子实现 `load(instrument, start, end, freq)`，叶子节点读取原始数据，中间节点做滚动计算并自动处理 NaN 与窗口对齐。好处：
- 新因子=一行字符串，不用写 `compute(df)` 样板代码
- 可被 LLM 生成与校验（与我们 DeepSeek NL→因子管线天然契合：DeepSeek 输出表达式字符串而非完整 Python 文件，可靠性高一个数量级）
- 表达式可哈希→因子缓存、去重、相关性矩阵自动化

### 亮点2：CSRankNorm 截面标签归一化

训练 LightGBM 时不用原始收益率做标签，而是把每个截面（每天）的收益率转成排名分位再标准化。消除市场整体涨跌（beta）对标签的污染，模型学到的是"当天谁比谁强"——短线选股恰好是截面排序问题。

### 亮点3：标签时移防泄漏约定

`Ref($close, -2)/Ref($close, -1) - 1`：信号日收盘后出信号，T+1开盘/收盘才能买入，所以收益从 T+1 起算。A股 T+1 制度下这是必须的，我们的信号追踪闭环可直接采用此约定核对。

## 四、与用户选股逻辑的契合点

| 用户逻辑 | Qlib对应物 | 契合度 |
|---|---|---|
| B1买点（涨幅±3%+振幅<9%+J<13...） | 全部条件可写成表达式组合，如振幅 `($high-$low)/Ref($close,1) < 0.09` | ★★★★★ |
| 知行白线 EMA(EMA(C,10),10) | `EMA(EMA($close,10),10)`（EMA算子需确认/自定义注册） | ★★★★ |
| 红肥绿瘦量能比 | `Sum(If($close>$open,$volume,0),20)/Sum(If($close<$open,$volume,0),20)` 类表达式 | ★★★★★ |
| 0-100加权评分 | Alpha158→LGBM预测分，替代手工加权 | ★★★★ |
| LightGBM胜率模型 | LGBModel + CSRankNorm 整套训练规范 | ★★★★★ |
| 形态相似度搜索 | 无直接对应 | ☆ |

## 五、取精华建议

### 建议1：实现迷你表达式引擎 `alphapulse/factors/expr_engine.py`（核心收益最大）

不引入 Qlib 全框架（其数据格式 .bin + 初始化太重），只移植表达式 DSL 思路：

```python
# 接口设计
OPS = {
    "Ref":  lambda s, n: s.shift(n),
    "Mean": lambda s, n: s.rolling(n).mean(),
    "Std":  lambda s, n: s.rolling(n).std(),
    "Max":  lambda s, n: s.rolling(n).max(),
    "Min":  lambda s, n: s.rolling(n).min(),
    "EMA":  lambda s, n: s.ewm(span=n, adjust=False).mean(),
    "Corr": lambda a, b, n: a.rolling(n).corr(b),
    "Sum":  lambda s, n: s.rolling(n).sum(),
    "If":   lambda c, a, b: a.where(c, b),
}

def eval_expr(expr: str, df: pd.DataFrame) -> pd.Series:
    """'($close-$open)/$open' -> Series；$xxx 映射到 df 列。
    用 ast.parse 解析（白名单算子，禁止任意代码执行），递归求值。"""

# 注册到 factor_registry：
register_factor("KMID", expr="($close-$open)/$open")
register_factor("ZHIXING_WHITE", expr="EMA(EMA($close,10),10)")
register_factor("ZHIXING_YELLOW", expr="(Mean($close,14)+Mean($close,28)+Mean($close,57)+Mean($close,114))/4")
register_factor("B1_AMP", expr="($high-$low)/Ref($close,1)")
```

- DeepSeek NL→因子管线改为输出表达式字符串，`eval_expr` 直接执行，无需生成整个 .py
- 工作量：**2~3天**（含 ast 白名单安全解析 + 对拍 tests/golden/ 知行公式）

### 建议2：移植 Alpha158 的 kbar+rolling 因子到评分体系

把158个表达式按上面引擎批量注册，与现有452 alpha合并后做 IC 筛选，喂给 LightGBM 胜率模型扩充特征。工作量：**1天**（表达式表是现成的，loader.py 里直接抄）。

### 建议3：训练标签改造为 CSRankNorm

`alphapulse/utils/backtest_utils.py` 增加 `cs_rank_norm(label_df)`：每日截面 rank→zscore。LGBM 胜率模型重训一次对比 AUC。工作量：**0.5天**。

## 六、不取的部分及原因

- **Qlib 全框架/qrun**：依赖自有 .bin 数据格式与 provider 初始化，和我们 baostock→CSV 管线冲突，迁移成本 > 收益
- **NestedExecutor 嵌套执行器/高频部分**：做日内拆单模拟，我们是日线短线，用不上
- **RL（QlibRL）与市场动态建模**：范式与规则化买点体系不符，可解释性差
- **RD-Agent 自动研发**：依赖其全家桶，我们已有 DeepSeek 管线，取其"表达式即因子"思想即可
