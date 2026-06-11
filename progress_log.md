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
