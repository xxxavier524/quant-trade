# 精读笔记 07：virattt/ai-hedge-fund — 多Agent LLM投研

> 研究日期：2026-06-11 | 研究目的：为 DeepSeek AI研判模块借鉴多Agent辩论与信号聚合架构

## 一、项目卡片

| 项 | 内容 |
|---|---|
| 地址 | https://github.com/virattt/ai-hedge-fund |
| Star | ~50k（GitHub上最热的AI金融项目） |
| 语言 | Python（Poetry管理），LangGraph 编排，支持 OpenAI/Ollama 本地LLM |
| 最近更新 | 活跃（已出 v2 目录与 Web app） |
| 定位 | 教育用途的多Agent对冲基金仿真：约14个"投资大师人格"Agent + 5个功能Agent，辩论后由组合经理出最终决策 |
| 选择理由 | 我们已有 DeepSeek AI研判（单次调用式）；该项目展示了"人格化多视角 + 量化功能Agent + 风险/组合两级闸门"的成熟编排范式，且其 technicals.py 是一份高质量纯量化信号聚合参考实现 |

## 二、核心架构与关键模块精读

### 2.1 Agent 编排（LangGraph DAG）

```
[数据获取]
   → 并行: 14个投资大师Agent (Buffett/Munger/Burry/Wood/Lynch/Graham/Druckenmiller...)
   → 并行: 功能Agent: valuation / sentiment / fundamentals / technicals
   → risk_manager (风险经理: 仓位上限、风险度量)
   → portfolio_manager (组合经理: 汇总所有signal+confidence+reasoning, LLM做最终buy/sell/hold+数量)
```

每个Agent输出统一三元组：`{signal: bullish|bearish|neutral, confidence: 0-100, reasoning: str}`。**组合经理不重新分析原始数据，只对Agent意见做元决策**——分层避免了单prompt塞爆上下文。

### 2.2 technicals.py 精读（无LLM，纯量化，质量很高）

`technical_analyst_agent()` 内置五策略，各自产出 signal+confidence：

| 策略 | 函数 | 指标与逻辑 | 置信度 |
|---|---|---|---|
| 趋势 | `calculate_trend_signals` | EMA8>EMA21>EMA55 多头排列 + ADX强度 | ADX/100 |
| 均值回归 | `calculate_mean_reversion_signals` | 50日z-score与布林位置：z<-2且贴下轨→bullish | min(\|z\|/4,1) |
| 动量 | `calculate_momentum_signals` | 1/3/6月收益 + 量能确认，>5%→bullish | min(\|mom\|×5,1) |
| 波动率 | `calculate_volatility_signals` | 21日年化波动 vs 其均值的体制比 + z-score | 体制偏离度 |
| 统计套利 | `calculate_stat_arb_signals` | Hurst指数<0.4(均值回归性) + 63日偏度方向 | (0.5-H)×2 |

聚合 `weighted_signal_combination`：权重 趋势0.25/动量0.25/均值回归0.20/波动0.15/统套0.15，加权和（按各自confidence加权）÷ 总置信度，**±0.2阈值** 输出最终 bullish/bearish/neutral。

### 2.3 风险经理与组合经理

risk_manager 计算各标的仓位上限（如单票占比限制），portfolio_manager 接收"全部Agent信号 + 风险约束 + 当前持仓"，由LLM产出带数量的订单建议。**两级闸门：观点(信号层) 与 钱(仓位层) 分离**。

## 三、亮点技术拆解

### 亮点1：signal+confidence+reasoning 统一信号协议

所有异构分析（LLM人格、量化策略、情绪、估值）归一到同一协议，下游聚合器不关心来源。confidence 不是装饰——聚合时按置信度加权，低置信意见自动边缘化。**这是多源信号系统的最佳实践**：我们的 0-100 评分、LGBM 概率、DeepSeek 研判文本目前是三套不可互通的输出。

### 亮点2：人格化prompt产生"结构性分歧"

每个大师Agent的prompt固化其投资哲学（Burry找深度价值+做空泡沫，Wood找颠覆成长），同一份数据得出**有立场的不同结论**，组合经理见到的是结构化的多空对辩而非单一口径。对研判类LLM应用，**制造受控分歧比追求单次"正确"更能暴露风险盲点**。

### 亮点3：置信度加权 + 死区阈值聚合

`final = Σ(signal_i × conf_i × w_i) / Σ(conf_i × w_i)`，|final|<0.2 输出 neutral。死区设计防止微弱倾向被放大成交易动作——比简单投票或平均稳健。

## 四、与用户选股逻辑的契合点

| 用户逻辑 | ai-hedge-fund对应物 | 契合度 |
|---|---|---|
| DeepSeek AI研判 | 多Agent辩论+组合经理元决策范式 | ★★★★★ |
| 0-100加权评分 | confidence加权聚合公式（数学上同族，但其带死区与置信度二阶权重） | ★★★★ |
| S1卖出/仓位管理 | risk_manager 与 portfolio_manager 两级闸门 | ★★★ |
| B1等规则买点 | technicals.py 仅是通用指标，无A股短线战法 | ★★ |
| 形态相似度搜索 | 无 | ☆ |

注意：该项目面向美股基本面数据（financialdatasets API），数据层对A股不可用，**取架构不取数据与大师人格本身**。

## 五、取精华建议

### 建议1：AI研判升级为"多视角辩论 + 元决策"两段式（最优先）

把现有 DeepSeek 单次研判改造为 `alphapulse/llm/committee.py`：

```python
PERSONAS = {
  "trend_hunter":  "你是趋势主力行为分析师，只关心量能与主力意图……",
  "risk_officer":  "你是空头风控官，专找该信号失败的理由（假底/中继/出货）……",
  "zhixing_master":"你是知行体系老手，严格按白黄线/红肥绿瘦/B1B2B3评估……",
}
def run_committee(signal_ctx: dict) -> dict:
    # 1. 并行3次 deepseek-v4-flash 调用，各persona输出
    #    {signal, confidence, reasoning}（JSON模式强制）
    # 2. 一次 deepseek-v4-pro 做组合经理: 输入三方意见+UMP裁判结果+LGBM胜率
    #    输出 {action, confidence, key_risk, reasoning}
```

要点：风控官persona**专职唱反调**（结构性分歧），与UMP裁判（笔记06）一票否决机制互补。工作量：**2天**（已有DeepSeek管线，主要是prompt工程与JSON schema约束）。

### 建议2：统一信号协议 `SignalOpinion`

```python
@dataclass
class SignalOpinion:
    source: str          # 'rule:B1' | 'ml:lgbm' | 'llm:risk_officer' | 'ump:main_deg'
    signal: float        # -1..+1
    confidence: float    # 0..1
    reasoning: str
def aggregate(opinions, weights, deadzone=0.2) -> float:
    """Σ(sig*conf*w)/Σ(conf*w)，|x|<deadzone → 0"""
```

0-100评分、LGBM概率、研判委员会、UMP全部适配为该协议后聚合，最终分数=每日排序依据；权重进网格搜索。工作量：**1~2天**（主要是改造现有评分器的输出格式）。

### 建议3：移植 technicals.py 三个我们缺失的量化件

- Hurst指数（63日）：判定个股当前"趋势性vs均值回归性"，B1（回归逻辑）适合低Hurst环境、砖型突破（趋势逻辑）适合高Hurst——**按Hurst给战法分流**
- ADX置信度：B2确认信号附带 ADX/100 趋势强度置信
- 波动率体制(vol/vol_MA)：高波动体制下自动调低仓位建议（接 risk_monitor）

工作量：**1天**（纯pandas移植）。

## 六、不取的部分及原因

- **14个投资大师人格**：巴菲特/伯里prompt面向美股基本面长线，对A股短线量价战法无意义；只取"人格化分歧"方法论，人格自定义为知行体系角色
- **financialdatasets数据层 / app前端 / LangGraph依赖**：数据不覆盖A股；我们Streamlit已有；编排用朴素asyncio即可，不引入LangGraph
- **LLM直接决定下单数量**：实盘资金交给LLM输出数量风险不可控，仓位仍由规则（单票≤20%、最多5只）硬约束
- **回测器**：其回测简陋，远不如我们vnpy管线
