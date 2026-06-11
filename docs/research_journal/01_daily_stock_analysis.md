# 研究笔记 01：ZhuLinsen/daily_stock_analysis 精读与融合方案

> 日期：2026-06-11 ｜ 研究对象：https://github.com/ZhuLinsen/daily_stock_analysis
> 方法：WebSearch 定位 + 浅克隆全仓库精读（/tmp/dsa_repo，236 个非测试 .py 文件）

---

## 0. 候选清单与选择理由

| 候选 | Star | 说明 |
|------|------|------|
| **ZhuLinsen/daily_stock_analysis（选定）** | **42.1k**（fork 40k） | LLM 驱动 A/H/美股日度分析，功能最全、活跃维护、MIT 协议 |
| chjm-ai/stock-daily-analysis-skill | 少量 | 仅是上者的 OpenClaw Skill 改编版 |
| XIQUQIX/Stock-Analysis_Pioneer | 少量 | KDJ/MACD 金叉筛选 + Excel 导出，功能子集，无融合价值 |
| ArvinLovegood/go-stock | 较多 | Go 语言桌面端 AI 选股，语言栈不符 |

选定理由：名称完全匹配用户描述（"daily stock analysis"），star/fork 断层领先，功能覆盖面（数据聚合、LLM 决策、推送、回测、Agent、Web）远超其他候选，且为 Python 3.10+，与 AlphaPulse-A 技术栈同源。

---

## 1. 项目概览

- **地址**：https://github.com/ZhuLinsen/daily_stock_analysis
- **Star / Fork**：42.1k / 40k ｜ **语言**：Python 76%（其余为 Web/桌面前端）｜ **协议**：MIT
- **定位**：自选股（watchlist）日度智能分析系统——多源行情聚合 + 实时新闻检索 + LLM 生成"决策仪表盘" + 多渠道推送，支持 GitHub Actions 零成本定时运行
- **同系列**：AlphaSift（多因子全市场选股，独立仓库经 `dsa_adapter` 接入）、AlphaEvo（策略回测进化）

### 架构（文字版）

```
入口层    main.py(CLI/定时) / server.py(FastAPI) / webui.py / bot(TG/Discord/飞书命令)
             │
核心管线  src/core/pipeline.py  StockAnalysisPipeline（3100 行总调度）
             │  fetch → enhance_context → LLM analyze → guardrail → render → notify
             ├── data_provider/   DataFetcherManager：10+ 数据源能力路由 + 容错链
             │     akshare/tushare/pytdx/baostock/efinance/yfinance/longbridge/
             │     tickflow/alphavantage/finnhub（按"能力"注册：日线/实时/筹码/板块/名称）
             ├── src/search_service.py  新闻搜索：Anspire/SerpAPI/Tavily/Bocha/Brave/
             │     MiniMax/SearXNG 多 provider + 多 Key 轮换 + 降级
             ├── src/analyzer.py  LLM 层（LiteLLM 统一调用 + 多模型 fallback +
             │     json_repair + Pydantic schema 校验 + 占位符回填 + 决策稳定器）
             ├── src/stock_analyzer.py  本地技术面（趋势/量能/MACD/RSI 枚举化结论）
             ├── src/market_analyzer.py  大盘复盘 + market_light 红绿灯快照
             ├── src/phase_decision_guardrail.py  市场阶段决策护栏
             ├── src/agent/  多 Agent 编排（technical/intel/risk/portfolio/decision）
             │     + strategies/*.yaml 自然语言策略 skill（15 个内置战法）
             ├── src/services/  告警(alert_*)/信号生命周期(decision_signal)/
             │     持仓(portfolio)/历史对比/回测(backtest_service)/社交舆情
             ├── src/core/backtest_engine.py  对历史 AI 建议做 T+N 前向验证
             └── src/notification_sender/  14 个推送渠道 + notification_noise 噪音控制
存储      SQLAlchemy(SQLite)：AnalysisHistory / DecisionSignal / Portfolio / Alert
调度      GitHub Actions(工作日18:00北京时间) / Docker / 本地 --schedule / launchd 均可
模板      templates/*.j2（report_markdown/report_brief/report_wechat 分渠道渲染）
```

---

## 2. 功能清单与实现方式（逐模块）

### 2.1 多源数据聚合与容错（`data_provider/base.py`，3282 行核心）
- `BaseFetcher` 抽象基类声明能力接口：`get_daily_data` / `get_realtime_quote` / `get_chip_distribution` / `get_main_indices` / `get_market_stats` / `get_sector_rankings` / `get_concept_rankings` / `get_hot_stocks` / `get_limit_up_pool` / `get_belong_boards` / `get_stock_name`
- `DataFetcherManager`：按市场（A/HK/US/ETF）和能力过滤 fetcher → 逐个尝试 → 异常分类（`RateLimitError`/`DataSourceUnavailableError`）→ 自动跳过不可用源 → 实时行情还做**多源字段互补合并**（`_merge_quote_fields`：主源缺字段用次源补全）
- 超时/重试统一封装（`_run_with_timeout`/`_run_with_retry`），基本面块带预算秒数和 TTL 缓存
- 股票名称多级缓存 + 批量预取（`prefetch_stock_names`）

### 2.2 LLM 决策仪表盘（`src/analyzer.py` 3800 行 + `src/schemas/report_schema.py`）
- LiteLLM Router 统一调用任意厂商（DeepSeek/Gemini/Claude/Ollama…），多模型 fallback、多 Key 轮换、用量持久化（`persist_llm_usage`）
- 输出强约束为 Pydantic `AnalysisReportSchema`：`sentiment_score(0-100)` / `dashboard.core_conclusion`（一句话结论+信号类型+时效性+有/无仓建议）/ `data_perspective`（趋势/价格位置/量能/**筹码结构**）/ `intelligence`（最新动态/风险警报[]/利好催化[]/业绩预期/舆情摘要）/ `battle_plan.sniper_points`（理想买点/次级买点/止损/止盈）+ 仓位策略 + 操作检查清单 / `phase_decision`
- 健壮性管线：`json_repair` 修复劣质 JSON → `check_content_integrity` 检查必填字段 → `apply_placeholder_fill` 占位符回填 → `_trend_*_fallback` 用本地技术面结果兜底 LLM 缺失字段 → `stabilize_decision_with_structure` 用确定性结构数据稳定 LLM 决策（防 LLM 与数据自相矛盾）

### 2.3 市场阶段决策护栏（`src/phase_decision_guardrail.py`）
- 按交易时段（盘前/盘中/午休/尾盘竞价/盘后/非交易日）对 LLM 建议做规则审查：非交易时段禁止输出"立即买入/卖出"类即时动作（含中英文否定前缀识别防误杀）、核心数据块（quote/daily_bars/technical）降级时强制保守决策、盘后输出复盘式措辞
- 配套 `src/core/trading_calendar.py`（A/H/US 三市场交易日历）

### 2.4 自然语言策略 Skill（`strategies/*.yaml`，15 个）
- 均线金叉/缠论/波浪/龙头/情绪周期/事件驱动/热点题材/缩量回踩/底部放量/一阳三阴/箱体震荡/多头趋势/成长质量/预期重估等
- 每个 YAML 只含元数据（name/category/aliases/required_tools/market_regimes/priority）+ `instructions` 自然语言战法描述（判定标准、量能确认、评分调整规则），**零代码新增战法**；运行时由 Agent 按工具清单取数并按 instructions 研判
- `src/agent/strategies/router.py` 按用户问题/市场状态路由到策略

### 2.5 多 Agent 编排（`src/agent/`，实验性）
- 5 个角色 Agent（`technical_agent`/`intel_agent`/`risk_agent`/`portfolio_agent`/`decision_agent`），各自 system_prompt + 工具集 + `post_process` 产出 `AgentOpinion`，由 `orchestrator.py`（1614 行）汇总仲裁，带预算护栏与 provider 轨迹追踪
- 工具注册表 `src/agent/tools/registry.py`：data/market/analysis/search/backtest 五类工具

### 2.6 大盘复盘与红绿灯（`src/market_analyzer.py` + `src/services/market_light_service.py`）
- `get_market_overview`：指数、涨跌家数、涨停/跌停池、板块/概念涨跌榜、热股
- `build_market_light_snapshot`：结构化大盘"红绿灯"快照（Pydantic 校验）持久化，逐日对比生成趋势变化告警（`market_light_alerts.py`）
- LLM 生成大盘复盘文字 + `_summarize_market_review` 摘要

### 2.7 信号生命周期与告警（`src/services/decision_signal_service.py` / `alert_*.py`）
- DecisionSignal 入库：action/入场区间校验/止损止盈/过期时间/触发来源，状态机 active→triggered/expired，与持仓联动去重
- 技术指标告警引擎（`alert_indicators.py`）：MA/RSI/MACD/KDJ/CCI 的"上穿/下穿阈值、零轴、交叉方向"统一判定框架，`alert_worker.py` 后台轮询

### 2.8 AI 建议事后验证（`src/core/backtest_engine.py`）
- 对历史每条 LLM `operation_advice` 做 T+N 前向验证：从建议日取 forward bars，先判止损/止盈触达（同一根 K 线同时触及时标记 `first_hit="ambiguous"` 并保守按止损先成交），再算窗口收益、方向命中，`compute_summary` 汇总胜率——形成"AI 说的话准不准"的量化闭环

### 2.9 持仓与组合（`portfolio_service.py`/`portfolio_risk_service.py`/`portfolio_alerts.py`）
- 持仓导入（图片 OCR via LLM `image_stock_extractor.py`、CSV/Excel、剪贴板）、持仓风险监控、持仓相关推送

### 2.10 新闻/舆情（`src/search_service.py` + `social_sentiment_service.py`）
- 7 类搜索 provider 统一 `BaseSearchProvider` 接口，多 Key 轮换、可解释排序（新闻按相关性/时效打分）、SearXNG 自建实例无配额兜底
- 美股社交舆情（Reddit/X/Polymarket，第三方 API，可选）

### 2.11 推送与渲染（`src/notification_sender/` 14 渠道 + `templates/*.j2`）
- 企业微信/飞书/Telegram/Discord/Slack/邮件/PushPlus/ServerChan/ntfy/Gotify/Pushover/AstrBot/自定义 Webhook；飞书云文档解决长文截断；Markdown 转图片（`md2img.py`）
- `notification_noise.py`：去重 TTL、冷却时间、静默时段、最低严重级——防告警轰炸
- 按渠道分模板渲染（完整版/简报版/微信版）

### 2.12 调度与部署
- GitHub Actions 工作日 18:00 自动跑（交易日判断、断点续传、非交易日跳过）；Docker；本地 `--schedule`；FastAPI `--serve-only`；桌面端打包

---

## 3. 与 AlphaPulse-A 重叠的部分（已有，不必融合）

| DSA 模块 | AlphaPulse-A 对应物 | 结论 |
|----------|--------------------|------|
| AlphaSift 全市场多因子选股 | 全市场 0-100 加权评分（13 子分数 + LightGBM）→ Top50 | 已有且更深（含 ML 分），不融合 |
| `stock_analyzer.py` 本地技术指标 | 8 大因子 + factor_registry + 通达信公式翻译 | 已有且更贴合战法 |
| 大盘复盘 `market_analyzer` | 大盘诊断（量能/N型/知行BS 三维） | 框架已有；仅"红绿灯快照逐日对比"思想可参考 |
| 板块/概念排行 | 49 行业 + 126 概念本地聚合评分 | 已有，且 DSA 该能力依赖东财类接口（本机被封） |
| 策略回测 | vnpy + 三大战法状态机回测 + 网格搜索 | 已有且更严格（滑点/手续费/仓位约束） |
| 信号胜率统计 | 信号胜率验证器 + 信号追踪闭环（7日跟踪→归因→因子沉淀） | 已有；仅 2.8 的"止损止盈触达判定"细节可借鉴 |
| LLM 接入 | DeepSeek NL→因子管线 + AI 研判 | 通道已有；缺的是 DSA 的结构化 schema 与护栏（见下） |
| Web 界面 | Streamlit GUI v4 交易台 | 已有，不引入 FastAPI+桌面端 |

---

## 4. 值得融合的精华清单（按价值排序）

### ★1 多数据源容错链（DataFetcherManager 模式）
- **是什么**：`data_provider/base.py` 的"能力注册 + 按市场过滤 + 逐源降级 + 异常分类 + 字段互补合并 + 超时重试预算"框架，及 `pytdx_fetcher.py`（直连通达信行情服务器）、`efinance_fetcher.py`、`tushare_fetcher.py` 三个现成实现
- **为什么有价值**：AlphaPulse-A 当前 baostock/akshare/新浪是硬编码单链路，东财被封禁已暴露单点风险；pytdx 与用户的通达信数据血缘一致，可作实时行情与日线补源；这是全系统数据可靠性的地基
- **怎么融合**：在 `alphapulse/utils/data_loader.py` 之上加一层 `FetcherManager`（抽 DSA 的 base.py 骨架，砍掉 HK/US/Longbridge/TickFlow），注册 baostock→akshare→pytdx→efinance→新浪 五源，日线/实时/板块三种能力分别配优先级；现有调用方接口不变
- **工作量**：2-3 天（骨架可大量参考其源码，MIT 协议允许）

### ★2 LLM 结构化决策仪表盘 + 决策护栏
- **是什么**：`report_schema.py` 的 Pydantic 仪表盘 schema（评分/一句话结论/狙击点位/止损止盈/风险警报/利好催化/操作检查清单）+ `analyzer.py` 的 json_repair→完整性检查→本地技术面兜底→`stabilize_decision_with_structure` 决策稳定器 + `phase_decision_guardrail.py` 时段护栏
- **为什么有价值**：现有 DeepSeek AI 研判输出是自由文本，无法入库、无法事后验证、可能与量价数据自相矛盾；DSA 这套是 42k star 项目踩坑两年的健壮性结晶
- **怎么融合**：给现有 AI 研判模块（DeepSeek 集成层）定义精简版 `DashboardSchema`（pydantic），prompt 要求 JSON 输出，接 `json_repair` 修复，缺字段用全市场评分的 13 子分数兜底；加规则：LLM 建议方向与本地评分/战法信号冲突时降级为"观望"；研判结果连同 schema 入 SQLite 供 ★6 验证
- **工作量**：2-3 天

### ★3 战法 YAML 化（自然语言策略 Skill）
- **是什么**：`strategies/*.yaml` 模式——每个战法一个 YAML：元数据 + required_tools + 自然语言 instructions（判定标准/评分调整），LLM 按之研判，零代码扩展
- **为什么有价值**：用户的 B1 六条件/量能B1/知行超短/砖型图本质就是"通达信公式 + 操作纪律"的自然语言知识，YAML 化后 DeepSeek 可直接按战法逐票研判并解释"为什么像/不像 B1"，与现有 NL→因子管线天然衔接；也让未来新战法（用户常提供案例）沉淀有统一格式
- **怎么融合**：新建 `alphapulse/strategies/skills/*.yaml`（b1.yaml/zhixing_short.yaml/needle.yaml/brick.yaml），required_tools 映射到现有 factor_registry 与 data_loader；在 DeepSeek 研判 prompt 中注入对应 skill 的 instructions；DSA 的 15 个内置 YAML（尤其缩量回踩、底部放量、一阳三阴、情绪周期、龙头战法）可直接改写复用
- **工作量**：1-2 天（纯配置 + prompt 组装）

### ★4 新闻/消息面接入（search_service 多 provider 框架）
- **是什么**：`src/search_service.py` 的 BaseSearchProvider 统一接口 + 多 Key 轮换 + 可解释排序 + SearXNG 免费兜底；管线中"对 Top 候选股补新闻→LLM 提炼风险警报/利好催化"的用法
- **为什么有价值**：AlphaPulse-A 是纯量价系统，完全没有消息面；A 股短线战法（尤其知行超短）对题材/公告极敏感，"放量异动"背后是否有催化是胜率关键变量；信号追踪闭环的连涨归因也缺消息面维度
- **怎么融合**：抽 provider 框架，先接零成本的 SearXNG 自建 + 新浪财经新闻接口（东财封禁不影响），可选 Tavily 免费额度；只对每日 Top50 候选补新闻（控制配额），新闻摘要进 DeepSeek 研判上下文，输出归入 ★2 的 risk_alerts/positive_catalysts 字段
- **工作量**：2-3 天

### ★5 多渠道推送 + 噪音控制
- **是什么**：`notification_sender/`（14 渠道，每渠道一个独立 sender 文件，可直接拷）+ `notification_noise.py`（去重 TTL/冷却/静默时段/最低严重级）+ 分渠道 Jinja2 模板（完整版/简报版）
- **为什么有价值**：现有 daily_screener/risk_monitor 输出只落本地 CSV/MD，盘中 14:30 信号和 CRITICAL 风控警报无法实时触达手机；DSA 的 sender 是即拿即用的成熟代码
- **怎么融合**：拷 `wechat_sender.py`（企业微信 webhook 最简）+ `telegram_sender.py` + `notification_noise.py` 三个文件级移植；在 daily_screener 末尾和 risk_monitor exit 1 路径上挂推送；信号简报用 report_brief.j2 改造
- **工作量**：0.5-1 天（性价比最高的一项）

### ★6 AI 建议事后验证（BacktestEngine 前向评估）
- **是什么**：`src/core/backtest_engine.py` 对每条历史 LLM 建议做 T+N 前向验证：止损/止盈触达判定（同 K 线双触达标 ambiguous 按止损保守处理）、方向命中、窗口收益、按建议类型汇总胜率
- **为什么有价值**：现有信号胜率验证器只验证"战法信号"，不验证"AI 研判"；接入 ★2 后 AI 建议结构化入库，此引擎让 AI 研判也进入"7日跟踪→归因→沉淀"闭环，可量化 DeepSeek 研判增量价值（决定 AI 分在 13 子分数中的权重——正好对应遗留待办"权重调优"）
- **怎么融合**：在现有信号追踪闭环里加 `ai_advice` 信号类型，移植 `evaluate_single`/`compute_summary`（约 300 行纯 pandas 逻辑，无依赖）；周度产出"AI 研判胜率 vs 战法信号胜率"对比表入 reports/
- **工作量**：1-2 天

### ★7 筹码分布因子
- **是什么**：`get_chip_distribution`（akshare `stock_cyq_em` 等/tushare 实现）：获利盘比例、平均成本、90/70 集中度；DSA 把 `chip_structure`（含 chip_health 健康度）作为决策仪表盘四大数据视角之一
- **为什么有价值**：13 个子分数无筹码维度；筹码集中度/获利盘对 B1"洗盘结束"判定（知行洗盘 3/21 参数）是强互补信号——DSA 推送样例中"筹码集中度 35.15% 表明筹码分散，拉升阻力大"正是用户战法关心的逻辑
- **怎么融合**：新增 `alphapulse/factors/chip_structure.py` 实现 `compute(df)->Series`，注册 factor_registry；注意 akshare 筹码接口走东财的风险——优先用 tushare 版或按 DSA 的多源思路自算（用历史成交量分布估算，DSA 的 `realtime_types.ChipDistribution` 字段定义可作契约）；作为第 14 个子分数小权重试运行，经信号追踪闭环验证后再调权
- **工作量**：2 天（含数据源验证）

### ★8 大盘红绿灯快照逐日对比（可选）
- **是什么**：`market_light_service.py`：大盘结构化快照（Pydantic）持久化 + 与前一交易日快照 diff 生成状态变化告警
- **为什么有价值**：现有大盘诊断每天独立输出，缺"今天比昨天变好/变坏"的增量视角；实现极轻
- **怎么融合**：把现有量能/N型/知行BS 三维诊断结果定义成 snapshot dataclass 存 SQLite，加 diff 函数，变化时走 ★5 推送
- **工作量**：0.5 天

---

## 5. 不建议融合的部分及原因

| 模块 | 原因 |
|------|------|
| FastAPI Web 工作台 + 桌面端（api/ apps/ webui.py） | 与 Streamlit GUI v4 完全重复，前端代码量巨大，维护成本不值 |
| 多 Agent 编排（5 Agent + orchestrator 1614 行） | 官方标注实验性；token 消耗数倍于单次结构化调用；DeepSeek 单轮 + schema（★2）已覆盖 90% 价值 |
| 港股/美股多市场、yfinance/longbridge/tickflow/finnhub | 用户聚焦 A 股，引入只增加 fetcher 维护面 |
| 社交舆情 Stock Sentiment API（Reddit/X/Polymarket） | 仅支持美股，且依赖第三方付费 API |
| LiteLLM 全家桶多模型路由 | 用户只用 DeepSeek（v4-pro/v4-flash 双模型路由已在 CLAUDE.md 约定）；只需借鉴其"多 Key 轮换 + 失败降级"思想，无需引入 litellm 依赖 |
| Bot 命令系统（Telegram/Discord 多轮对话问股） | 低频需求，Streamlit 已覆盖交互；推送单向触达（★5）足够 |
| GitHub Actions 调度 | 已有 launchd 方案稳定运行，且本地有 5229 只全量 CSV，Actions 容器内拉不到 |
| AlphaSift/AlphaEvo 外部仓库接入 | 角色等同于自有全市场评分与回测体系；其 `dsa_adapter` 契约设计（status/424 错误边界）可作日后模块解耦参考，但不引代码 |
| 持仓图片 OCR 导入 | 用户 positions.csv 流程已定型，QMT 对接在阶段九另有方案 |

---

## 6. 推荐实施顺序

按"性价比递减 + 依赖顺序"排列：

1. **★5 推送渠道 + 噪音控制**（0.5-1 天）——文件级移植，立刻让 14:30 信号和风控警报上手机，无依赖
2. **★1 数据源容错链**（2-3 天）——地基工程，解东财封禁之痛，后续 ★4/★7 都依赖它
3. **★2 结构化 AI 仪表盘 + 护栏**（2-3 天）——AI 研判从"能看"到"能存、能验、能信"
4. **★3 战法 YAML 化**（1-2 天）——依赖 ★2 的 prompt 组装层；把 B1/知行超短沉淀为 skill
5. **★6 AI 建议事后验证**（1-2 天）——依赖 ★2 入库的数据；接入信号追踪闭环，为权重调优提供依据
6. **★4 新闻接入**（2-3 天）——依赖 ★1 的 provider 框架思路与 ★2 的 schema 字段
7. **★7 筹码因子**（2 天）——独立可并行，但建议在 ★1 落地后做（多源取筹码数据）
8. **★8 大盘红绿灯 diff**（0.5 天）——收尾甜点

总计约 2-3 周渐进落地；每步独立可交付、可回滚，符合"每次修改前 git commit、每阶段追加 progress_log.md"的项目纪律。

---

## 附：精读时参考的关键源文件（克隆于 /tmp/dsa_repo，可随时重新克隆）

- `data_provider/base.py`（3282 行，容错链核心）、`data_provider/pytdx_fetcher.py`
- `src/core/pipeline.py`（3105 行总管线）、`src/core/backtest_engine.py`（683 行）
- `src/analyzer.py`（3800 行 LLM 层）、`src/schemas/report_schema.py`（仪表盘 schema）
- `src/phase_decision_guardrail.py`、`src/core/trading_calendar.py`
- `strategies/*.yaml` + `strategies/README.md`（skill 模板）
- `src/search_service.py`、`src/notification_sender/*.py`、`src/notification_noise.py`
- `src/market_analyzer.py`、`src/services/market_light_service.py`
- `src/services/decision_signal_service.py`、`src/services/alert_indicators.py`
- `docs/full-guide.md`、`docs/alphasift-integration.md`
