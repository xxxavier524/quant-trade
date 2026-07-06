# AlphaPulse-A 量化交易系统

A股端到端量化选股系统 — 从数据准备到策略回测到实盘导出。

**版本**: v2.0 | **更新**: 2026-05-23 | **覆盖**: 5,229只A股 (2020-2026)

---

## 一、快速入口

### 安装

```bash
cd "/Users/qiushixuan/cc/quantan trade"
source .venv/bin/activate
pip install -r requirements.txt  # 首次
```

### 常用命令

| 操作 | 命令 |
|------|------|
| 全量下载A股数据 | `python scripts/_smart_downloader.py` |
| 运行三个策略回测 | `python scripts/run_backtest.py --strategy ALL --sample 300` |
| 两阶段AI回测 | `python scripts/run_two_stage_opt.py` |
| 每日选股报告 | `python scripts/daily_screener.py` |
| 晚间复盘 | `python scripts/evening_review.py --signals signals.csv` |
| 风控检查 | `python scripts/risk_monitor.py --positions positions.csv` |
| QMT下单导出 | `python scripts/export_qmt_csv.py --signals signals.csv` |
| 案例股检测 | `python scripts/backtest_cases.py` |
| 运行全因子扫描 | `python scripts/daily_auto_run.py` |
| 运行全部测试 | `python -m pytest tests/ -v` |
| 监控守护 | `python scripts/_monitor_runner.py --daemon` |

---

## 二、系统架构

```
输入层                 计算层                  输出层
┌──────────┐    ┌──────────────────┐    ┌──────────────┐
│ 日线CSV   │───▶│ 19+因子计算引擎   │───▶│ 选股信号报告   │
│ 5,229只  │    │ (向量化pandas)   │    │ (Markdown)   │
└──────────┘    └──────────────────┘    └──────────────┘
                       │
┌──────────┐    ┌──────▼───────────┐    ┌──────────────┐
│ 案例股46只│───▶│ 8+策略信号生成器  │───▶│ 回测结果JSON  │
└──────────┘    └──────────────────┘    └──────────────┘
                       │
┌──────────┐    ┌──────▼───────────┐    ┌──────────────┐
│ 行业轮动  │───▶│ 两阶段AI选股模型  │───▶│ QMT下单CSV    │
│ β预测模型 │    │ (双层垂直体系)    │    └──────────────┘
└──────────┘    └──────────────────┘
```

### 目录结构

```
├── README.md                        # 本文件
├── CLAUDE.md                        # Claude Code 自动指令
├── progress_log.md                  # 阶段进度日志
├── alphapulse/                      # 主包
│   ├── factors/                     # 因子模块 (19个)
│   │   ├── factor_registry.py       # 因子注册表 (23项)
│   │   ├── experimental/            # 券商金工因子 (5个)
│   │   ├── industry_rotation.py     # 行业轮动模型
│   │   └── beta_fundamental.py      # β预测模型
│   ├── strategies/                  # 策略模块 (9个)
│   │   ├── two_stage_selection.py   # 两阶段AI选股
│   │   └── ...
│   ├── adapters/                    # 外部集成 (4个)
│   ├── pipeline/                    # 6-Agent研究管线
│   ├── strategy/                    # N型精确识别
│   ├── utils/                       # 回测/滑点/费率
│   └── config/                      # settings.py
├── scripts/                         # 可执行脚本 (14个)
├── tests/                           # 单元测试
├── reports/                         # 分析报告 (19份)
├── backtest_results/                # 回测结果
├── data/day/                        # 本地CSV缓存
├── cases/                           # 46只案例股
├── .claude/skills/                  # 论文研究Skills (4个)
└── papers/                          # 论文工作区
```

---

## 三、选股因子体系 (23项)

### 核心技术因子 (8个)

| 因子ID | 名称 | 类型 | 关键参数 |
|--------|------|------|----------|
| N_STRUCT | N型结构识别 | 形态 | min_leg_len=5, retrace_ratio=0.618 |
| VOL_RED_GREEN | 红肥绿瘦 | 量能 | N=20, ratio_threshold=1.3 |
| ABNORMAL_VOL | 放量异动 | 量能 | M=60, K=2.0 |
| VOL_CONT_SHRINK | 缩量 | 量能 | shrink_ratio=0.25 |
| KDJ_J_LOW | J值低位 | 指标 | j_threshold=13 |
| WEEKLY_MA_BULL | 周线多头 | 趋势 | MA5>MA10>MA20 |
| MACD_BULL_DEAD | MACD多头/死叉 | 指标 | fast=12, slow=26, signal=9 |
| SHRINK_TO_ABNORMAL | 缩至异动量1/4 | 量能 | ratio=0.25 |

### 通达信选股方案 (4个)

| 方案ID | 来源 | 逻辑 |
|--------|------|------|
| B1_FORMULA | B1选股公式.txt | 6条件AND：涨幅±3%+振幅<9%+J<13+趋势>多空+DIF>-0.1+市值>10亿 |
| BRICK_ULTRA | 砖型图超短选股.txt | TDX砖型图昨绿→今红转换 |
| ZHIXING_WASHOUT | 知行洗盘短线.txt | 四线归零/交叉判断 |
| VOLUME_B1 | 量能B1选股.txt | 阳阴量比+爆量阳+缩倍量+价格位置 |

### 纯指标因子 (2个)

| 因子ID | 说明 |
|--------|------|
| BRICK_INDICATOR | TDX砖型图指标数值 (VAR1A-VAR6A) |
| ZHIXING_LINES | 知行四线数值 (短期/中期/中长期/长期) |
| ZHIXING_TREND | EMA(EMA(C,10),10) 知行趋势线 |

### 券商金工因子 (5个，实验性)

| 因子ID | 来源 | IC | 方向 |
|--------|------|-----|------|
| NORTHBOUND_FLOW | 广发证券·北向2.0 | +5.1% | 正向 |
| IDIOSYNCRATIC_VOL | 国信证券·特质波动 | -9.29% | 反向 |
| TURNOVER_UNIFORMITY | 东吴证券·换手均匀 | -6.7% | 反向 |
| ANALYST_REVISION | 华泰证券·分析师修正 | +4.27% | 正向 |
| CAPITAL_FLOW_BIG | 东海证券·大单流向 | +0.087% | 正向 |

### AI模型因子 (3个，实验性)

| 因子ID | 说明 |
|--------|------|
| INDUSTRY_ROTATION | 行业轮动评分 (MA/MACD/动量/一致性) |
| BETA_PREDICTION | 7基本面代理→β预测 (规模/盈利/经营杠杆/财务杠杆/成长/质量/量能) |
| TWO_STAGE_SELECTION | 双层垂直AI选股 (行业配置+个股精选) |

---

## 四、策略体系

### 4.1 B1_FORMULA (主力策略) ★★★★★

**来源**: 通达信B1选股公式
**逻辑**: 6条件AND组合
**回测结果 (5,114只, 2020-2025)**:

| 指标 | 值 |
|------|-----|
| 年化收益率 | **+9.31%** |
| 最大回撤 | -28.67% |
| 夏普比率 | 0.36 |
| 胜率 | 33.07% |
| 总交易次数 | 259 |

### 4.2 BRICK_ULTRA (砖型图超短)

**来源**: 通达信砖型图超短选股
**逻辑**: TDX砖型图昨绿→今红转换，红实体≥绿实体×2/3
**回测结果**:

| 指标 | 值 |
|------|-----|
| 年化收益率 | **+8.10%** (优化后) |
| 最大回撤 | -27.01% |
| 夏普比率 | 0.32 |
| 胜率 | 32.04% |
| 总交易次数 | 211 |

### 4.3 NEEDLE_ENHANCED (单针增强)

**逻辑**: 长下影 + J超卖 + 知行洗盘叠加
**回测结果**: 年化+3.6%，回撤-44.5% — 弱于B1和Brick

### 4.4 Two-Stage AI (两阶段AI选股) ★★★☆☆

**来源**: AI量化选股论文（行业配置+个股精选双层垂直体系）
**逻辑**: Stage1行业轮动评分→Stage2 β预测→Top N选股
**回测结果 (20次参数优化)**:

| 指标 | 最优 | 均值 |
|------|------|------|
| 年化收益率 | 7.34% | 7.0% |
| 最大回撤 | -24.35% | -47% |
| 夏普比率 | 0.29 | 0.29 |
| 最优参数 | top_ind=6, per_ind=10, min_score=0.32, Monthly |

### 4.5 B1_ENHANCED

B1 + 知行超短 + 量能B1融合信号。辅助策略。

### 4.5b ZG_B1_BRICK (Z哥融合选股·独立试验) 🆕

把 Z哥（zettaranc）少妇战法 SOP 串成一个自包含选股器，**刻意独立**于现有 B1，
跑一段时间效果好再考虑并入主选股：

- 进场：复用 `b1_formula` 的 B1 买点（6条件）
- 周期确认：`four_brick_cycle` 只放行砖型图早段（第1-2红砖），尾段（第4砖起）否决
- 纪律卡：每个信号附「只输一根K线」止损线（`dynamic_stop_loss`）+ S1/四砖尾段离场提示

```bash
python scripts/zg_screener.py --date 2026-05-15 --top 30   # 独立报告 reports/zg_screen_*.{csv,md}
python scripts/zg_screener.py --ignore-macro               # 跳过择时闸门
```

注册名 `ZG_B1_BRICK`（type=selection）。来源：`.claude/skills/zettaranc-perspective`（女娲蒸馏）。

### 4.6 策略对比总览

| 策略 | 年化收益 | 最大回撤 | Sharpe | 评级 |
|------|---------|---------|--------|------|
| **B1_FORMULA** | **+9.31%** | -28.67% | **0.36** | ★★★★★ |
| BRICK_ULTRA | +8.10% | -27.01% | 0.32 | ★★★★☆ |
| Two-Stage AI | +7.34% | -24.35% | 0.29 | ★★★☆☆ |
| NEEDLE_ENHANCED | +3.60% | -44.46% | 0.13 | ★★☆☆☆ |
| B1_SUPER | 0% | 0% | - | ☆ (无效) |

---

## 五、回测引擎

### 独立回测引擎 (`scripts/run_backtest.py`)

**特性**:
- 两阶段架构：Phase1预计算信号 → Phase2快速组合模拟
- 滑点：买入+0.1%，卖出-0.2%
- 手续费：万2.5，最低5元
- 仓位限制：单票≤20%，最多5只
- 止损：-10%，止盈：+30%
- 初始资金：100万

**输出指标 (8+)**:
年化收益率 | 最大回撤 | 夏普比率 | Calmar比率 | Sortino比率 | 胜率 | 盈亏比 | 最大连续亏损

### 向量化验证 (`quant-multifactor/`)

- Walk-Forward验证 (降解比0.6-0.8健康)
- Combinatorial Purged CV (45+非随机路径)
- Deflated Sharpe Ratio Gate (DSR p≥0.95)
- 3道Gate + 30天Paper Trading + Kill-switch

---

## 六、自动化任务

| 时间 | 任务 | 脚本 | 触发 |
|------|------|------|------|
| 01:00 | 全量数据下载 | `_smart_downloader.py` | launchd |
| 02:00 | 因子扫描+策略快照 | `daily_auto_run.py` | launchd |
| 14:30 | 盘中选股 | `daily_screener.py` | launchd |
| 15:30 | 晚间复盘 | `evening_review.py` | launchd |
| 每小时 | 系统健康监控 | `_monitor_runner.py` | launchd |

### 安装定时任务

```bash
cp config/com.alphapulse.daily-auto.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alphapulse.daily-auto.plist
```

---

## 七、Agent工具链

| 脚本 | 功能 | 输出 |
|------|------|------|
| `daily_screener.py` | 三大策略选股 | 信号Markdown报告 |
| `zg_screener.py` 🆕 | Z哥融合选股(独立) | reports/zg_screen_*.{csv,md} |
| `evening_review.py` | 信号vs实际涨跌 | 胜率统计 |
| `risk_monitor.py` | 5项风控检查 | 告警(CRITICAL→exit 1) |
| `export_qmt_csv.py` | QMT下单CSV | 代码转换+整手计算 |
| `daily_auto_run.py` | 无人值守主控 | 日报追加 |

### 6-Agent研究管线

`python scripts/run_pipeline.py`

假设生成→数据获取→因子编码→回测→审查→DSR/Risk Gate

### Agent Team 人格角色 (`config/personas/`) 🆕

`agent_team` 辩论庭支持 skill 驱动的人格角色：`config/personas/` 下每个 `.md`
= 一个人格，文件内容作为 system prompt，在辩论时基于量化 evidence 独立出观点，
注入 Referee 仲裁并展示在报告/GUI。

- **金渐成**（`config/personas/金渐成.md`）：以「长期可持续的财富循环」为核心的
  投资体系人格，判断顺序 生存→周期→战场→期望值→质量买点→边界。
  来源 `.claude/skills/jin-jiancheng-perspective`（女娲蒸馏）。

---

## 八、外部集成

| 适配器 | 来源 | 功能 |
|--------|------|------|
| riskfolio_adapter | Riskfolio-Lib | Black-Litterman/CVaR/HRP组合优化 |
| vectorbt_adapter | vectorbt | 向量化网格搜索加速 |
| financetoolkit_adapter | FinanceToolkit | 45个基本面因子 |
| tradingagents_adapter | TradingAgents | 多智能体LLM信号增强 |

### 论文研究Pipeline (`.claude/skills/`)

| Skill | 功能 |
|-------|------|
| paper-search | Arxiv q-fin检索→PDF下载 |
| paper-extract | PDF→结构化笔记+指标JSON |
| paper-replicate | 独立复现+基准对比 |
| strategy-translate | 向量化→事件驱动生产代码 |

---

## 九、案例股检测结果

**46只案例股，100%命中 (45/45数据可用)**:

| 策略 | 命中率 | 平均信号数 |
|------|--------|-----------|
| B1_FORMULA | 100% | 83.6 |
| BRICK_ULTRA | 100% | 145.1 |
| B1_ENHANCED | 100% | 118.0 |
| NEEDLE_ENHANCED | 4.4% | 1.0 |

---

## 十、因子IC分析 (Top 5)

| 排序 | 因子 | IC | 使用建议 |
|------|------|-----|---------|
| 1 | N_STRUCT | -0.387 | 反向过滤 |
| 2 | KDJ_J_LOW | +0.019 | 正向选股 |
| 3 | B1_FORMULA | +0.012 | 综合选股 |
| 4 | SHRINK_TO_ABNORMAL | +0.007 | 辅助确认 |
| 5 | BRICK_ULTRA | +0.004 | 弱正向 |

---

## 十一、系统限制与已知问题

| 限制 | 说明 |
|------|------|
| 仅A股 | 无港股/美股/加密货币 |
| 无ML模型 | LightGBM/XGBoost未集成 |
| 仅日线 | 无分钟/高频数据 |
| 仅OHLCV | 无基本面数据(PE/PB/ROE等) |
| 无GUI | CLI+脚本为主 |
| Qlib不可用 | Python 3.14无cp314 wheel |

---

## 十二、数据来源

- **主力**: baostock + akshare 交替下载
- **备用**: yfinance适配器
- **路径**: `/Volumes/Mac-480g外接/quantan_data/day/`
- **格式**: CSV (date, open, high, low, close, volume, amount, turnover)
- **环境变量**: `ALPHAPULSE_DATA_DIR` 可覆盖数据路径
