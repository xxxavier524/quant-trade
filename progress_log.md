# AlphaPulse-A 进度日志

> 每阶段结束自动追加。格式：时间戳、任务名、结果、最优参数、下一步建议。

---

## 总体进度

| 阶段 | 状态 | 完成时间 | 备注 |
|------|------|----------|------|
| 阶段零：项目脚手架 | ✅ | 2025-05-16 | 目录结构、CLAUDE.md、配置 |
| 阶段一：环境搭建与数据准备 | 🔄 | 2025-05-16 | akshare方案替代TDX，下载脚本就绪 |
| 阶段二：核心因子实现 | ✅ | 2025-05-16 | 8因子+注册表+10测试通过 |
| 阶段三：案例分析与因子提炼 | ⏭️ | 2025-05-16 | 跳过（无cases.csv），后续补 |
| 阶段四：策略信号生成器 | ✅ | 2025-05-16 | B1/砖型图/单针下三十+5测试通过 |
| 阶段五：VeighNa 回测 | ✅ | 2025-05-16 | 独立回测引擎+VeighNa封装 |
| 阶段六：参数网格搜索 | ⬜ | | |
| 阶段七：云端交叉验证 | ⬜ | | |
| 阶段八：Agent 工具封装 | ✅ | 2025-05-16 | 4脚本完成，待真实数据验证 |
| 阶段九：QMT 实盘对接 | ✅ | 2025-05-16 | export_qmt_csv完成，待券商开通 |
| 阶段十：长期无人值守 | ✅ | 2025-05-16 | launchd+auto脚本，待接入真实数据 |
| 阶段十一：GitHub Top 10 集成研究 | ✅ | 2026-05-21 | 4适配器+前端迁移+Python3.14兼容验证 |
| 阶段十二：AlphaPulse-A 最终集成 | ✅ | 2026-05-21 | 40因子注册+3策略集成+管线更新+129测试全过 |

## 待补阶段

| 阶段 | 跳过原因 | 阻塞项 | 预计补做时机 |
|------|----------|--------|-------------|
| 阶段一（全量下载） | 需运行全A股下载 | 约2-3小时 | 随时可执行 `python scripts/download_a_share_data.py` |
| 阶段一（VeighNa安装） | 未安装 | pip install veighna | 阶段五前补 |
| 阶段三 | 无cases.csv案例数据 | 需用户准备≥10条 | 用户提供后补 |

---

## 阶段零：项目脚手架 — 2025-05-16

- **结果**: 成功。目录结构、CLAUDE.md、progress_log.md、config/settings.py、git init 完成
- **产出**:
  - `CLAUDE.md` — 精简版完整计划 + 核心约束
  - `alphapulse/` 完整包结构（factors/strategies/utils/config）
  - `config/settings.py` — 全局配置常量
- **下一步**: 阶段一 — 安装 VeighNa，准备数据源

---

## 阶段一：环境搭建与数据准备 — 2025-05-16

- **结果**: 部分完成。数据方案从通达信 `.day` 改为 akshare 直接下载
- **产出**:
  - `scripts/download_a_share_data.py` — 批量下载脚本（限流/断点续传/进度条）
  - `data/day/600519.csv` — 茅台样本（87行，2025-01~05）
  - `data/day/000001.csv` — 平安银行样本（87行，2025-01~05）
- **验证**: 列完整（OHLCV+金额+振幅+涨跌幅+换手率），前复权
- **待完成**: 全量A股下载（约5000只，预计2-3小时）、VeighNa安装
- **全量下载命令**: `python scripts/download_a_share_data.py`
- **下一步**: 全量下载后进入阶段五（VeighNa回测）

---

## 阶段二：核心因子实现 — 2025-05-16

- **结果**: 成功。8个因子全部实现，10个单元测试全部通过
- **产出**:
  - `alphapulse/factors/n_struct.py` — N型结构识别（scipy.signal 极值点检测）
  - `alphapulse/factors/vol_red_green.py` — 红肥绿瘦（涨跌量比）
  - `alphapulse/factors/abnormal_vol.py` — 放量异动（K倍均量 + 频次统计）
  - `alphapulse/factors/vol_cont_shrink.py` — 缩量（近期最大量对比）
  - `alphapulse/factors/kdj_j_low.py` — J值低位（KDJ超卖）
  - `alphapulse/factors/weekly_ma_bull.py` — 周线多头（周线重采样+MA排列）
  - `alphapulse/factors/macd_bull_dead.py` — MACD多头/零轴上死叉
  - `alphapulse/factors/shrink_to_abnormal.py` — 缩量至异动量1/4
  - `alphapulse/factors/factor_registry.py` — 因子注册表（名称→函数映射）
  - `tests/test_factors.py` — 10个单元测试，合成数据全覆盖
- **验证**: `python -m pytest tests/test_factors.py -v` 10 passed
- **关键参数**: 均采用 default_params，网格搜索待阶段六
- **下一步**: 阶段三（需用户提供 cases.csv）或直接阶段四（策略实现）

---

## 阶段三：案例分析与因子提炼

⏭️ 跳过待补

---

## 阶段四：策略信号生成器 — 2025-05-16

- **结果**: 成功。三个策略信号生成器实现，5个单元测试全部通过
- **产出**:
  - `alphapulse/strategies/b1.py` — B1策略（5因子条件组合：缩量+J低+MACD+异动+周线多头）
  - `alphapulse/strategies/brick.py` — Renko砖型图（固定2%振幅+连续同向砖确认）
  - `alphapulse/strategies/needle.py` — 单针下三十（长下影+J超卖+低位30%+缩量确认）
  - `tests/test_strategies.py` — 5个单元测试
- **输出格式**: 统一DataFrame（symbol/date/signal/strategy/factor_snapshot）
- **验证**: `python -m pytest tests/ -v` 15 passed (10 factors + 5 strategies)
- **下一步**: 阶段五（需VeighNa安装+真实数据）或阶段六（参数网格搜索）

---

## 阶段五：VeighNa 回测 — 2025-05-16 (部分)

- **结果**: 独立回测引擎+VeighNa封装完成，待数据就绪后运行
- **产出**:
  - `alphapulse/utils/backtest_utils.py` — 滑点/手续费/仓位管理工具
  - `scripts/run_backtest.py` — 独立回测引擎（逐日遍历、信号执行、绩效计算）
  - `vnpy_strategies/b1_strategy.py` — B1 CtaTemplate 封装
  - `vnpy_strategies/brick_strategy.py` — 砖型图 CtaTemplate 封装
  - `vnpy_strategies/needle_strategy.py` — 单针 CtaTemplate 封装
- **回测功能**: 年化收益率、最大回撤、夏普比率、胜率、盈亏比
- **待完成**: 数据就绪后运行完整回测（2020-2025）、生成HTML报告
- **下一步**: 阶段六（参数网格搜索）或等待数据下载完成

---

## 阶段六：参数网格搜索

⬜ 待执行

---

## 阶段七：云端交叉验证

⬜ 待执行

---

## 阶段八：Agent 工具封装 — 2025-05-16

- **结果**: 成功。4个独立脚本全部实现，集成测试通过
- **产出**:
  - `scripts/daily_screener.py` — 每日三大策略选股，输出Markdown信号报告
  - `scripts/evening_review.py` — 晚间复盘，比对信号vs实际涨跌，生成胜率统计
  - `scripts/risk_monitor.py` — 风控监控（仓位/回撤/亏损5项检查），CRITICAL时exit 1
  - `scripts/export_qmt_csv.py` — QMT批量下单CSV导出（含代码格式转换、整手计算）
- **待完成**: 真实数据验证、macOS launchd / Python schedule 定时配置
- **下一步**: 阶段五（VeighNa回测，需数据）

---

## 阶段九：QMT 实盘对接 — 2025-05-16

- **结果**: 基本完成。`scripts/export_qmt_csv.py` 可独立使用
- **产出**: QMT格式订单CSV（code/quantity/direction/price_type/price）
- **待完成**: 券商QMT开通后的模拟交易测试、3个月半自动运行规则执行
- **下一步**: 券商对接

---

## 阶段十：长期无人值守 — 2025-05-16

- **结果**: 成功。自动化框架搭建完成
- **产出**:
  - `scripts/daily_auto_run.py` — 每日凌晨自动化主脚本（因子扫描+策略快照+案例复核+日报生成）
  - `config/com.alphapulse.daily-auto.plist` — macOS launchd 配置（每日 2:00 触发）
  - `CLAUDE.md` — 已更新模型路由+自动化任务说明
  - `daily_auto_report.md` — 无人值守日报模板
  - `logs/` — 日志目录
- **安装 launchd**: `cp config/com.alphapulse.daily-auto.plist ~/Library/LaunchAgents/ && launchctl load ...`
- **Python schedule 备选**: 可替代 launchd，适合无 sudo 权限场景
- **待完成**: 真实数据接入后首次夜间运行验证、连续一周稳定性测试
- **下一步**: 接入真实数据，跑通全流程

---

## 阶段十一：GitHub Top 10 开源项目集成研究 — 2026-05-21

- **结果**: 成功。10个项目全面研究 + 4个Python适配器 + 前端迁移指南
- **产出**:
  - `reports/github_top10_research.md` — 完整研究报告（10个项目逐一分析）
  - `alphapulse/adapters/__init__.py`
  - `alphapulse/adapters/riskfolio_adapter.py` — Black-Litterman + CVaR + HRP 组合优化适配器（P0）
  - `alphapulse/adapters/vectorbt_adapter.py` — 向量化网格搜索加速适配器（P0）
  - `alphapulse/adapters/financetoolkit_adapter.py` — 45个基本面因子适配器（P1）
  - `alphapulse/adapters/tradingagents_adapter.py` — 多智能体LLM信号增强适配器（P1）
  - `frontend/lightweight_charts_migration.md` — TradingView前端迁移指南（P1）

### Python 3.14 兼容性验证

| 项目 | pip安装 | 版本 | 导入验证 |
|------|---------|------|----------|
| backtrader | YES | 1.9.78.123 | OK |
| yfinance | YES | 1.3.0 | OK |
| FinanceToolkit | YES | 2.0.7 | OK |
| TradingAgents | YES | 0.6.0 | OK (liteLLM警告可忽略) |
| Riskfolio-Lib | YES | 7.2.1 | OK (HRP/NCO scipy兼容性警告) |
| vectorbt | YES | 0.28.2 | OK |
| OpenBB | YES | 4.7.1 | OK |
| Microsoft Qlib (pyqlib) | **FAILED** | N/A | 无cp314 wheel |

### 适配器测试结果

| 适配器 | 无视图BL | CVaR | HRP | 自动选择 | 仓位转换 |
|--------|---------|------|-----|---------|---------|
| riskfolio_adapter | PASS | PASS | PASS(fallback) | PASS | PASS |
| vectorbt_adapter | N/A | N/A | N/A | N/A | PASS(single+multi) |
| financetoolkit_adapter | N/A | N/A | N/A | N/A | PASS(45因子) |
| tradingagents_adapter | N/A | N/A | N/A | N/A | PASS(fallback) |

### 已知限制
- **Riskfolio-Lib HRP/NCO**: scipy sqrtm在Python 3.14有兼容性问题，自动fallback到CVaR
- **Microsoft Qlib**: 无cp314 wheel，需Python 3.12 sidecar环境或纯pandas重新实现Alpha158
- **TradingAgents**: 需LLM API密钥(DeepSeek推荐)，无密钥时graceful fallback（信号透传）

### 集成优先级
1. **P0-立即**: Riskfolio-Lib Black-Litterman/CVaR替换静态20%仓位分配
2. **P0-立即**: vectorbt向量化网格搜索加速阶段六参数扫描
3. **P1-短期**: FinanceToolkit 45个基本面因子扩展因子库
4. **P1-短期**: TradingAgents多智能体信号增强（需API密钥）
5. **P1-短期**: Lightweight Charts替换Chart.js前端
6. **P2-中期**: Qlib Alpha158因子纯pandas重实现
7. **P3-长期**: OpenBB作为美国市场基准数据源

- **下一步**: P0项集成到主回测流程中

---

## 阶段十二：AlphaPulse-A 最终集成 — 2026-05-21

- **结果**: 成功。全量因子注册+3新策略集成+选股管线更新+129测试全过+E2E验证通过
- **产出**:

### 因子注册表完整性 (factor_registry.py)
- **40个因子/策略** 全部注册（原有19 + 新9多头 + 新5空头 + 1单针 + 2风控 + 3策略 + 1指标补充）
- 所有模块导入验证通过，无缺失

### 新增9个多头因子 (type="core")
| 因子 | 描述 |
|------|------|
| KEY_KLINE | 关键K线：近20日涨幅最大阳线+量>2倍均量 |
| VIOLENT_KLINE | 暴力K：涨幅>5%+量>3倍均量 |
| DOUBLE_VOLUME_BAR | 倍量柱：量>=前日2倍+阳线 |
| CHIP_CONCENTRATION | 筹码集中度：振幅<15%+换手率下降 |
| SYMMETRIC_STRUCTURE | 对称结构：V/W型形态识别 |
| FILL_PIT_EXIT_PIT | 填坑出坑：回落>15%→横盘→放量突破 |
| LONG_YIN_SHORT_COLUMN | 长阴短柱：阴线+缩量+实体>1% |
| WAVE_IDENTIFIER | 波段识别：建仓波/拉升波/冲刺波 |
| KEY_K_ABC | 关键K线ABC：A低点/B回调/C突破节点 |

### 新增5个空头/风控因子 (type="risk")
| 因子 | 描述 |
|------|------|
| S1_SELL_SIGNAL | S1卖出：波段高点放巨量阴线(0/1/2三级) |
| DD_SELL_SIGNAL | DD卖出：收盘<前日最低价(0/1/2三级+DD增强) |
| TRENDLINE_BREAK | 趋势线跌破：白线/黄线跌破+假跌破确认 |
| DYNAMIC_STOP_LOSS | 动态止损：入场低点-N型低点取min |
| FLY_AWAY | 放飞减仓：连续阳线加速→阶梯减仓1/4→1/3→1/2 |

### 3个新策略
| 策略 | 描述 | 置信度 |
|------|------|--------|
| B1_B2_B3 | B1底部挖掘(7AND)→B2阳线确认→B3锁仓 | 0.6/0.75/0.9 |
| BRICK_THREE_TYPES | 砖型图3子类型(N起跳/上涨中继/横盘突破) | 0.55-0.85 |
| NEEDLE_WASHOUT | 单针下三十N型洗盘版(10条件AND) | 0.6-1.0 |

### 选股管线更新
- `scripts/friday_screener.py`: 7策略全量选股 + signal_type列输出 + 子类型明细
- `scripts/after_close.py`: B1/B2/B3递进统计 + 砖型图3类型统计 + 单针洗盘统计

### 代码质量修复
- 修复 `needle_washout.py` 和 `b1_b2_b3_strategy.py` 中的 FutureWarning (fillna/ffill downcasting)
- 全部 `.fillna(False)` → `.fillna(False).infer_objects(copy=False)`
- 全部 `.ffill()` → `.ffill().infer_objects(copy=False)`

### 测试结果
- `python -m pytest tests/ -v --tb=short`: **129 passed, 0 failed**
- E2E验证 (500股样本): B1=2, B2=0, B3=0 (严格条件), BRICK NJUMP=0/CONT=1/BRKOUT=20969, NEEDLE_WASHOUT=24
- 所有策略正常运行，无异常

### 已知Issue
- BRICK_BREAKOUT 信号偏多 (20969/500股 ≈ 42/股)，横盘突破条件可能需要收紧
- B1/B2/B3 在随机500股中仅触发2个B1信号（7条件AND非常严格，属正常）

- **下一步**: 策略参数调优、P0 Riskfolio-Lib/vectorbt集成到回测流程

## 2026-06-11 Phase 0 — 公式忠实复现 + 黄金案例回归（v3-dev）

**目标：Python 翻译与通达信选股结果一致（用户最高优先级）**

- 原始通达信公式存档至 `docs/tdx_formulas/`（7个txt），交易体系口述规格写入 `docs/trading_system.md`
- 重大修复：
  - 知行多空线参数 20/60/120/250 → **14/28/57/114**（用户确认值）
  - 知行洗盘短线 N1/N2 5/30 → **3/21**（用户确认值）
  - `b1_formula` 条件5弃用 EMA12/26 近似，改调真知行白线/黄线
  - 数据schema漂移修复：`turn`/`turnover` 双列合并（影响约旧版下载股票的市值条件）
  - 市值统一从CSV换手率反推流通股本（逐日精确，无需网络）；单位统一为元
- 新增 `zhixing_trend.compute_ultra()`：知行超短选股方案5条件完整实现
- 新工具 `scripts/replay_screen.py`：历史日全市场回放/黄金对比/逐条件诊断/区间信号日定位（向量化，等价逐日切片但快两个数量级）
- **回归结果**（窗口2025-12~2026-05-15，三公式并集）：
  - 33只B1案例：31/32命中（96.9%，920807北交所无数据；野马电池白线全程贴黄线下方~1分钱，可解释）
  - 14只超短案例：14/14命中（100%，立讯精密由知行超短2026-04-20命中，证实"2604"=4月超短案例）
  - 信号日定位表 `tests/golden/located_signal_days.csv` 待用户复核
- 回归固化：`tests/golden/test_golden_cases.py`（3用例，公式改动必须通过）
- 关键认知：案例xls为**多日收集的案例集**而非单日选股快照（导出日2026-05-17为周日）

## 2026-06-11 Phase 1 — 数据管道可靠性（v3-dev）

- **根因确认**：2个僵尸 daily_update 进程自6月3日挂死8天（baostock TCP socket 无超时）——即"定时任务卡死"元凶
- daily_update.py 重写：socket全局30s超时 / 预检不mkdir+飞书告警 / 查指数定最新交易日已最新零API跳过 / 复权一致性自动重下 / 断点续传 / 断线重连 / 原子写 / turn列自愈
- run_with_timeout.py 外层硬超时包装器接入 launchd plist（60分钟上限）并已重装载
- 验证：挂载检查exit 2✓；增量更新29跳过/16更新/4复权重下✓；超时exit 3续传✓；baostock限流时响亮失败✓

## 2026-06-11 Phase 2 — 加权评分选股（v3-dev）

- sub_scores.py：11个连续子分数（0-1，向量化）；composite.py：加权排序+严格信号徽章
- daily_screener.py 重写：全市场5146只1.6分钟，结构化 screen_*.csv 输出
- 修复大盘指数bug（旧版误用平安银行CSV当上证指数）：fetch_index_data.py 新浪接口拉6大指数→data/index/
- 体系补建因子：YIN_VOLUME_34（3/4阴量线）、FOUR_BRICK_CYCLE（四砖周期，含第4砖减仓）；
  牵牛绳/掉进碗里/黄线价值/击穿对手盘/大哥还在等已存在于 knowledge_points.py（知行参数修复后自动生效）
- 验证：190 tests passed；2026-05-15 当日信号案例股 4/5 进全市场前5%（法狮龙#11/5146）

## 2026-06-11 Phase 2b — 大盘诊断 + 板块评分（v3-dev）

- market_score.py：三大指数 量能30+知行BS40+N型30 → 0-100综合分+仓位建议；
  历史回放方向正确（2026-04-09暴跌后26.5偏空轻仓 / 2026-01-06放量75偏多）
- sector_score.py：板块指数由本地日线等权聚合（彻底摆脱被封的东财接口），
  量能25+动量25+知行位置形态50 评分排名
- fetch_sector_data.py：新浪板块成员表49板块2967成员 → data/meta/sector_members.json（每周刷新）
- config/sector_tags.json：板块性质标签（顺周期/科技/消费/医药/防御/红利）
- daily_screener 集成：大盘建议+板块排名 sectors_*.csv+个股板块标注+sector_score列；
  目标日改为全市场最后日期众数+数据陈旧告警（修复只扫48只新数据股的偏差）

## 2026-06-11 Phase 3 — 回测 + 三大战法状态机（v3-dev）

- signal_validator.py + validate_signal.py CLI：全历史前向收益统计（B1: 71687信号/5日胜率47.5%——证实B1是入场过滤器需叠加确认）
- grid_search.py：邻域稳健性扫描；B1 稳健最优 J=10/DIF=-0.1，参数面平滑
- run_backtest.py --mode short 修复 NameError，全链路跑通
- playbook_engine.py：三大战法按权威定义重写为状态机（旧版0%覆盖→全部出交易）
  - **B1→B2→B3完整序列 94.7%胜率/+13.0%净收益（用户"B3确定性更高"经验获统计证实）**
  - B1→B2: 72.4%/+6.2%；卖出体系有效（S1卖点+23.2%、DD增强+11.4%）
  - 发现头号优化点：73%交易死于等B2期间止损过紧（price_ticks待网格调优）
- run_playbook.py CLI：逐笔交易CSV + 按信号类型/退出原因拆分统计

## 2026-06-11 Phase 4 — DeepSeek + 开源集成（v3-dev）

- llm/client.py：openai SDK 直连 DeepSeek（v4-pro推理/v4-flash批量），不引LangChain；
  需用户配置 DEEPSEEK_API_KEY（当前环境未配，模块运行时检测）
- llm/factor_gen.py：中文→因子管线（正则解析优先→DeepSeek兜底→AST白名单→沙箱冒烟→
  落盘 factors/generated/ 默认不启用）；恶意代码/shift(-n)未来函数拦截验证通过
- scripts/ai_review.py：Top10 AI研判（v4-flash单次调用，约¥0.1/天）
- factors/zoo_bridge.py：桥接 vibe-trading 452个面板alpha（Py3.14兼容验证通过），
  精选20个GTJA短周期量价alpha，真实数据96%覆盖
- TradingAgents 适配器已默认 deepseek-v4-pro + env key，无需改动
- cc finance：决策=有限集成（适配器模式用于板块财务层；美股数据源不用）

## 2026-06-11 Phase 5 — GUI 深度优化（v3-dev）

- 全新 alphapulse/ui/app.py（旧版存档 app_v3_legacy.py）：深色主题+红涨绿跌（#ef232a/#14b143）
- 顶部信息条：大盘综合分+档位+仓位建议+最新选股日+严格信号数
- 6工作区：选股雷达（进度条评分/徽章/板块筛选/行点击联动K线/子分明细）、
  个股K线（plotly蜡烛+白黄QL线+B1/量能B1/知行超短买点+S1/DD卖点标注+量副图）、
  大盘板块（三指数三维分项+板块强度排名）、信号验证（因子下拉一键回测+逐年胜率图）、
  参数搜索（网格结果+热力图）、AI工具（NL→因子+AI研判展示）
- .streamlit/config.toml 主题；.claude/launch.json 启动配置
- 浏览器截图验证：雷达页/K线页渲染正确（红涨绿跌、信号标注、法狮龙605318全形态）
- 已知小缺口：股票中文名待 share_capital 拉取成功后显示（东财接口当前被封）

## 2026-06-11 GUI v5 + 信号闭环 + ML（v3-dev）

**三层任务流重构**（用户确认信息架构）：
- 今日看板：大盘三卡(综合分/档位/仓位建议) + 指数三维分项条 + 板块强弱榜 + Top10信号卡片
- 选股工作台：左表右图单屏，点行刷K线，子分数明细条
- 研究优化：信号复盘/信号验证/参数搜索/ML形态/AI工具 五个子区
- 扁平设计系统 ui/style.py（卡片/KPI/横条组件，红涨绿跌仅用于数据语义）

**信号追踪闭环**：每日Top50入库→7日逐日表现→连涨≥2天归因（特征偏移+DeepSeek总结）
→沉淀候选因子描述+ML强化样本

**ML 双路线**：
- GBDT胜率模型：15万笔战法交易（按年切分），样本外Top10%分位胜率48% vs 基准36%；
  ml_score以0.15权重进评分体系；特征重要性榜与体系逻辑吻合（红肥绿瘦/振幅/量比居前）
- 形态相似度搜索：45个案例模板z归一相关匹配，案例间互匹配验证一致性
- sub_scores向量化重构（compute_sub_score_frame），训练从~100分钟降至0.5分钟

浏览器三层页面截图验证全部通过。

## 2026-06-11 选股列表增强（v3-dev）

- WEEKLY_MA_CROSS 因子：周线M5上穿M14（上一完整周对齐日线，无泄漏）+ 日线MA5>10>20多头排列；
  子分数 weekly_cross(0.08)/ma_bull(0.05) 进评分权重——B1加强因子（用户需求）
- 选股CSV新列：strategies（B1/量能B1/知行超短/周线金叉触发标签）、concepts（新浪概念板块）
- 工作台重构：列表评分/策略/板块/概念列，点行展开『选股依据+日K线』面板
  （B1六条件✓✗实际值/均线体系/量能B1要点/子分数全览）；看板信号卡带策略与概念
- 概念板块拉取：新浪175个，限流退避+增量合并
- 验证：Top股普遍带"周线金叉"标签（新因子生效）；GUI截图确认依据面板正确

## 2026-06-12 开源融合第一批 + 形态教学 + GUI修复（v4-fusion 分支，回退点 tag v3-stable）

**研究**（subagent 并行，日记 docs/research_journal/ 00-08）：
- 精读 daily_stock_analysis（42.1k星）+ qlib/chan.py/InStock/Sequoia-X/abu/ai-hedge-fund 共7项目
- 12条集成路线图（00_summary.md），剩余项归档任务#23

**融合实施**（每项带回测验证，见 08_integration_log.md）：
- ❌ RPS过滤B1（Sequoia-X）：6.3万事件AB回测显示单调负贡献——动量过滤与超跌买点逻辑相反，否决（负结果防系统变坏）
- ✅ pytdx直连备援（daily_stock_analysis）：baostock限流时增量更新兜底；不复权裸价靠重叠close一致性检查保护，隔离验证0.000%偏差
- ✅ 形态教学NL→ML：中文描述→DeepSeek标注函数→历史验证→案例确认→GBDT特征；"机构票缩量回调"端到端2331次命中

**GUI**：修复顶部标签被固定页头遮盖的致命bug（padding-top 1rem→3.8rem）；
看板加上证分时+日K小图；板块/概念K线弹窗（含工作台按钮入口）；
研究区重构（参数动态控件+5步工作流+因子权重编辑器+热力图美化与说明）；
修复板块聚合K线concat日期乱序bug

## 2026-06-12 知识库网站完成（v4-fusion）

`docs/knowledge_site/` 12 页静态站建成（零依赖，双击 index.html 或 `python3 -m http.server` 即用）：
- 4 阶段渐进：L1 基础(因子/回测/胜率) → L2 经典(评分/网格/仓位) → L3 ML(GBDT/标签/评估) → L4 AI(LLM/案例)
- 互动演示 11 个：IC权重分配器、过拟合曲线、期望值计算器+资金曲线模拟、两因子合成、网格热力图+稳健分、凯利仓位、决策树切分、随机vs时序切分、分位胜率直方图、NL→因子安全链可视化、RPS否决真实回测曲线
- 即时判分测验 33 题（每章3-4题，全对自动标记✔）
- 术语 tooltip 词典 ≥40 条；学习进度 localStorage 持久化
- 设计：深色+红涨绿跌、卡片化、与 GUI 一致审美

浏览器验证：首页/章节页渲染完美；演示交互正常响应；测验判分逻辑+✔标记+localStorage 写入全通；
所有 JS 语法清白、零坏链。

## 2026-06-15 用户四项需求（v4-fusion）

1. **黄线硬过滤**：rank_all `require_above_yellow`（默认开）— 选股铁律"价站上知行黄线才选"。4218只→886只站上黄线，Top50零违规。
2. **交互式选股**：选股工作台加参数面板（黄线开关/最低分/仅严格信号/板块强度/出票数 + 8个因子权重滑杆）+「重新选股」按钮。daily_screener 落盘全市场 `factor_frame_DATE.csv`，GUI 基于缓存因子帧秒级重排。
3. **15:30收盘流水线 + 更新时间**：`eod_pipeline.py`（更新→选股→追踪）写 `last_run.json`；plist 01:30→15:30；看板顶部显示数据/选股更新时间。
4. **投资判断板块**（第4主Tab）：`analysis/concept_miner.py` — B1信号股概念分布 + 概念指数位置量化（区间分位/黄线/动量）+ DeepSeek 产业链投研（上下游/位置研判/催化/操作建议）。验证：DeepSeek 正确识别专精特新=中上游隐形冠军、光伏=中游产能过剩，今日优选专精特新（5只B1集群均分91.7）。

附带修复：板块/概念指数日收益裁剪±21%（剔停牌复牌跳空，光伏动量178%→-11%）；weekly_ma_cross 日期混合格式兼容。回归 11 tests passed。

## 2026-07-02 Agent Team 阶段二 + 回测验证（v4-fusion）

**阶段二**（a310ac1）：debate.py（v4-pro Bull/Bear/仲裁，触发线65分，JSON容错，失败回退P0）
+ fusion.py（TrustTrade贝叶斯融合，中立=恒等）+ risk.py（Buy20%/增持12%、市值<10亿×0.5、
偏空×0.5、限5只）+ CLI --debate + GUI投资判断Tab研判区。真实冒烟：300715 仲裁 bullish62
→ 65分升76(Buy 仓20%)；辩论文本质量高（空方精准攻击GBDT胜率/板块无共振）。

**回测验证**（dd4d850，用户/goal：结果以回测为准）：
- backtest_agent_team.py 全市场向量化（5184只×1年 3.8分钟），四标准+基线+生产口径Top10
- **负结果**：固定持有期六项全部未达标（超短次日红盘47.3% vs 基线48.4%、B1三日>5%
  12.7% vs 11.8%、强板块周涨2% 39.9% vs 40.3%、研判Top10五日胜率47.3%）
- **交叉验证**：同窗口交易级 B1B2 507笔 75.5%/+7.1%、B1B2B3 30笔 100%/+16.6%
  → 优势由B2确认+卖出体系收割，固定持有期是错误度量；选股列表=候选池非当日买入清单
- patterns.py 战法序列状态机（B2确认=多头/B1候B2=中性），agent与回测严格共源
- 研判标准修订为交易级：Buy/增持按playbook执行胜率≥55%且净均值>0 —— 本窗口✅通过
- 再证头号优化点：B1等B2止损过紧（3700笔-1.8%）→ 路线图 price_ticks 网格

## 2026-07-02 路线图#6启动 — 止损口径网格（头号优化点闭环）（v4-fusion）

- playbook_engine 增 stop_pct 百分比止损（向后兼容，绝对价位对高价股结构性过紧：百元股3价位=0.03%）
- grid_search_stop.py 网格 0.5%~15%：单调渐近，价格止损在超跌买点体系中系统性截断赢家
- **全市场验证（5184只）：基线全历史净均值-0.116%（负期望！）→ stop_pct=0.10 转正+0.101%，
  近1年+0.235%→+0.847%（3.6×），止损死亡73%→5%，B2确认交易+39%**
- 采纳 stop_pct=0.10（保留灾难止损），写入 best_params.json PLAYBOOK_B1B2B3；
  run_playbook --stop-pct 默认读 best_params
- 尾部代价 p5 -5.6%→-9.9%，由单票≤20%仓位控制；GBDT需按新口径重训（队列）

## 2026-07-04 系统体检+基础设施治理+调参循环（v4-fusion）

**根因修复**：外接盘3次掉线(7-3流水线全失败) → 日线迁内置盘data/day/(523MB)+DATA_DIR切换;
launchd治理:15:30三任务并发(限流打架+CSV竞态)+凌晨双跑 → 禁用3冗余,保留eod_pipeline+daily-auto。
**调参**:b2_wait网格 → 每持有日收益w=8见顶(+0.041%/日,近1年+1.68% vs w5 +0.85%),
best_params落盘+patterns同步;auto_retune.py每周日04:00邻域周检(只建议不自动改参),实测邻域最优。
**UMP**:时间外推0/40失败簇+敏感性6配置全不过 → 否决接入(止损修复已吸收其攻击面),负结果入日记。
**人格插槽**:config/personas/*.md即插即用(金渐成由外部AI供给)。数据补至7-3(85%),
recover_stale后台修复除权卡死群。234 tests passed。

## 2026-07-06 路线图#3 因子表达式引擎 + Alpha158 因子库（v4-fusion）

**动机**：新因子成本从"写.py+沙箱exec"降为"一行DSL字符串"，收窄DeepSeek生成幻觉面。
**引擎**（factors/expr_engine.py）：ast.parse(mode=eval)+节点白名单+递归树遍历求值，
全程无exec/eval——无沙箱逃逸面。算子表qlib名为主+通达信别名（MA/HHV/LLV/REF/SMA…）：
时序Ref/Delta、滚动统计17个、回归Slope/Rsquare/Resi（convolve闭式OLS）、双序列Corr/Cov、
平滑EMA/WMA/SMA(通达信ewm)、逐元素If/Cross/Greater/Less等。参数运行时绑定（j<j_threshold）。
歧义规避：Max/Min/HHV/LLV固定滚动窗口语义，成对逐元素用Greater/Less。
**Alpha158**（factors/alpha158.py）：qlib Alpha158DL全套158表达式（KBAR9+价格4+滚动29×5窗口），
compute_alpha158(df) 0.05s/股。逐条核对qlib原定义（IdxMax用argmax+1的qlib惯例、
SUMP/RSV/CORD/WVMA分母、Slope/Resi闭式解）。
**接线**：factor_registry.compute_factor未知因子兜底查expressions.json；
factor_gen新增generate_expression()——DeepSeek输出JSON表达式而非.py，校验失败回喂重试；
生成因子enabled=False不自动进选股（沿用安全规约）。
**IC验证**（scripts/alpha158_ic.py）：797股×500日面板(39万股日/1963交易日)日截面Spearman IC，
132/158因子|meanIC|≥0.02、94个|ICIR|≥0.3；Top均值回归型(QTLD60/MA60/QTLD20/VMA60)
IC≈0.067 ICIR≈0.45-0.61，与底部挖掘体系风格一致 → reports/alpha158_ic.md。
**验收**：知行白线/黄线/洗盘四线/MACD DIF/KDJ-J 表达式对拍现有模块逐点allclose✅；
Alpha158全量跑通✅；安全拒绝矩阵（import/属性/下标/Ref负数/内省/内建）✅。
**对抗审查**：Workflow五维审查agent全撞会话额度上限 → 改自跑真实验证：全158因子+21算子
截断因果性（截尾不改前段值+NaN掩码一致，含volume=0停牌样）零泄漏、19条沙箱逃逸全拦截、
_extract_json四形态鲁棒、名字冲突FACTOR_REGISTRY优先——固化为回归测试。
**设计取舍(非bug)**：IdxMax暖机用满窗(qlib用min_periods=1,IC侧不影响)；WMA用权重1..N(通达信语义)。
**测试**：test_expr_engine.py 48用例；全仓286 passed零回归。
设计spec: docs/superpowers/specs/2026-07-06-expr-engine-design.md。

**#3进阶验收 — Alpha158入LGBM的AUC前后对比**（scripts/alpha158_lgbm_ab.py，1199股/21.1万笔交易，
同切分≤2023训/2024验/2025+测、同超参，只报告不覆盖生产模型 → reports/alpha158_lgbm_ab.md）：
- A基线27特征: valid AUC 0.5565 / test 0.5501 / test Top10%胜率 0.5021
- B基线+158:   valid AUC 0.5488 / test 0.5568 / test Top10% 0.5045
- C仅158:      valid AUC 0.5421 / test 0.5542 / test Top10% 0.5034
- **结论=非稳健**：B 的 test AUC +0.0067 但 valid AUC −0.0077，方向不一致=噪声/风格波动，
  按 ic_weight_tuning "双指标均改善才采纳" 标准**暂不合入生产**（负结果，诚实入账）。
- **真发现**：C（仅Alpha158零手工特征）test AUC 0.5542 ≈ A 的 0.5501，通用因子库"免费"
  复现了手工27特征的信号量 → 表达式引擎降低了新因子边际成本这一结论被数据支撑。
- 后续可试：Alpha158 只挑高|IC|子集(reports/alpha158_ic.md Top20)入模，或对158做截面中性化，
  减少过拟合再评估；生产 pattern_gbdt.pkl 保持现状。
下一队列：#5筹码分布 / #4信号链状态机。

## 2026-07-06 路线图#5 筹码分布因子（CYQ成本分布重建）（v4-fusion）

**动机**：给"底部挖掘"补持仓成本维度（现有CHIP_CONCENTRATION只是振幅代理，非真实成本分布）。
**算法**（factors/chip_distribution.py，InStock CYQ）：三角分布沉积+换手衰减逐日演化筹码——
`chips_t=chips_{t-1}*(1-turn_t)+deposit_t*turn_t`，deposit按三角分布(峰在(H+L+C)/3)摊到[low,high]。
输出profit_ratio(获利盘=现价以下筹码占比)/avg_cost/conc90(中央90%筹码带宽/现价)。
**向量化**：exp-cumsum闭式(减decaylog[-1]防溢出，公共因子按日归一抵消)，5.9ms/股；
配逐日递归参考实现_compute_chips_sequential对拍——机器精度1e-15一致。因果由构造保证。
注册 CHIP_PROFIT_LOW(获利盘<15%)/CHIP_SINGLE_PEAK(conc90<12%)/CHIP_DISTRIBUTION(三指标)。
**AB验证**（scripts/ab_test_chip.py，799股/7.2万B1事件→reports/ab_chip_b1.md）=**正结果**：
- 单峰密集(conc90)提纯最强：纯B1净胜率5日44.7% → conc90<0.3 **46.5%**(留样1.38万,10日净均值转正+0.43%)
  → conc90<0.2 48.2%(留样4699)。**推荐操作点conc90<0.3**(兼顾提升与留样)。
- 获利盘profit_ratio<0.15→45.5%、<0.10→46.2%(5日净均值翻正+0.11%)，单调有效。
- 最紧阈值(conc90<0.12样本493/组合过滤)过度过滤致均值转负——报告如实标注甜点区，不夸大。
- 与Alpha158-LGBM(非稳健)对比：筹码因子是本会话**首个干净正结果**，验证"低位单峰=真底"命题。
**测试**：tests/test_chip_distribution.py 11用例(向量化==逐日/固定网格截断因果/涨跌方向/单峰density/一字板)。
**顺带**：新因子conc_threshold暴露test_all_factors_no_error盲区(只调基础compute)→改为按compute_func忠实
分派+签名过滤参数，首次覆盖compute_func路径。发现既有缺陷(compute_factor对7个knowledge_points因子
TypeError，factor_name透传)已开背景任务，未在本会话修(超范围)。全仓297 passed。
设计spec: docs/superpowers/specs/2026-07-06-chip-distribution-design.md。
下一队列：#4信号链状态机 / 把conc90<0.3并入B1选股(需用户确认启用) / #6洗盘模板。

## 2026-07-06 路线图#4 信号链状态机 seq_id 贯穿（v4-fusion）

**缺口**：b1_b2_b3_strategy.generate_signals 产出 B1/B2/B3 是独立行(B2只判"过去5日有B1")，
不记seq_id串链→无法按序列聚合、无法把B2/B3收益归因到源头B1。
**改造**（strategies/b1_b2_b3_strategy.py，纯后处理不改触发）：assign_seq_ids 因果单次扫描——
一B1开序列(seq_id=symbol:date)，首个窗内B2继承其seq、首个B3继承B2；按(日期,阶段)键避免
同日既是某链B2又是新链B1的冲突。三类信号行新增seq_id/parent_stage/seq_root_date(向后兼容)。
语义与playbook_engine.simulate_b1b2b3严格共源(一B1→首B2→首B3)。
**序列分析**（scripts/sequence_analysis.py，799股/4万B1序列→reports/sequence_analysis.md）：
- 漏斗：B1→B2 仅5.9% → B3 0.2%(占B2的3.6%)，B1极permissive、确认极稀。
- **诚实拆解(防误读)**：①孤立B1(占94%)固定5日净胜率39.2%/净均值-0.82%=负期望(印证信号日无优势)；
  ②确认序列从B1日起88.8%/+7.2% 但**是事后条件统计**(需持有到确认才兑现,不可ex-ante挑)；
  ③全B1等权固定5日**混合ex-ante期望42.1%/-0.35%仍偏负**→序列价值不来自固定窗口、需simulate的
  持有到卖出+stop_pct机器把赢家跑出来；④追买B2确认42.3%/~0=折价严重(印证既有hold_matrix结论)；
  ⑤B3入场最强(10日53.5%/+2.41%)。
- **94.7%复核**：该数为交易级(持有到S1/DD卖出)，与固定前向窗口不可直接对齐，B3序列样本86偏小；
  定性结论成立=确认越深条件胜率单调抬升、优势在确认序列而非孤立信号，但兑现依赖完整战法。
**测试**：tests/test_signal_chain.py 9用例(满链同seq/孤立B1/超窗/两链不串号/首个B2确认/截断因果/
向后兼容)。自查修复混合期望重复计数B3序列。全仓306 passed零回归。
设计spec: docs/superpowers/specs/2026-07-06-signal-chain-seqid-design.md。
下一队列：把conc90<0.3并入B1选股(需用户确认) / #6洗盘模板 / #7MACD背驰 / #10K线合并。

## 2026-07-06 路线图#6 洗盘段模板 + #7 MACD面积背驰（v4-fusion）

**#6 洗盘段量化模板**（factors/washout_template.py，Sequoia涨停洗盘三段式）：
washout_ok(df,anchor_idx,max_vol_ratio,anchor_price_col)标量(锚后每日vol<ratio×锚量且low>锚价)
+ compute(爆量阳锚→缩量不破锚→首个再确认阳线,向量化因果)。注册WASHOUT_SEGMENT。
把"缩量阴/3-4阴量线"参数化，统一服务B3锁仓与单针(是yin_volume_34的通用化,不替换)。
**#7 MACD面积背驰**（factors/macd_divergence.py，chan.py divergence_rate）：
红柱(hist=2(dif-dea)>0)分段,每段记面积与price_peak;价创新高但area/前段<divergence_rate→
死叉日DD顶背离(段末死叉日触发,因果)。注册MACD_DIVERGENCE(risk)。是dd_sell_signal的升维补充。
**网格验证**（scripts/grid_factor_forward.py 通用单因子参数网格×前向净收益vs随机基准,800股）：
- #6 max_vol_ratio∈{0.4,0.5,0.6,0.75}→reports/grid_washout_segment_max_vol_ratio.md：
  **标量入场未超基准**(最优0.4:5日44.1% vs基准45.4%)——追买green candle,与B2追买折价同因;
  网格给最优缩量上限max_vol_ratio=0.4(越严越好,单调),作B3/单针过滤部件用。
- #7 divergence_rate∈{0.7,0.8,0.9,1.0}→reports/grid_macd_divergence_divergence_rate.md：
  **卖点有效**——信号后5日净胜率44.7% < 基准45.4%、10日净均值转负(-0.11~-0.17 vs基准+0.28),
  顶背离后确实走弱;单调:divergence_rate越紧走弱越强。诚实:前向走弱代理非完整持仓卖出模拟。
**测试**：tests/test_washout_macddiv.py 14用例(锚场景/背驰正负例/死叉日对齐/面积手算/因果/单调)。
全仓320 passed零回归。设计spec: docs/superpowers/specs/2026-07-06-washout-macddiv-design.md。

## 2026-07-06 路线图 #10/#8/#12 收官（v4-fusion）— 集成路线图12项全部完成

**#10 K线包含合并预处理**（utils/kline_merge.py，缠论去毛刺）：merge_klines 方向定向
（向上取高高/向下取低低）逐根因果 + map回原始日历。**AB(800股)正结果**：长下影探底信号
原始vs合并→信号58196→41724(-28%去毛刺)、5日净胜率43.3%→46.9%(+3.6)、净均值转正。
去掉的是噪音,形态更稳定。opt-in不改N_STRUCT/单针/砖型默认(避免golden回归)。8用例。

**#8 统一信号协议SignalOpinion**（ranking/signal_opinion.py）：source/signed/confidence +
aggregate(死区+置信度加权+UMP硬否决)+from_rule_ml。显式化现有隐式统一(composite已IC权重合
规则+LGBM),补死区。**AB(800股/39万股日)中性结果**：死区聚合Top50 5日胜率50.4% vs线性
composite基线50.0%(Δ+0.4噪声内),死区0.5更差→现行0-100排序已近最优,不必重构,协议保留供
未来接LLM/其它源。不纳UMP(已否决)。11用例。

**#12 杂项增强包**：①Hurst分流(factors/hurst.py结构函数法120窗,注册HURST)——标定发现对
趋势/随机游走分辨弱(有限样本偏差)、只清晰识别均值回归轴;**AB(800股)分流效应全在噪声内**
(B1低-高+0.3pp,砖型-0.1pp)→不推荐硬分流,诚实记录。②CSRankNorm标签(ml/label_transform.py)
按日截面排名去beta,测试证下跌市raw正样本率<0.3而CSRankNorm恒≈50%;完整LGBM重训AUC留后续。
③增量数据/推送:daily_update/recover_stale/smart_downloader/feishu_bot已就绪,push阻塞于用户
未配FEISHU_WEBHOOK_URL(不重建)。8用例。

**本会话累计完成路线图 #3/#4/#5/#6/#7/#8/#10/#12 共8项**（+既有#1#2#9#11=集成路线图12项全清）。
全仓347 passed零回归。诚实结论分布：正结果=#5筹码conc90/#7 MACD背驰卖点/#10 K线合并；
中性/负=#3 Alpha158-LGBM/#6洗盘入场/#8信号协议/#12 Hurst分流(均如实入账未夸大)。
下一步：把已验证正收益件(conc90<0.3筹码过滤 / K线合并预处理 / MACD背驰卖点)接入战法主干
(需用户确认,别自动改选股/卖出口径) / Alpha158高|IC|子集入模 / vnpy里程碑回测验证。
## 2026-07-10 数据更新可靠性治理（v4-fusion）

**根因链**：07-07体检发现本地主盘停07-03。①配置分裂：daily-update.plist残留
ALPHAPULSE_DATA_DIR指向外接冷备盘(07-05迁盘遗留)→定时更新外接盘、系统读本地盘(已修+重载)。
②断点污染：覆盖率0%仍无条件写满done_index→一次坏运行锁死当天重试(07-07/07-09两次复现)；
修为断点绑定(运行日,latest)、失败清断点、超时保留续传点、_coverage改>=。
③调度撞15:30收盘高峰：baostock限流+pytdx当日K线未出(16:00连T-1都缺)→新增22:00
update-retry launchd(只跑数据不重跑选股)，与②配合：下午失败晚间自愈、下午成功晚间补当日K线。
**加固**：只摄入≤latest已确认K线（盘中运行时pytdx形成中半截K线一旦写入将被永远跳过）。
微测：_coverage(>=/None安全)+断点三态(续传/新latest失效/跨日失效)全过。

## 2026-07-11 四维体检修复队列 C1-C7（v4-fusion）

体检（选股逻辑/运行流程/回测/策略选择）发现4真bug+10隐患+10优化点，全部排队修复：
- **C1 选股正确性**：①数据部分更新日"最新股票反被整批剔除"→按目标日截断对齐（07-10实测1572只被误剔）；②严格信号异常逐个隔离+计数汇报（原一坏全灭且无声）；③raw_score跨日可比列；④MD日报补单针、strategies剔除周线金叉；⑤市值缺失>20%告警。
- **C2**：移除大盘档位乘数——min-max后统一乘系数不改排序，只会空头档推出>100假分数。
- **C3 回测引擎**：①修估值bug（候选股行情误套全部持仓→仓位失真）；②信号日收盘成交改次日开盘+滑点；③开盘涨停(≥9.8%)/停牌跳过；④max_hold_days=20到期离场；⑤docstring注明幸存者偏差。
- **C4 夜场去假**：02:00报告改用追踪库真实成功率（原mock_signals假数据每天推飞书）；参数求和假优化下线。
- **C5 流程加固**：22:00升级为完整流水线（15:30时baostock未发布当日K线→下午选股永远T-1；22:00数据齐重选推"晚间版"）；track超时300→600s；周末守卫；run_with_timeout直读.env缺盘告警兜底。
- **C6 砖型图法上岗**：BRICK_THREE_TYPES接入第5严格信号（尾窗260行实测2.3ms/股全市场+12s；best_params网格参数回流）；家族映射砖型图法=[知行超短,砖型图]。
- **C7**：FactorWeighter空权重拒绝覆盖（防加载失败清空B1_SCORE)；筹码conc90/获利盘+MACD背驰以信息列入帧（推送标⚠️背驰），权重待IC积累；README策略地位表；CLAUDE.md回测框架描述改实情。

**遗留（методология，需专项）**：网格搜索walk-forward化（B1_B2_B3 hit_rate=1.0是样本内过拟合信号）；退市股universe（幸存者偏差）；vnpy_strategies接线或删除；K线合并预处理接入生产前需专项AB。

## 2026-07-12 遗留四项收官 D1-D4（v4-fusion）

- **D1 walk-forward**：`walk_forward.py`+`run_walk_forward.py`（锚定扩张+6月滚动8验证窗，口径=实盘同源5日+5%，robust=0.5中位+0.5最差，链式流程回测无偏估计）。B1_B2_B3 稳健参数 j23/pct7/vol1.5/conf0.7（链式OOS中位24.0%/最差17.7%）；BRICK vol_nj1.3/vol_bo1.5/consol5/amp15（26.2%/20.6%）→ best_params.json（带_source，旧参存provenance）。旧网格 hit_rate=1.0 确认为"案例股覆盖率"型过拟合（评分里无前向收益）。
- **D2 退市股**：fetch_delisted.py 239/239 零失败→外接盘 delisted/（与生产隔离）；run_backtest --include-delisted 按真实占比抽样并入（防权重放大10倍高估偏差）。量化：真实占比下年化Δ≈0、胜率-1.1pp、回撤-3.3pp（集中持仓策略偏差有限）；占比失真组(-14.7pp)为上限示意。**附带重磅**：诚实引擎下 B1 v1 年化-12.4%，README旧+9.31%作废标注。
- **D3 vnpy**：vnpy_strategies/ 删除（零引用，git可回溯），CLAUDE.md 阶段五/六改自研引擎+walk-forward语义。
- **D4 K线合并生产AB**（989股×2024-2025，前向收益均在原始价评价）：知行超短 +4.4pp/z=6.79/平均5日收0.72%→1.40% → 接入（settings.KLINE_MERGE_ZHIXING）；砖型图 +1.5pp/z=1.76 未过门槛不接。
- **顺带修**：策略信号帧索引=输入行标签（非date）——C6 的 sig_brick3 曾因此永远False，已修（500股日抽查命中2次≈0.4%/日）。

---

## v5 P0 — 2026-08-02（分支 codex/v5，基线 v4-fusion@7c1dc31）

**背景**：全目录审查（约42K行）发现三类系统性问题——N 型结构未来函数、
胜率口径分裂（94.7% 条件胜率 vs 实盘追踪 19.7%）、硬闸门关闭时无人值守静默空转
近三周（07-16 起零选股产物但 last_run.json 记 ok:true）。538 单测全过，问题在接线/口径。

### P0-1 N 型结构因果化（`n_struct.compute_causal`）
- 根因：`argrelextrema(order=5)` 判定枢轴需前后 5 根K线 → `needle_washout` 的
  B→C 回调段标记、`b1_b2_b3` 的 N_STRUCT=0 过滤都在信号日用了未来信息，
  案例回放命中率系统性虚高。
- 修复：新增 `compute_causal`——结构只在确认时点公布（C/D 枢轴+order）；
  phase 2 = 回调确认后的恢复窗口（"回调进行中"在实盘天生不可知，这是诚实语义）；
  phase 1 不实时存在（需等 C 验证才知是 N 型）。`compute()` 保留但标注废弃（仅兼容）。
- 消费方：`needle_washout`（删除 `_build_n_structure_context`）、`b1_b2_b3`
  （改用因果标签，原过滤近乎惰性语义保留）。
- 对抗测试（152 项）：**截断不变性**——t 日信号不得被追加未来数据改变（旧版必失败）；
  旧版泄漏演示（A/B/C/D 枢轴标签全部提前公布）。

### P0-2 胜率口径统一为 realized
- `evening_review` / `daily_auto_run` 夜场报告主数字改为追踪库已实现收益
  （持有5日/收盘破5%止损/扣往返费≈0.35%），"曾触及+5%"仅作对照。
- 决策固化：B1B2B3 已证负期望（08-02 周检：留出窗 9 组参数全负，最好 -41.69% 年化），
  **调参救不了 → 重做信号**；auto_retune 维持"负期望不覆盖参数"守卫。

### P0-3 硬闸门关闭留痕
- `daily_screener` 闸门关闭写 `reports/gate_closed_<date>.json`（含原因/时间）；
  闸门重开自动清除当日标记。
- `eod_pipeline` 读标记 → `last_run.json` 增加 `gated/gate_reason` + "硬闸门(空头区间)"
  步骤；夜场报告提示"🚧 硬闸门关闭中·不开新仓"。

### 文档同步
- AGENTS.md / CLAUDE.md：新增 v5 分支说明、因果铁律、realized 主口径、
  修正过时的 CLI 与调度描述（14:30/15:30 → data_catchup 15:35 链路）。
- README.md：命令表对齐（evening_review / QMT 待修标注）+ v5 说明。

### 结果与验证
- 全量测试：**689 passed / 2 skipped**（`test_get_strong_sectors_returns_list` 超时为
  既有网络依赖问题，东财接口被封且无超时，与本次改动无关）。
- 对抗检查：新增 156 项测试全过；旧版泄漏演示确认 compute() 确实提前公布枢轴。

### 已知遗留（P1）
- `knowledge_points.py`（KEY_SUPPORT 支撑价）与 `utils/filters.py`（web/friday 遗留路径）
  仍调用非因果 `n_struct.compute`——未接每日生产信号，但需在 P1 替换为因果版。
- QMT 导出链路：`export_qmt_csv.py` 无法消费 `screen_*.csv`（缺 date/signal 列，实测崩溃）。
- 每日 IC 自动调权闭环断裂（写键/读键/消费键不一致，nightly 为 no-op）。
- `run_backtest` 静默吞错、short 模式口径、risk_monitor 三个假规则（见审查报告）。
- 数据停更 07-28（07-29~31 三个工作日 catchup 无记录，机器睡眠/断网待查）。

## v5 P1 — 2026-08-02（与数据停更修复同批）

### 数据停更修复（根因：整机关机，非代码故障）
- 根因确认：`kern.boottime` = 08-02 19:02，机器自 07-28 22:50 断电至 08-02 19:02；
  launchd 的 StartCalendarInterval 错过窗口不补跑 → 07-29~31 三个工作日漏更。
- 立即修复：`fetch_index_data.py` 指数追平 07-31 + `daily_update.py` 后台断点续传
  （baostock 限速约 40-80 只/分，全市场约 2 小时，进度在 `logs/update_progress.json`）。
- 韧性修复：`config/com.alphapulse.data-catchup.plist` **RunAtLoad=true**——
  每次开机/登录立即触发一次自愈（周末守卫照常跳过），已同步安装并 reload 验证。

### P1-1 risk_monitor 三个假规则
- 个股回撤基准：全历史最高 → **近60个交易日高点**（旧版早年大牛股永久触发假警报）。
- "单日亏损>5%"：实现本是累计浮亏 → 规则改名"个股浮亏>5%"对齐实现。
- 组合回撤：分母持仓成本 → **总资金**（旧版 20% 仓位上限下几乎永不触发，是死规则）。
- 顺带优化：每只股票 CSV 只读一次（旧版逐规则重复读 3 次）。

### P1-2 run_backtest 静默吞错
- 信号预计算 `except: pass` → 计数上报 + 错误率 >10%（或 >50 只）直接中止，
  不再"系统性故障=零信号回测成功"；load_stocks 解析失败 >20 只告警；
  `--mode short` 的 `signal.astype(bool)` 会把 -1 卖信号当买 → 改 `== 1`。

### P1-3 QMT 导出接口打通
- `export_qmt_csv.py` 兼容 `screen_*.csv`（无 date/signal 列 → 日期取文件名、
  整表视为买入候选、按 rank 取前5、close 列取价）；实测 07-16 screen CSV 正常出单。
- 旧 signals.csv 格式（date/signal，含 -1 卖出）保持兼容。

### P1-4 因果化收尾
- `knowledge_points.compute_key_support`：A 标签 → `compute_causal` 的 a_price 列。
- `utils/filters.has_n_structure`：`compute()` 标签 → `compute_causal` 的 phase。

### P1-5 nightly IC 调权死代码下线
- `daily_auto_run` 原对 B1B2/BRICK/NEEDLE 三个空策略名调权（消费方是 B1_SCORE，
  写键/读键/消费键永不对齐，纯 no-op）→ 移除；IC 调权唯一入口 =
  `scripts/ic_weight_tuning.py --apply`（手动，写 B1_SCORE）。

### 验证
- 新增 14 项 P1 测试全过；全量套件回归通过（693+14，网络依赖测试仍 deselect）。
- 后台补数进行中（done_index 进度可查 `logs/update_progress.json`）。

## v5 大重构 — 2026-08-02（纯选股版）

**用户决策**：去掉全部量化交易部分，只保留选股；从第一性原理构建
"仅针对选股成功率的回测+优化系统"。

### B1B2B3 原理溯源（结论：来自原始策略体系）
- `docs/trading_system.md` §2 战法一明确记载（用户口述体系）：
  B1 = 形态与资金共振的底部买点（B1 公式 1.1/1.2）→ B2 = B1 后的**放量阳线**
  确认加速 → B3 = B2 后的**缩量阳线无明显破位**（主力锁仓，确定性更高）。
- 因此 B1B2B3 不是凭空发明的，但旧实现混入了交易模拟（等 B2 期间止损、
  持有期退出），其"94.7% 序列胜率"是条件胜率，已随交易引擎下线；
  v5 中 B1/B2/B3 退化为**纯选股确认链**（信号分级，不模拟持有）。

### 交易侧移除清单（git 历史可回溯）
- 模块：`alphapulse/backtest/{portfolio_eval,short_term_bt,bt_storage}.py`、
  `alphapulse/risk/`（position_manager）、`alphapulse/strategies/playbook_engine.py`、
  `alphapulse/agent_team/risk.py`
- 脚本：run_backtest / risk_monitor / export_qmt_csv / run_playbook / hold_matrix /
  grid_search_stop / backtest_agent_team / auto_retune / run_two_stage_opt /
  backtest_cases{,_v2,_dates} / grid_search_b1b2b3
- 定时任务：weekly-retune（auto_retune）已 unload 并移出 LaunchAgents
- 测试：test_position_manager / test_portfolio_eval / test_risk_monitor_discipline /
  test_v3_backtest / test_auto_retune_gate / test_v5_p1_batch（交易部分）
- 依赖修补：start_web 三个回测 API → 纯选股成功率；pattern_model 训练标签 =
  选股机会命中（原 PLAYBOOKS 交易标签）；friday_screener/grid_search_brick_types
  内联加载器；agent_team 移除风控层

### 新系统：纯选股成功率回测 + 优化（第一性原理）
- 规格文档：`docs/v5_screen_system.md`
- **主口径 = 机会命中**：信号日收盘后 H（默认5）日内任一收盘 ≥ +5%；
  纯涨跌判断，无交易模拟
- **随机基线**：同信号日全体股票命中率；超额 ≤0 的策略无选股价值，
  优化默认拒绝写入 lift < 3pp 的参数
- 因果门禁：screen_bt 抽样截断不变性；右删失处理；--include-delisted 修正幸存者偏差
- 组件：`alphapulse/screening/{evaluator,strategies}.py` + `scripts/screen_bt.py`
  （全策略成功率报告）+ `scripts/screen_optimize.py`（walk-forward 稳健分+
  链式回测+基线门槛→best_params.json 带 provenance）
- 覆盖 10 策略：B1_FORMULA / B1_B2_B3 / BRICK_THREE_TYPES / NEEDLE_WASHOUT /
  BRICK_ULTRA / NEEDLE / B1_ENHANCED / ZG_B1_BRICK / VOLUME_B1 / ZHIXING_ULTRA

### 验证
- 全量测试 **631 passed / 2 skipped**（网络依赖测试继续 deselect）
- 新增 10 项新系统测试（口径/基线/样本门槛/右删失/注册表/CLI 端到端）
- 文档：AGENTS/CLAUDE/README 全部改为纯选股体系；里程碑改为成功率口径
- 数据补数仍在后台进行（约 1/4 完成，见 logs/update_progress.json）

## v5 纯选股系统首次全量运行 — 2026-08-02 晚（数据追平后）

**数据状态**：个股/指数已全部追平至 07-31，覆盖 96.7%（其余为真停牌）；
eod_pipeline 实跑 `data_fresh=true, gated=true`（零轴门 DIF=-58.41）。

### screen_bt 全策略成功率（594 只 + 退市股，口径：5日内任一收盘≥+5% 机会命中）

| 策略 | 信号数 | 成功率% | 基线% | 超额pp |
|---|---|---|---|---|
| B1_B2_B3 | 5,559 | 28.21 | 22.87 | **+5.34** ✅ |
| ZHIXING_ULTRA | 20,272 | 28.71 | 23.56 | **+5.15** ✅ |
| VOLUME_B1 | 1,643 | 28.91 | 24.66 | **+4.25** ✅ |
| B1_ENHANCED | 76,001 | 24.60 | 23.70 | +0.90 |
| BRICK_ULTRA | 88,594 | 25.41 | 24.57 | +0.84 |
| BRICK_THREE_TYPES | 35,566 | 24.37 | 24.85 | -0.49 |
| ZG_B1_BRICK | 9,193 | 22.84 | 23.20 | -0.36 |
| B1_FORMULA | 54,030 | 22.92 | 23.70 | -0.79 |
| NEEDLE_WASHOUT | 798 | 21.43 | 22.20 | -0.78 |
| NEEDLE | 159 | 12.58 | 21.69 | **-9.11** ❌ |

**关键洞察**：
- B1_B2_B3 作为**纯选股信号**超额 +5.34pp——此前"负期望"结论来自交易包装层
  （等 B2 期间 -10% 止损杀掉 73% 交易），信号层本身有价值；交易层已移除，
  现在以信号命中率为唯一评价。
- NEEDLE（经典单针）超额 -9.11pp，是 10 个策略里唯一显著负值 → 该策略应降级/重做。
- 因果门禁全部通过（抽样截断不变性）。

### screen_optimize B1_B2_B3（54 组参数 × 8 验证窗）
- 最佳稳健分 21.8%（中位 26.3% / 最差 17.3%），基线中位 20.1% → 稳健超额仅 **+1.7pp**，
  **未过 3pp 门槛，拒绝写入 best_params**（在任参数 j23/pct7/vol1.5/conf0.7 仍为 Top2）。
- 链式样本外：24.1 / 13.0 / 25.3 / 35.6 / 29.3 / 28.1 —— 2023H2 仅 13%，边缘不稳定。
- 结论：全样本点估计有 +5pp 超额，但按窗稳健估计只有 +1.7pp → **信号有真实但脆弱的
  边际优势，距离里程碑（+5pp 稳健）需要策略改进**，不是参数问题。
- 修复 screen_optimize 链式表成功率 ×100 单位 bug（曾显示 2406%），加回归断言。

### 里程碑对照（v5 选股口径）
- ✅ 全样本：B1_B2_B3 / ZHIXING_ULTRA / VOLUME_B1 超额 ≥ +5pp
- ⬜ walk-forward 稳健超额 ≥ +3pp：未达标（B1_B2_B3 只有 +1.7pp）
- ✅ 因果门禁全过；闸门留痕告警生效
- 待办：重做 NEEDLE；提升 B1_B2_B3 稳健超额（考虑信号分级 B2/B3 子集）

## v5 优化第 2/3 轮 — 2026-08-02（ZHIXING_ULTRA / VOLUME_B1）

- ZHIXING_ULTRA 参数化：`compute_ultra(med_long_min=65, brick_min_ratio=2/3, dif_min=0)`，
  默认值=原始公式口径，供 screen_optimize 扫描。
- 网格：ZHIXING_ULTRA 18 组（med_long 55/65/75 × brick 0.5/0.67/0.8 × dif 0/0.1）；
  VOLUME_B1 27 组（yangyin_28 × yangyin_14 × surge_ratio）。

### 结果（600 只，8 验证窗，5日+5%机会命中）
| 策略 | 最佳稳健% | 中位% | 最差% | 基线中位% | 超额pp | 总信号 | 判定 |
|---|---|---|---|---|---|---|---|
| ZHIXING_ULTRA | 24.0 | 26.9 | 21.1 | 22.2 | +1.8 | 8,800 | 未写参（<3pp） |
| VOLUME_B1 | 21.4 | 28.4 | 14.5 | 20.9 | +0.5 | 1,002 | 未写参（<3pp） |

两个策略的最差窗都在 14-21%（2023H2 类弱市段），与 B1_B2_B3 同样结论：
全样本点估计有正超额，但按窗稳健估计不足 3pp——**当前三个"跑赢基线"的策略
都处于"真实但脆弱"状态，需要策略改进而非调参**。

### 对抗性检查抓到并修复：should_write 门槛绕过
- 根因：旧逻辑"无在任参数 → 直接写入"排在基线检查之前，新策略第一次优化时
  ZHIXING_ULTRA（+1.75pp）被误写入 best_params.json。
- 修复：`min_lift`（跑赢随机基线）检查移到最前，无论有无在任参数都必须先过
  基线门槛；回滚误写条目（best_params 恢复为原 3 个键）。
- 回归测试：`test_should_write_lift_gate_applies_to_new_strategy`（无在任+低超额
  → 拒绝；高超额→允许；有在任+低超额→拒绝）。
- 修复后用真实数据复跑验证：ZHIXING_ULTRA / VOLUME_B1 均正确拒绝，best_params 未再被污染。

## v5 假设检验：B1_B2_B3 分级子集（第②项，2026-08-03）

**问题**：B2/B3 分级确认能否把稳健超额推过 3pp？——用户"B3 确定性更高"经验的统计验证。

### 系统能力新增
- `run_strategy(subtype=...)`：按 signal_type/brick_type 过滤子类型
- screen_bt 自动输出子类型明细（B1_B2_B3[B1/B2/B3]、BRICK_THREE_TYPES 三型）
- screen_optimize `--subtype`：对子类型单独 walk-forward
- 修复两处：空帧保 schema（signal_type 列不再丢失）；窗口级样本门槛 8
  （默认 100 会把稀疏子集整窗判"样本不足"）

### 点估计（979 只 + 退市股，5日+5%机会命中）
| 子集 | 信号数 | 成功率% | 基线% | 超额pp |
|---|---|---|---|---|
| B1_B2_B3[B3] | 243 | 38.7 | 23.3 | **+15.4** |
| B1_B2_B3[B2] | 7,669 | 29.1 | 23.0 | **+6.0** |
| B1_B2_B3[B1] | 1,045 | 23.0 | 21.5 | +1.5 |

命中率随确认等级**单调提升**（B1→B2→B3）——"递进确认"逻辑成立，B3 点估计极强。

### 稳健性（walk-forward，8 验证窗）
| 子集 | 稳健% | 中位窗% | 最差窗% | 基线中位% | 稳健超额 | 判定 |
|---|---|---|---|---|---|---|
| B1 | 15.0 | 20.0 | 10.0 | 17.6 | **-2.6pp** | B1 无独立价值 |
| B2（网格最优） | 23.4 | 26.7 | 20.2 | 20.5 | **+2.98pp** | 8/8 窗为正，距 3pp 差 0.02pp |
| B3（800只） | 24.7 | 33.5 | 15.8 | 23.5 | +1.2pp | 中位 +10pp，最差窗小样本拖累 |
| B3（2000只） | 21.2 | 29.0 | 13.3 | 20.3 | +0.8pp | 8/8 窗有效，2024-01(15信号)仍负 |

### 结论
1. **分级假设成立**：B1 < B2 < B3 单调，B2 每窗都跑赢基线（稳健 +2.98pp，
   已达门槛边缘），B3 中位窗超额 +10pp（点估计 +15pp）。
2. B2 是最佳可落地子集：调参后稳健超额 +2.98pp，因差 0.02pp 系统拒绝写参；
   如需采纳可 `--force-write`（阈值内差异，非统计差异）。
3. B3 稀缺（约 0.3 信号/股/5年）导致最差窗噪声大，稳健分过不了 3pp——
   需更大样本或接受"中位窗 +10pp"的证据强度。
4. 建议：每日选股将 B2/B3 信号单独标注（B3 高置信徽章），不做参数覆盖。

## v5 B2/B3 徽章接入每日选股 — 2026-08-03

- `composite.build_stock_row` 新增 `b1b2b3_stage`（''/B1/B2/B3，末行标签对齐、
  尾窗 300 行控耗时、套用 best_params 在任参数）与严格徽章 `sig_b2`/`sig_b3`
  （加入 rank_all 的 strict_signal 判定）。
- daily_screener：strategies 标签新增 "B2确认"/"B3锁仓"，进 Markdown 报告与飞书推送；
  strategy_families.json 将两者归入"基本面法"（成功率追踪口径一致）。
- 效果：每天选出的 Top 表会直接标出"今天是某票 B2 放量确认 / B3 锁仓"，
  对应统计验证过的 +6.0pp / +15.4pp 命中优势。
- 测试：新增 3 项（末行 stage 解析/空信号/家族归属），全量 **637 passed**。
- 未做：B2 优化参数（稳健 +2.98pp）仍未写入 best_params——差 0.02pp，
  是否 `--force-write` 由用户定夺。
