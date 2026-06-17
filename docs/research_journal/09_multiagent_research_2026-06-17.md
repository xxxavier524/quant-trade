# 精读笔记 09：多 Agent 分工分析股票 — 横向调研与 AlphaPulse-A 落地设计

> 研究日期：2026-06-17 | 研究目的：为用户下一步"多 agent 分工分析股票的 agent team"提供可执行架构
> 调研对象：Qlib + RD-Agent、TradingAgents、HKUDS/AI-Trader、ai-hedge-fund、Anthropic financial-services、dexter、OpenBB、FinRobot、FinGPT
> 关联：本项目已有 `alphapulse/pipeline/`（6-Agent 因子 R&D 流水线）、journal 07（ai-hedge-fund 统一信号协议）、00_summary 集成路线图

---

## 1. 摘要

A 股多 agent 投研在 2025–2026 已从"单 prompt 推理"演进为"结构化多角色辩论 + 记忆反思 + 因子/模型联合优化"。本次九个项目可归为四类：

1. **多 agent 投研编排骨架**（TradingAgents 86.9k★、ai-hedge-fund 60.2k★）— 五阶段/多人格分工、Bull/Bear 辩论、LangGraph 状态机，工程落地价值最高，且原生支持 A 股代码（.SS/.SZ）与 DeepSeek 路由。
2. **LLM 驱动的自动因子工厂**（Qlib + RD-Agent）— 因子-模型联合优化、知识森林、Co-STEER 代码生成；CSI300 实测 IC=0.0532、ARR 14.21%、IR 1.74、MDD −7.42%，可喂养本项目 `factor_registry`。
3. **数据/技能基础设施**（OpenBB MCP、Anthropic financial-services 的 skills+connectors+subagents、dexter）— 多端数据总线、orchestrator-worker 模式、SOUL.md 投资哲学常驻。
4. **辅助模块**（FinRobot 报告生成、FinGPT 中文情绪因子）。

**关键结论**：本项目已具备完整的"规则因子层（B1/sub_scores）+ 状态机（B1→B2→B3 playbook）+ GBDT 胜率 + 板块/概念评分 + DeepSeek 研判 + 6-Agent 因子 R&D 流水线"。多 agent team **不应另起炉灶接入庞大外部框架**，而应**复用现有模块做 thin-wrapper**，以 TradingAgents 的五层分工与 ai-hedge-fund 的统一信号三元组为协作协议蓝本，自建一个轻量 `alphapulse/agent_team/`。MVP 可在 1–2 天内落地（无 LLM，纯量化聚合），第二阶段再叠加 DeepSeek 多空辩论。这条路线零框架依赖、零前视偏差风险、与现有 DeepSeek-v4-pro/flash 路由零冲突。

---

## 2. 逐项目分析（进展 / 优势 / 如何优化 AlphaPulse-A）

### 2.1 TauricResearch/TradingAgents — 86.9k★（首选骨架参考）

- **进展**：v0.1.0（2025-06）→ v0.2.5（2026-05-11）。8 个版本/年。v0.2.4 引入结构化输出决策 agent、LangGraph checkpoint 断点续跑、持久化决策日志 `TradingMemoryLog`、DeepSeek/Qwen/GLM/Bedrock 支持；v0.2.5 新增 grounded sentiment、区域基准指数（含上证/深证）、多语言报告。AAAI 2025 研讨会，arXiv:2412.20138 v7。
- **优势**：① 11 个专业 agent 完整覆盖投研链路（4 分析师并行 → 多空研究员辩论 → 交易员 → 3 风险经理 → 组合经理）；② **Bull/Bear 结构化辩论**强制交叉审视，系统性消除单边偏见，是相对单 agent 的核心差异；③ 双模型策略 `deep_think_llm`/`quick_think_llm` 与本项目 v4-pro/v4-flash 天然对应；④ 原生支持 .SS/.SZ，示例即 600519.SS；⑤ LangGraph 工厂模式，增删 agent 节点方便。
- **如何优化 AlphaPulse-A**：取其**五层分工拓扑**与**辩论协议**作为本项目 `agent_team` 的骨架蓝本（不直接装框架，避免 LangGraph + 大依赖）。把现有 `alphapulse/strategies/b1.py` 的 signal DataFrame 作为 TechnicalAnalyst 的输入上下文；`AggressiveRisk/Conservative/Neutral` 三视角风控可简化为单 RiskAgent 注入 A 股硬约束。
- 来源：https://github.com/TauricResearch/TradingAgents ｜ https://arxiv.org/abs/2412.20138 ｜ https://tauricresearch.github.io/TradingAgents/

### 2.2 virattt/ai-hedge-fund — 60.2k★（最易二开 + 统一信号协议）

- **进展**：2026-06-17 仍有发布（852 commits）。Web 应用（Python 后端 + TS 前端），19 个 agent（13 投资大师人格 + 6 功能 agent），支持 OpenAI/Groq/Anthropic/DeepSeek/Ollama，内置回测。
- **优势**：① 已在 journal 07 精读，**统一信号三元组 `{signal: bullish|bearish|neutral, confidence: 0-100, reasoning: str}`** 是最简洁可复用的 agent 间协议；② 组合经理只做元决策（不重读原始数据），分层避免 prompt 撑爆上下文；③ `technicals.py` 是高质量纯量化信号聚合参考（趋势/均值回归/动量/波动率/统计套利五策略，各带置信度公式）。
- **如何优化 AlphaPulse-A**：直接采用其**统一信号三元组**作为本项目所有 agent 的输出契约（与现有 `pipeline/agents.py` 的 `AgentResult` dataclass 对齐扩展）；组合经理"只做元决策"的分层原则避免上下文爆炸。
- 来源：https://github.com/virattt/ai-hedge-fund

### 2.3 Microsoft Qlib + RD-Agent — 44.6k★ / 13.5k★（自动因子工厂）

- **进展**：Qlib v0.9.7（2025-08）；RD-Agent v0.8.0（2026 上半年），新增 Web UI、LiteLLM 全后端、ICML 2026/ACL 2026 论文。论文 arXiv:2505.15155 入选 NeurIPS 2025。CSI300 实测 IC=0.0532、ARR 14.21%、IR 1.74、MDD −7.42%，较 Alpha360 提升约 80%，因子数减少 70%+，每轮优化成本 <$10。
- **优势**：① A 股原生（cn_data、SH000300，2008–2020 开箱即用）；② **因子-模型联合优化**（多臂老虎机 8 维性能向量动态决定优化因子还是模型）；③ 知识森林持续积累历史假设/代码/回测；④ Co-STEER 链式推理代码生成 + 历史相似度检索；⑤ LiteLLM 解耦，研究/开发/评估阶段可分别配不同模型。
- **如何优化 AlphaPulse-A**：**不替换现有 6-Agent 流水线，作思想补充**。本项目 `alphapulse/pipeline/`（Hypothesis→Data→Code→Backtest→Critique→Risk→Memory）已是 RD-Agent 的轻量同构版；可借鉴其"多臂老虎机调度"思路升级 `pipeline/orchestrator.py` 的下一步决策。若日后要规模化扫因子，写 `scripts/tdx_to_qlib_converter.py` 把 `data/day/*.csv` 转 Qlib binary，跑 RD-Agent 做快速 IC/ARR 粗筛，候选因子再回 VeighNa 全量回测。
- 来源：https://github.com/microsoft/qlib ｜ https://github.com/microsoft/rd-agent ｜ https://arxiv.org/abs/2505.15155

### 2.4 Anthropic financial-services（官方）— 31.3k★

- **进展**：2025 初发布 financial-analysis 技能包 + MCP 连接器；2025-10 Excel 侧边栏 Add-in + Vals AI 基准 55.3%；2026-05 发布 10 个开箱 agent 模板、Claude Opus 4.7、Claude Agent SDK 多 agent 编排公测（subagent 嵌套最深 5 层）。Apache 2.0。
- **优势**：① **skills（Markdown 指令+领域知识）+ connectors（MCP 受控数据）+ subagents（委托专用子模型）三层标准化打包**，每个 agent 模板开箱即用；② orchestrator-worker 实测比单 agent 高 90.2%；③ Excel Add-in 可读改建工作簿；④ Apache 2.0 可 fork。
- **如何优化 AlphaPulse-A**：借鉴 **skills/connectors/subagents 三层打包思想**组织本项目 agent_team 的目录与提示词；可写一份常驻"A 股短线底部挖掘投资哲学"Markdown（见 §4 的 SOUL.md 模式）。注意：官方明确**不执行交易、不绑风险**，所有输出需人工审核——与本项目"QMT 半自动"定位一致。A 股数据连接器需自建（AKShare/BaoStock MCP）。
- 来源：https://github.com/anthropics/financial-services ｜ https://www.anthropic.com/news/finance-agents ｜ https://www.anthropic.com/engineering/multi-agent-research-system

### 2.5 HKUDS/AI-Trader — 19.8k★（信号市场/跟单平台）

- **进展**：2026-05 开源，"agent-native trading platform"。论文 arXiv:2512.10971 对 6 个 LLM 做美股/A 股/加密全自主交易评测。FastAPI+React，$100K 纸交易 + 真实跟单，支持 IBKR/Binance/Coinbase。
- **优势**：① agent 读完 Skill 文档即可注册发布 strategy/action/discussion 三类信号；② 跨资产统一 OpenAPI；③ **论文实证：A 股因政策管制流动性受限，AI 超额收益难度高于美股/加密**——与本项目"底部挖掘/低流动性标的"逻辑吻合，可作风控依据。
- **如何优化 AlphaPulse-A**：定位是"信号分发出口"而非分工骨架。可选地把 `daily_screener.py` 信号发布到平台验证公开胜率。**核心可取物是论文风控结论**：在"单票≤20% 最多 5 只"基础上，对流通市值 <10 亿标的额外折减仓位（落到 §4 的 RiskAgent）。
- 来源：https://github.com/HKUDS/AI-Trader ｜ https://arxiv.org/abs/2512.10971

### 2.6 virattt/dexter — 27.1k★（单 agent + 工具/技能层）

- **进展**：v1.0.0（2026-06-15）。两级上下文压缩（microcompaction + full compaction）、WhatsApp 网关、LangSmith + LLM-as-Judge 评估、Playwright 抓取、Memory Manager、Skills 扩展层。TypeScript/Bun。
- **优势**：① **是精巧的单 agent，非多 agent 框架**（次级资料误传其有 Planning/Action/Validation 分工，实为工具组合 + Skills 层）；② SOUL.md 价值投资哲学注入每个 prompt；③ 两级上下文压缩防 token 膨胀；④ LLM-as-Judge 评估范式。
- **如何优化 AlphaPulse-A**：① 移植**两级上下文压缩**到 `alphapulse/llm/`，长多轮因子设计会话省 40–60% token；② 用 **LLM-as-Judge** 给每日 B1 信号叙述打分替代人工复核；③ **SOUL.md 常驻投资哲学**模式（见 §4）。非 A 股原生，数据工具全是美股，不取数据层。
- 来源：https://github.com/virattt/dexter ｜ https://andrew.ooo/posts/dexter-autonomous-financial-research-agent-review/

### 2.7 OpenBB — 69.3k★（数据总线/MCP）

- **进展**：ODP Desktop（2026-04-25），转向"AI agents 数据基础设施"，新增 MCP server、REST API、connect-once-consume-everywhere。AGPLv3。
- **优势**：connect-once 多端消费（Python/MCP/REST/Excel/AI agent）；MCP server 可直接接 Claude/GPT。
- **如何优化 AlphaPulse-A**：作为**可选数据补充层**（实时行情/财务/新闻情绪），补足通达信 .day CSV 缺失维度；`daily_screener.py` 可 `import openbb` 取当日行情。注意 AGPLv3 传染性，仅按需 import 不深绑。
- 来源：https://github.com/OpenBB-finance/OpenBB

### 2.8 FinRobot（AI4Finance）— 7.3k★ / FinGPT — 20.5k★（辅助）

- **FinRobot**：v1.0.0（2026-03），Director(SmartScheduler)→Data-CoT→Concept-CoT→Thesis-CoT 三段式，自动生成 15+ 图表专业研究报告。可借鉴其**模型路由（性能驱动选模型）**与 Thesis-CoT 自动生成个股研判摘要写入 `reports/`。
- **FinGPT**：金融情绪/NER/关系抽取最强（LoRA 微调），无多 agent。其**中文金融情绪模型**可单独封装为本项目第 9 个因子 `SENTIMENT_SCORE`，在 ABNORMAL_VOL 异动触发时叠加验证利好催化。
- 来源：https://github.com/AI4Finance-Foundation/FinRobot ｜ https://github.com/AI4Finance-Foundation/FinGPT

---

## 3. GitHub 近期高星项目精选（2026-06 数据）

| 项目 | Star | 活跃度 | 定位 | 与本项目契合 | 核心可取物 | 集成成本 |
|---|---|---|---|---|---|---|
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | 86.9k | 极高(v0.2.5/2026-05) | 多 agent 五层投研 | ★★★★★ | 五层分工拓扑 + Bull/Bear 辩论协议 + 双模型路由 | 低（取架构，不装框架） |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | 69.3k | 高(2026-04) | 数据基础设施/MCP | ★★★☆ | MCP 数据总线、多端消费 | 低（按需 import） |
| [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | 60.2k | 高(2026-06) | 多人格 agent 对冲基金 | ★★★★ | 统一信号三元组、元决策分层、technicals.py | 低（已精读 07） |
| [Qlib](https://github.com/microsoft/qlib)+[RD-Agent](https://github.com/microsoft/rd-agent) | 44.6k/13.5k | 高(2026) | LLM 自动因子工厂 | ★★★★ | 因子-模型联合优化、知识森林、Co-STEER | 中（数据转换） |
| [financial-services](https://github.com/anthropics/financial-services) | 31.3k | 高(2026-05) | 官方金融 agent 模板 | ★★★☆ | skills+connectors+subagents 三层打包 | 中（A 股连接器自建） |
| [dexter](https://github.com/virattt/dexter) | 27.1k | 高(v1.0/2026-06) | 单 agent + Skills | ★★☆ | 两级上下文压缩、LLM-as-Judge、SOUL.md | 低（取思想） |
| [AI-Trader](https://github.com/HKUDS/AI-Trader) | 19.8k | 高(2026-06) | agent 信号市场 | ★★☆ | A 股流动性风控结论、信号分发出口 | 中 |
| [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 20.5k | 中 | 金融 LLM 微调 | ★★ | 中文情绪因子 | 中 |
| [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | 7.3k | 中 | CoT 研报生成 | ★★ | 三段式 CoT 报告、性能驱动模型路由 | 中 |

**结论排序**：TradingAgents（骨架）> ai-hedge-fund（协议+技术信号）> RD-Agent（因子工厂思想，已有同构 pipeline）> dexter/financial-services（工程模式）> OpenBB（数据可选）> FinGPT/FinRobot（辅助因子/报告）。

---

## 4.【重点】多 agent 分工分析股票：AlphaPulse-A 的 agent team 设计

### 4.1 横向对比：各家分工模式

| 框架 | 分工范式 | 协作机制 | 聚合方式 | 记忆 |
|---|---|---|---|---|
| TradingAgents | 五层：4 分析师 → 2 研究员辩论 → 交易员 → 3 风控 → 组合经理 | 平时结构化文档（防 telephone effect），辩论阶段自然语言 | 研究经理仲裁 + 组合经理审批 | TradingMemoryLog 持久化决策日志 + 跨 ticker 教训 |
| ai-hedge-fund | 13 人格 + 6 功能 agent 并行 | 各自独立产信号，无辩论 | 组合经理对信号三元组做元决策（多空投票加权） | 无强记忆 |
| FinRobot | Director→Data→Concept→Thesis 线性三段 | Director 跨模型任务路由 | 线性传递 | 无 |
| RD-Agent(Q) | 5 单元 R&D 闭环 | 知识森林共享 | 多臂老虎机 8 维向量调度 | 知识森林全量存储 |
| Anthropic | orchestrator-worker | 主 agent 分解→并行 subagent | 主 agent 聚合草稿→人工审核 | 共享文件系统 + p2p 消息 |
| TrustTrade（学术） | 同 TradingAgents | 跨 agent 语义/数值一致性动态加权 | **贝叶斯置信度融合**（非均等信任） | 三层记忆 + Outcome Embargo 防前视 |

**提炼三条对本项目最有价值的原则**：
1. **分层不重读**（ai-hedge-fund）：下游 agent 只消费上游结构化输出，不重算原始数据，避免上下文爆炸。
2. **结构化文档 + 局部自然语言辩论**（TradingAgents）：平时传 JSON 防信息衰减，仅多空辩论阶段用自然语言。
3. **置信度加权聚合优于均等投票**（TrustTrade，arXiv:2603.22567）：本项目已有 GBDT 胜率（量化置信度），可与 LLM 的 verbal 置信度做贝叶斯融合。

### 4.2 AlphaPulse-A 七角色 agent team 设计（复用现有模块）

统一输出契约（扩展现有 `alphapulse/pipeline/agents.py:AgentResult`）：
```python
{ "agent": str, "signal": "bullish|bearish|neutral",
  "confidence": 0-100, "evidence": {...结构化字段...}, "reasoning": str }
```

| # | 角色 | 调用现有模块 | 输入 | 输出 | LLM |
|---|---|---|---|---|---|
| 1 | **DataAgent 数据** | `alphapulse/utils/data_loader`（通达信 .day CSV）、`fetch_share_capital`/市值反推 | symbol 列表 + 回放日期 | 清洗后 OHLCV + 流通市值 DataFrame；数据健康校验（沿用覆盖率判据） | 无 |
| 2 | **FactorAgent 因子** | `factors/factor_registry.compute_factor()`（8 因子）+ `ranking/sub_scores.compute_sub_scores()`（11 连续子分数）| 个股 df | 因子命中摘要 + 11 子分数 + 严格信号徽章(B1/量能B1/知行超短) | 无 |
| 3 | **PatternAgent 形态** | `strategies/playbook_engine`（B1→B2→B3 状态机）+ `strategies/needle*`/`brick*`、`ml/pattern_model.predict_ml_score()`（GBDT 胜率） | 个股 df | 当前所处战法状态(B1/B2/B3) + 形态命中 + **GBDT 胜率分(0–1) 作量化置信度** | 无 |
| 4 | **SectorAgent 板块** | `market/sector_score.rank_sectors`/`symbol_sector_map`、`analysis/concept_miner`、`market/market_score`/`macro_position` | symbol + 板块/概念映射 | 标的所属板块相对强弱、概念热度、大盘档位 | 无（可选 flash 摘要） |
| 5 | **DebateAgents 多空辩论** | `llm/client.chat()`（**v4-pro**）+ `diagnosis/llm_diagnosis` | 角色 1–4 的结构化报告 | Bull/Bear 各 1 份观点 + ResearchManager 仲裁结论 | v4-pro |
| 6 | **RiskAgent 风控** | `risk/position_manager`、A 股硬约束（T+1、涨跌停、单票≤20% 最多 5 只、滑点买0.1%卖0.2%、手续费万2.5最低5元） | 交易提案 + 流通市值 | 仓位上限/否决；**流通市值<10亿额外折减**（HKUDS 结论） | 可选 v4-pro |
| 7 | **PortfolioAgent 组合经理** | 聚合层（贝叶斯融合）+ `notify/feishu_bot`、`scripts/track_signals` | 全部 agent 三元组 | 5 档评级(Buy/增持/持有/减持/Sell) + 仓位 + reasoning，写 `reports/` + 决策日志 | v4-flash（元决策） |

**模型路由对齐 CLAUDE.md**：角色 1–4、6（数据/规则/风控）**无 LLM 或 v4-flash 批量**；角色 5 多空辩论与 7 仲裁用 **v4-pro 重推理**；摘要/报告生成用 **v4-flash**。

### 4.3 协作与聚合协议

- **通信**：角色 1→4 串/并行产出**结构化 JSON**（防 telephone effect），写入会话级 state（不传原始 K 线，只传摘要 + 子分数 + 胜率）。仅角色 5 辩论阶段用自然语言，对话同步落结构化记录。
- **聚合（核心）**：PortfolioAgent 用**贝叶斯置信度融合**（TrustTrade 公式）合并量化置信度（GBDT 胜率 `c1`）与 LLM verbal 置信度（`c2`）：
  - 一致时 `c = c1·c2 / (c1·c2 + (1−c1)·(1−c2))`
  - 分歧时 `c = c1·(1−c2) / ((1−c1)·c2 + c1·(1−c2))`
  - 各 agent 判断越一致权重越高，分歧/弱依据降权——优于均等投票。
- **硬约束兜底**：RiskAgent 在仓位约束空间内**否决/修正** LLM 方案（规则兜底 + LLM 增益）；现有 B1→B2→B3 状态机作为 PatternAgent 的硬约束动作空间。
- **记忆**：复用 `pipeline/memory.py` + 新建 `reports/agent_decisions.jsonl` 决策日志，记录每股 agent 决策 + 后续实际收益；PortfolioAgent prompt 注入"同标的最近 3 次决策 + 跨标的教训"。**严格 Outcome Embargo**（arXiv:2605.19337）：历史检索禁带未来信息，沿用本项目回放(--date)机制天然防前视。

### 4.4 MVP 与分阶段路线

**MVP（1–2 天，零 LLM，纯量化）**：新建 `alphapulse/agent_team/`，实现 DataAgent + FactorAgent + PatternAgent（含 GBDT 胜率）+ SectorAgent + PortfolioAgent（先用规则加权聚合，复用 `ranking/composite.rank_all`）。把 `daily_screener.py` Top10 标的喂入，输出带 evidence 的结构化操作建议 Markdown。**纯函数、可单测、无外部依赖**。

**阶段二（2–3 天，叠加 DeepSeek 辩论）**：接入 DebateAgents（v4-pro Bull/Bear + 仲裁），仅对 MVP 评分 >70 分的标的触发（控成本）；接入贝叶斯融合替代规则加权；接入 RiskAgent A 股硬约束。结果写入 GUI 第 4 主 Tab"投资判断"（已存在）。

**阶段三（按需）**：① 决策日志闭环 → `evening_review.py` 按序列统计 agent 胜率，回灌 prompt（dexter LLM-as-Judge 给叙述打分）；② 两级上下文压缩移植到 `llm/`；③ 可选把 RD-Agent 思想注入 `pipeline/orchestrator.py` 的多臂老虎机调度；④ 可选 OpenBB/FinGPT 情绪因子补充。

**架构原则**：thin-wrapper 复用现有模块，**不引入 LangChain/LangGraph 大依赖**（沿用 `llm/client.py` 直连 DeepSeek、规避 Py3.14 兼容风险的既有决策）；agent 输出统一三元组对齐 `pipeline/agents.py`；LLM 仅用于辩论/仲裁/报告，规则与 ML 负责确定性计算。

---

## 5. 优先级建议（先做什么 / 收益 / 工作量）

| # | 任务 | 收益 | 工作量 | 依赖 |
|---|---|---|---|---|
| **P0** | **MVP agent_team（5 角色纯量化聚合）**，喂 `daily_screener` Top10 出结构化操作建议 | 立刻把"分散的因子/状态机/GBDT/板块分数"整合为单股可解释结论；无 LLM 成本、无前视风险 | 1–2 天 | 现有模块即可 |
| **P1** | **DebateAgents 多空辩论（v4-pro）+ 贝叶斯融合聚合**，仅 >70 分触发 | LLM 增益 + 消除单边偏见；量化胜率与 verbal 置信度校准合并，比均等投票稳健 | 2–3 天 | P0 + DeepSeek key |
| **P1** | **RiskAgent A 股硬约束 + 流通市值折减**（HKUDS 结论）注入 | 防 LLM 幻觉出违规方案；降低低流动性政策风险暴露 | 0.5 天 | P0 |
| **P2** | **决策日志闭环**（`agent_decisions.jsonl` + `evening_review` 按序列统计 + LLM-as-Judge 复核） | 无监督在线学习；自动复盘替代人工 | 2 天 | P1 |
| **P2** | **两级上下文压缩**（dexter）移植到 `llm/` | 长多轮因子设计会话省 40–60% token | 1 天 | 独立 |
| **P3** | **tdx→Qlib 转换 + RD-Agent 粗筛因子** → 候选回 VeighNa 全量回测 | 自动扩充 `factor_registry`；快筛慢验避免全量跑慢回测 | 3–5 天 | 数据转换 |
| **P3** | **FinGPT 中文情绪因子 `SENTIMENT_SCORE`** 注册，异动叠加验证 | 给 ABNORMAL_VOL 加催化剂确认维度 | 2–3 天 | 情绪数据源 |

**先做什么**：直接上 **P0 MVP**——它把项目已有的五大确定性模块（B1/sub_scores、playbook、GBDT、板块评分、composite）一次性串成"单股 agent team 结论"，零新依赖、零成本、当天可验证，是收益/工作量比最高的一步；验证有效后再叠 P1 的 DeepSeek 辩论与贝叶斯聚合。

---

### 来源汇总
- TradingAgents: https://github.com/TauricResearch/TradingAgents ｜ https://arxiv.org/abs/2412.20138 ｜ https://tauricresearch.github.io/TradingAgents/
- ai-hedge-fund: https://github.com/virattt/ai-hedge-fund
- Qlib/RD-Agent: https://github.com/microsoft/qlib ｜ https://github.com/microsoft/rd-agent ｜ https://arxiv.org/abs/2505.15155
- Anthropic financial-services: https://github.com/anthropics/financial-services ｜ https://www.anthropic.com/engineering/multi-agent-research-system
- dexter: https://github.com/virattt/dexter
- HKUDS/AI-Trader: https://github.com/HKUDS/AI-Trader ｜ https://arxiv.org/abs/2512.10971
- OpenBB: https://github.com/OpenBB-finance/OpenBB
- FinGPT/FinRobot: https://github.com/AI4Finance-Foundation/FinGPT ｜ https://github.com/AI4Finance-Foundation/FinRobot
- 多 agent 学术：TrustTrade arXiv:2603.22567 ｜ TradingGroup arXiv:2508.17565 ｜ QuantAgents arXiv:2510.04643 ｜ Agentic Trading Survey arXiv:2605.19337 ｜ 置信度聚合 arXiv:2606.13591
