# AlphaPulse-A 进度日志

> 每阶段结束自动追加。格式：时间戳、任务名、结果、最优参数、下一步建议。

---

## 总体进度

| 阶段 | 状态 | 完成时间 | 备注 |
|------|------|----------|------|
| 阶段零：项目脚手架 | ✅ | 2025-05-16 | 目录结构、CLAUDE.md、配置 |
| 阶段一：环境搭建与数据准备 | ⏭️ | 2025-05-16 | 跳过（无数据源），后续补 |
| 阶段二：核心因子实现 | ✅ | 2025-05-16 | 8因子+注册表+10测试通过 |
| 阶段三：案例分析与因子提炼 | ⏭️ | 2025-05-16 | 跳过（无cases.csv），后续补 |
| 阶段四：策略信号生成器 | ✅ | 2025-05-16 | B1/砖型图/单针下三十+5测试通过 |
| 阶段五：VeighNa 回测 | ⬜ | | |
| 阶段六：参数网格搜索 | ⬜ | | |
| 阶段七：云端交叉验证 | ⬜ | | |
| 阶段八：Agent 工具封装 | ✅ | 2025-05-16 | 4脚本完成，待真实数据验证 |
| 阶段九：QMT 实盘对接 | ✅ | 2025-05-16 | export_qmt_csv完成，待券商开通 |
| 阶段十：长期无人值守 | ✅ | 2025-05-16 | launchd+auto脚本，待接入真实数据 |

## 待补阶段

| 阶段 | 跳过原因 | 阻塞项 | 预计补做时机 |
|------|----------|--------|-------------|
| 阶段一 | 无通达信.day数据源 | 移动硬盘未接入 | 接入后立即补 |
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

- **结果**: 跳过。无可用的通达信 `.day` 数据源（移动硬盘未接入）
- **备注**: VeighNa 安装、数据解析待有数据后补做
- **下一步**: 直接进入阶段二

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

## 阶段五：VeighNa 回测

⬜ 待执行

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
