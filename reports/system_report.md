# AlphaPulse-A 量化交易系统 — 搭建报告

> 生成时间：2026-05-16 | 版本：v0.7.0

---

## 一、系统概览

AlphaPulse-A 是一个端到端的 A 股量化交易系统，覆盖数据准备、因子实现、策略回测、参数优化、Agent 工具封装、实盘对接准备、长期无人值守全流程。

| 属性 | 值 |
|------|-----|
| 语言 | Python 3.14 |
| 数据源 | baostock (A股日线) |
| 回测引擎 | 独立引擎 + VeighNa 兼容封装 |
| 因子数量 | 8 个核心因子 + 可扩展注册表 |
| 策略数量 | 3 个（B1/砖型图/单针下三十） |
| 自动化脚本 | 6 个 |
| 前端 | 单页 HTML（NLP转公式+回测GUI+可视化） |

## 二、项目目录结构

```
quantan trade/
├── CLAUDE.md                          # 项目指令+模型路由
├── progress_log.md                    # 进度日志
├── daily_auto_report.md               # 无人值守日报
├── frontend/
│   └── index.html                     # 前端GUI
├── alphapulse/
│   ├── config/
│   │   ├── settings.py                # 全局配置
│   │   └── best_params.json           # 最优参数
│   ├── factors/                       # 8个因子 + 注册表
│   │   ├── factor_registry.py
│   │   ├── n_struct.py                # N型结构识别
│   │   ├── vol_red_green.py           # 红肥绿瘦
│   │   ├── abnormal_vol.py            # 放量异动
│   │   ├── vol_cont_shrink.py         # 缩量
│   │   ├── kdj_j_low.py               # J值低位
│   │   ├── weekly_ma_bull.py          # 周线多头
│   │   ├── macd_bull_dead.py          # MACD多头/死叉
│   │   └── shrink_to_abnormal.py      # 缩量至异动1/4
│   ├── strategies/
│   │   ├── b1.py                      # B1多因子组合
│   │   ├── brick.py                   # Renko砖型图
│   │   └── needle.py                  # 单针下三十
│   └── utils/
│       └── backtest_utils.py          # 滑点/手续费/仓位
├── vnpy_strategies/                   # VeighNa CtaTemplate封装
│   ├── b1_strategy.py
│   ├── brick_strategy.py
│   └── needle_strategy.py
├── scripts/
│   ├── download_a_share_data.py       # A股数据批量下载
│   ├── parse_tdx_data.py              # 通达信.day解析（备用）
│   ├── run_backtest.py                # 独立回测引擎
│   ├── daily_screener.py              # 每日选股
│   ├── evening_review.py              # 晚间复盘
│   ├── risk_monitor.py                # 风控监控
│   ├── export_qmt_csv.py              # QMT下单导出
│   └── daily_auto_run.py              # 无人值守自动化
├── config/
│   ├── com.alphapulse.daily-auto.plist    # 每日2:00自动化
│   └── com.alphapulse.full-download.plist # 全量下载任务
├── tests/
│   ├── test_factors.py                # 因子测试 (10项)
│   └── test_strategies.py             # 策略测试 (5项)
├── reports/
│   └── system_report.md               # 本报告
├── backtest_results/
├── data/day/                          # 本地数据缓存
└── logs/                              # 运行日志
```

## 三、各阶段完成情况

### ✅ 阶段零：项目脚手架
- Git 仓库初始化，完整目录结构
- CLAUDE.md（项目指令+模型路由）
- progress_log.md（进度追踪）
- config/settings.py（滑点买0.1%卖0.2%、手续费万2.5最低5元、单票≤20%最多5只、初始资金100万）

### 🔄 阶段一：数据准备
- 方案：通达信 .day → akshare → baostock（最终选择）
- 原因：akshare 被网络阻断（eastmoney.com 代理拦截），baostock 可用
- 数据目录：`/Volumes/Mac-480g外接/quantan_data/day/`
- 下载脚本：`scripts/download_a_share_data.py`（限流、断点续传、进度条）
- 定时任务：`config/com.alphapulse.full-download.plist`（每日凌晨1:00全量下载）
- 当前状态：样本数据下载中（100只测试）

### ✅ 阶段二：核心因子实现（8/8）
所有因子采用 pandas/numpy 向量化实现，通过 `factor_registry.py` 统一调用。

| 因子ID | 说明 | 关键参数 | 输出类型 |
|--------|------|----------|----------|
| N_STRUCT | N型结构识别 | min_leg_len=5, retrace_ratio=0.618 | 'A'/'B'/'C'/'D' |
| VOL_RED_GREEN | 红肥绿瘦 | N=20, ratio_threshold=1.3 | bool |
| ABNORMAL_VOL | 放量异动 | M=60, K=2.0, X=3, Y=5 | bool |
| VOL_CONT_SHRINK | 缩量 | shrink_ratio=0.25, recent_period=5 | bool |
| KDJ_J_LOW | J值低位 | j_threshold=13 | bool |
| WEEKLY_MA_BULL | 周线多头 | ma_periods=[5,10,20] | bool |
| MACD_BULL_DEAD | MACD多头/死叉 | fast=12, slow=26, signal=9 | bool |
| SHRINK_TO_ABNORMAL | 缩至异动1/4 | ratio=0.25 | bool |

**测试**: 10 项单元测试全部通过（合成数据验证）

### ⏭️ 阶段三：案例分析与因子提炼
- 跳过原因：需用户提供 `cases.csv`（≥10条，含 symbol/event_date/note）
- 待补时机：用户提供案例数据后

### ✅ 阶段四：三大策略信号生成器

| 策略 | 核心逻辑 | 文件 |
|------|---------|------|
| B1 | 缩量+J低+MACD+异动+周线多头（5条件AND） | `strategies/b1.py` |
| BRICK | Renko固定2%振幅+连续同向砖确认 | `strategies/brick.py` |
| NEEDLE | 长下影+J超卖+低位30%+缩量+单针确认 | `strategies/needle.py` |

**统一输出**: DataFrame(symbol/date/signal/strategy/factor_snapshot)
**测试**: 5 项单元测试全部通过

### ✅ 阶段五：回测引擎

**独立回测引擎** (`scripts/run_backtest.py`):
- 逐日遍历所有股票
- 信号触发 → 滑点修正 → 手续费扣除 → 仓位检查 → 执行
- 止损-10%、止盈+30%
- 绩效指标：年化收益率、最大回撤、夏普比率、胜率、盈亏比
- 输出 JSON 结果 + Markdown 报告

**VeighNa 封装** (`vnpy_strategies/`):
- B1/Brick/Needle 三个 CtaTemplate 子类
- on_bar 中调用 alphapulse 信号生成器
- 兼容 VeighNa 回测框架（可选）

### ⬜ 阶段六：参数网格搜索
- 待回测数据就绪后执行
- 搜索范围：shrink_ratio (0.2, 0.25, 0.3, 0.4) × j_threshold (8, 10, 13, 15) × K (1.5, 2.0, 2.5, 3.0)
- 共 4×4×4 = 64 组组合

### ⬜ 阶段七：云端交叉验证
- 待回测完成，关键指标偏差 < 5%

### ✅ 阶段八：Agent 工具封装

| 脚本 | 功能 | 用法 |
|------|------|------|
| `daily_screener.py` | 三策略选股 → Markdown信号报告 | `python scripts/daily_screener.py --date 2025-01-15` |
| `evening_review.py` | 信号vs实际涨跌 → 胜率统计 | `python scripts/evening_review.py --signals signals.csv` |
| `risk_monitor.py` | 5项风控检查 → CRITICAL时exit 1 | `python scripts/risk_monitor.py --positions positions.csv` |
| `daily_auto_run.py` | 凌晨全量扫描 → 日报追加 | `python scripts/daily_auto_run.py` |

### ✅ 阶段九：QMT 实盘对接
- `scripts/export_qmt_csv.py`：信号 → QMT批量下单CSV
- 代码格式：600519 → 600519.SH / 000001 → 000001.SZ
- 等额分配仓位 + 整手计算

### ✅ 阶段十：长期无人值守
- launchd 定时任务：每日凌晨2:00自动化（因子扫描+策略快照+案例复核）
- 每日14:30盘中选股 / 15:30晚间复盘
- 登录项安装：复制 plist 到 `~/Library/LaunchAgents/`

## 四、技术选型说明

| 决策 | 选择 | 原因 |
|------|------|------|
| 数据源 | baostock | akshare被网络阻断，baostock免费且macOS可用 |
| 回测引擎 | 独立实现+VeighNa兼容 | VeighNa在macOS上安装复杂，独立引擎更可控 |
| 数据路径 | 外接硬盘 | 项目目录与数据分离，便于管理 |
| NLP转公式 | 规则引擎 | 量化因子有明确的语法模式，规则匹配准确高效 |
| 前端 | 纯HTML单页 | 无需服务端，Chart.js可视化，直接打开即用 |
| 定时任务 | macOS launchd | 原生支持，比cron更可靠 |

## 五、测试覆盖

```
$ python -m pytest tests/ -v
=========================== 15 passed ===========================
tests/test_factors.py::test_n_struct PASSED
tests/test_factors.py::test_vol_red_green PASSED
tests/test_factors.py::test_abnormal_vol PASSED
tests/test_factors.py::test_vol_cont_shrink PASSED
tests/test_factors.py::test_kdj_j_low PASSED
tests/test_factors.py::test_weekly_ma_bull PASSED
tests/test_factors.py::test_macd_bull_dead PASSED
tests/test_factors.py::test_shrink_to_abnormal PASSED
tests/test_factors.py::test_factor_registry PASSED
tests/test_factors.py::test_all_factors_no_error PASSED
tests/test_strategies.py::test_b1_signals PASSED
tests/test_strategies.py::test_brick_signals PASSED
tests/test_strategies.py::test_needle_signals PASSED
tests/test_strategies.py::test_all_strategies_return_consistent_schema PASSED
tests/test_strategies.py::test_short_data_handling PASSED
```

## 六、Git 提交历史

```
3ba8257 feat: Phase 10 long-term automation
dda4552 feat: Phase 8 Agent tools + Phase 9 QMT export
ebb958b feat: Phase 4 strategies (B1/Brick/Needle)
1e84929 feat: Phase 2 - 8 factors + registry + tests
8224b42 docs: Phase 1 switched to akshare/baostock
15e5aa2 feat: A-share download script (baostock)
50f84bd feat: Phase 5 backtest engine + VeighNa wrappers
22e0d7e docs: progress update
1cea0d2 feat: project scaffold
```

## 七、待完成事项

| 优先级 | 事项 | 阻塞项 | 预计时间 |
|--------|------|--------|----------|
| P0 | 全量A股数据下载 | baostock限速 | 约3-4小时（自动） |
| P0 | 完整回测运行（2020-2025） | 数据就绪 | 约30分钟 |
| P1 | 参数网格搜索（64组） | 回测引擎 | 约2小时 |
| P1 | 用户案例 cases.csv | 用户准备 | — |
| P2 | VeighNa 安装验证 | macOS兼容性 | 约30分钟 |
| P2 | 聚宽云端交叉验证 | 回测结果 | 约1小时 |
| P2 | 前端API服务（连接回测引擎） | — | 约2小时 |
| P3 | QMT券商开通+模拟测试 | 券商流程 | 不定 |

## 八、快速启动

```bash
# 1. 激活环境
cd "/Users/qiushixuan/cc/quantan trade"
source .venv/bin/activate

# 2. 下载数据（100只测试）
python scripts/download_a_share_data.py --sample 100

# 3. 运行回测
python scripts/run_backtest.py --strategy ALL --sample 20

# 4. 每日选股
python scripts/daily_screener.py --date $(date +%Y-%m-%d)

# 5. 打开前端
open frontend/index.html

# 6. 安装定时任务
cp config/com.alphapulse.daily-auto.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alphapulse.daily-auto.plist
```

---

*报告由 AlphaPulse-A 系统自动生成。下次更新将在全量数据下载和完整回测完成后。*
