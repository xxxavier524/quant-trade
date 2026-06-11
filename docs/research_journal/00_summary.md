# 开源量化项目精读汇总与集成路线图

> 研究日期：2026-06-11 | 对应笔记：02~07 | 评估基准：用户A股短线底部挖掘体系（B1/B2/B3、知行白黄线、红肥绿瘦量能、单针下三十、砖型图、S1卖点、0-100评分+LGBM胜率+相似度搜索+信号闭环）

## 一、横向对比表

| 项目 | Star | 活跃度 | 定位 | 与用户逻辑契合度 | 核心可取物 | 集成成本 |
|---|---|---|---|---|---|---|
| [microsoft/qlib](https://github.com/microsoft/qlib)（笔记02） | ~37k | 高 | AI量化全栈平台 | ★★★★☆ | 因子表达式DSL、Alpha158、CSRankNorm标签 | 低（只取思想，不装框架） |
| [Vespa314/chan.py](https://github.com/Vespa314/chan.py)（笔记03） | ~1.5k | 中高 | 缠论形态学+买卖点+ML过滤 | ★★★★★ | 信号链状态机、MACD背驰量化、K线合并、信号点特征 | 中 |
| [myhhub/stock](https://github.com/myhhub/stock)（笔记04） | ~6.5k | 高 | A股全流程选股系统 | ★★★★☆ | 筹码分布CYQ、多周期持有验证矩阵 | 中 |
| [sngyai/Sequoia-X](https://github.com/sngyai/Sequoia-X)（笔记05） | ~4.3k | 高 | A股短线形态扫描（baostock同源） | ★★★★☆ | RPS相对强度、洗盘段量化模板、防诱多过滤 | 低 |
| [bbfamily/abu](https://github.com/bbfamily/abu)（笔记06） | ~17.4k | 停更(2019) | 多市场量化+UMP裁判 | ★★★★★ | UMP失败模式聚类否决、趋势角度特征族 | 中（仅移植思想） |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund)（笔记07） | ~50k | 高 | 多Agent LLM投研 | ★★★☆ | 统一信号协议、多视角辩论+元决策、Hurst/ADX | 低 |
| AI4Finance/FinRL（落选） | ~15k | 高 | 强化学习交易 | ★★ | — | 高（范式冲突，不取） |

**主题归纳**：六个项目对我们的价值集中在四条线——
1. **因子生产线**（qlib表达式引擎 → DeepSeek生成因子的可靠载体）
2. **战法状态机与形态学**（chan.py信号链 + Sequoia洗盘模板 + InStock筹码 → B1B2B3体系增强）
3. **防守型ML**（abu UMP否决 + chan.py信号点特征 → LGBM胜率模型升维）
4. **AI研判编排**（ai-hedge-fund多Agent协议 → DeepSeek研判升级）

## 二、按价值排序的集成路线图

| # | 任务 | 来源项目 | 预期收益 | 回测验证方法 | 工作量 |
|---|---|---|---|---|---|
| 1 | **RPS相对强度过滤因子**（`factors/rps.py`，B1加RPS120下限） | Sequoia-X | 剔除"弱者恒弱"假底，B1精确率直接提升；半天出活 | 现有胜率验证器AB对比：B1 vs B1+RPS≥{40,50,60,70}，看N日胜率/盈亏比变化 | 0.5天 |
| 2 | **UMP失败模式裁判**（`strategies/ump_referee.py`：GMM聚类历史失败信号→否决新信号）+ 趋势角度特征族 | abu | 防守型ML，可解释拦截（指认相似失败案例）；与LGBM互补 | 信号闭环历史数据训练，时间外推验证：拦截后剩余信号胜率应显著高于全量；统计误杀率 | 3天 |
| 3 | **迷你因子表达式引擎**（`factors/expr_engine.py`，ast白名单解析；DeepSeek改输出表达式） | qlib | 新因子成本从"写.py"降为"一行字符串"；DeepSeek生成可靠性大幅提升；附送Alpha158因子库 | tests/golden/ 对拍知行公式；Alpha158批量算IC，入LGBM前后AUC对比 | 3天 |
| 4 | **信号链状态机改造**（B2引用B1、B3引用B2，seq_id贯穿；evening_review按序列统计） | chan.py | 完整B1→B2→B3序列胜率 vs 孤立信号胜率可量化；S1卖点可归因 | 闭环表回放：按seq_id聚合，验证"94.7%胜率"在序列维度是否保持 | 2天 |
| 5 | **筹码分布因子**（`factors/chip_distribution.py`：获利盘比例/单峰密集度） | InStock | 给"底部挖掘"补上持仓成本维度：低位单峰+获利盘<15%确认真底 | 与通达信筹码图抽查对拍；B1+筹码条件 vs 纯B1 胜率网格对比 | 3天 |
| 6 | **洗盘段量化模板**（锚定位+量能上限，统一服务B3锁仓与单针下三十） | Sequoia-X | 把"缩量阴/3/4阴量线"语义参数化，可网格搜索 | max_vol_ratio∈{0.4,0.5,0.6,0.75}网格，B3持有收益对比 | 1天 |
| 7 | **MACD面积背驰因子**（DD卖点量化，divergence_rate参数化） | chan.py | S1卖点体系中DD从经验判断变为可回测参数 | 持仓模拟：DD触发卖出 vs 原S1规则，对比回撤与收益 | 1天 |
| 8 | **统一信号协议+置信度加权聚合**（SignalOpinion：规则/LGBM/LLM/UMP归一，死区阈值） | ai-hedge-fund | 0-100评分、LGBM、AI研判三套输出打通，排序逻辑单一化 | 聚合分数 vs 原0-100分数的Top-N组合回测对比（vnpy管线） | 2天 |
| 9 | **DeepSeek研判委员会**（3个知行体系persona并行+组合经理元决策，风控官专职唱反调） | ai-hedge-fund | 研判从单口径变为结构化多空对辩，暴露盲点 | 人工抽检30例 + 委员会confidence与实际胜率的校准曲线 | 2天 |
| 10 | **K线包含关系合并预处理**（N_STRUCT/单针/砖型统一用合并K线） | chan.py | 形态识别去毛刺，降低横盘误报 | 三个形态因子合并前后误报率/胜率对比 | 2天 |
| 11 | **多周期持有验证矩阵**（evening_review输出N∈{1..20}日收益矩阵） | InStock | 用数据定B3最优锁仓天数 | 闭环表直接聚合，无需新回测 | 1天 |
| 12 | **CSRankNorm标签 + Hurst战法分流 + 增量数据/推送**（杂项增强包） | qlib / ai-hedge-fund / Sequoia-X | LGBM标签去beta污染；按Hurst分流B1与砖型；数据更新提速+飞书推送 | LGBM重训AUC对比；分流前后各战法胜率 | 2天 |

总计约 22.5 人天。建议按 1→2→3 先做（合计一周内），三项都不动现有策略代码主干、纯增量、且各自有独立AB验证口径。

## 三、明确不做清单（避免范式漂移）

- **FinRL/强化学习端到端调仓**：黑箱与规则化买点体系冲突，A股短线可解释性要求高
- **Qlib全框架/缠论全体系/InStock的MySQL+Web/LangGraph**：基础设施重复建设
- **abu代码本体**（GPL+停更，只取算法思想）、**美股大师人格prompt**、**东财抓取层**（已封）
- **右侧追涨买点**（海龟/RPS突破作为独立买点）：与底部挖掘风格冲突，只作过滤器部件
