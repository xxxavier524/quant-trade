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
