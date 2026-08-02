# AlphaPulse-A 量化交易系统

> Codex 自动读取。完整计划与核心约束。

## 核心约束（全局）

- Python 3.10+，向量化优先（pandas/numpy），禁止逐行循环
- 回测主引擎为自研日线引擎 `scripts/run_backtest.py`（次日开盘成交/涨停跳过/滑点费率仓位内建）；`vnpy_strategies/` 为 VeighNa 封装备用未接线，不接受 backtrader
- 数据源：通达信 `.day` → CSV，主存储于外接盘 `/Volumes/Mac-480g外接/quantan_data/day`（经 `settings.DATA_DIR` 读取，勿硬编码；内置盘 `data/day/` 为迁移期旧副本勿用）
- 命名空间：`alphapulse.factors`、`alphapulse.strategies`
- 滑点买0.1%卖0.2%、手续费万2.5最低5元、单票≤20%最多5只
- 信号因子一律禁止未来函数：枢轴/形态/阶段必须按确认时点公布
  （N 型结构用 `n_struct.compute_causal`，禁止用带 ±N 前视的 `compute` 生成信号）
- 胜率唯一主口径 = 追踪库 `realized`（已实现收益，持有5日/破5%止损/扣往返费）；
  "曾触及+5%"、playbook 序列胜率仅作对照，不得当成功率主数字上报
- 每次修改代码前 `git commit`
- 每阶段结束追加 `progress_log.md`

## v5 分支（2026-08-02 起）

- 当前生产/开发分支：`codex/v5`（基线 = 原 `v4-fusion`，tag `v3-stable` 可回退）
- P0 已完成：N 型结构因果化、胜率口径统一为 realized、硬闸门关闭留痕告警
- 关键决策：B1B2B3 已证负期望（留出窗全参数组负值，见 daily_auto_report.md），
  **调参救不了 → 重做信号**；auto_retune 对负期望候选不覆盖参数
- 已知遗留（P1）：`knowledge_points.py` / `utils/filters.py` 仍调用非因果
  `n_struct.compute`（未接生产信号）；QMT 导出链路待修；文档/调度口已对齐

## 模型路由

- **重推理任务** → `deepseek-v4-pro`：因子设计、策略逻辑修改、bug 调试、案例特征分析
- **批量任务** → `deepseek-v4-flash`：数据清洗、回测执行（并行）、因子全量扫描、报告生成、CSV/Excel 转换

## 自动化任务（无人值守）

### 每日凌晨 2:00 — 因子/策略/案例全量扫描
- 触发方式：macOS launchd (`config/com.alphapulse.daily-auto.plist`)
- 执行脚本：`scripts/daily_auto_run.py`
- 输出：飞书夜场报告（追踪库 realized 口径 + 硬闸门状态）；`daily_auto_report.md`
  由 eod_pipeline 的 agent 决策对账与周日 auto_retune 追加
- 安装 launchd：`launchctl load ~/Library/LaunchAgents/com.alphapulse.daily-auto.plist`

### 每日收盘后（15:35 起每小时）— 数据自愈 + 选股流水线
- 触发方式：macOS launchd (`config/com.alphapulse.data-catchup.plist`，15:35~22:30)
- 链路：data_catchup 每小时续传至覆盖率达标 → `scripts/eod_pipeline.py`
  （指数更新 → 数据新鲜度铁律 → 全市场选股 → agent 研判 → 信号追踪 → 决策对账 → 卡死股恢复）
- 全市场选股：`scripts/daily_screener.py [--date YYYY-MM-DD] [--top N] [--no-gate]`
  → 输出 `reports/screen_YYYY-MM-DD.csv` + `reports/daily_report_*.md`
- 硬闸门关闭时：写 `reports/gate_closed_<date>.json`，流水线记录 `gated:true`，
  夜场报告提示"不开新仓"（禁止静默空转）

### 晚间复盘（手动/按需）
- 执行脚本：`scripts/evening_review.py [--push] [--window 30] [--output 文件]`
- 口径：追踪库 realized 为主（已实现胜率/均值），"曾触及+5%"仅对照

### 风控 — 按需
- 执行脚本：`scripts/risk_monitor.py --positions positions.csv`
- 有 CRITICAL 警报时 exit 1，可接入告警通道

## 项目结构

```
├── AGENTS.md
├── progress_log.md
├── alphapulse/
│   ├── factors/          # 因子模块（每个因子独立 .py，compute(df)->Series）
│   │   └── factor_registry.py
│   ├── strategies/       # B1 / 砖型图 / 单针下三十
│   ├── utils/            # data_loader, backtest_utils
│   └── config/           # settings.py, best_params.json
├── vnpy_strategies/      # CtaTemplate 封装
├── scripts/              # parse_tdx_data, daily_screener, evening_review, risk_monitor, export_qmt_csv
├── tests/
├── backtest_results/
├── data/day/             # CSV日线
└── reports/
```

## 执行阶段

### 阶段一：数据准备
- `scripts/parse_tdx_data.py`：解析通达信 `.day` → `data/day/{symbol}.csv`
- 安装 VeighNa：`pip install veighna`
- 验证：抽查 600519.csv / 000001.csv 完整性

### 阶段二：核心因子实现（8个因子）

| 因子ID | 名称 | 关键参数 |
|--------|------|----------|
| N_STRUCT | N型结构识别 | min_leg_len=5, retrace_ratio=0.618 |
| VOL_RED_GREEN | 红肥绿瘦 | N=20, ratio_threshold=1.3 |
| ABNORMAL_VOL | 放量异动 | M=60, P=20, K=2.0, X=3, Y=5 |
| VOL_CONT_SHRINK | 缩量 | shrink_ratio=0.25, recent_period=5 |
| KDJ_J_LOW | J值低位 | j_threshold=13 |
| WEEKLY_MA_BULL | 周线多头 | ma_periods=[5,10,20] |
| MACD_BULL_DEAD | MACD多头/死叉 | fast=12, slow=26, signal=9 |
| SHRINK_TO_ABNORMAL | 缩量至异动1/4 | ratio=0.25 |

每个因子实现 `compute(data: pd.DataFrame) -> pd.Series`，注册到 `factor_registry.py`。

### 阶段三：案例分析与因子提炼
- 用户提供 `cases.csv`（symbol, event_date, note，≥10 条）
- 输出 `reports/case_analysis_report.md`：
  1. 事件前后价格走势共性
  2. tsfresh 提取 Top 5 量价特征
  3. 转化为 CASE_001~005 因子注册入库
  4. 回放测试：命中率 + 平均提前天数

### 阶段四：三大策略信号生成器
- `b1.py`：条件组合信号 DataFrame（symbol, signal, strategy, factor_snapshot）
- `brick.py`：Renko 固定2%振幅 + 突破逻辑
- `needle.py`：长下影 + J值超卖
- 单元测试验证

### 阶段五：回测（自研引擎，已验收）
- `scripts/run_backtest.py`：次日开盘成交/涨停停牌跳过/滑点费率仓位/持有期上限内建
- 2020-2025 完整回测；`--include-delisted` 加载退市股修正幸存者偏差
- （2026-07-12 决定：vnpy CtaTemplate 封装零引用已删除，git 历史 `9e5a45d` 前可找回；
  实盘对接走阶段九 QMT CSV 路线，不经 vnpy）

### 阶段六：参数网格搜索（walk-forward 化）
- `scripts/walk_forward.py`：锚定扩张训练窗 + 滚动验证窗，最差窗+中位数选稳健参数
- 单窗口样本内选参已废弃（B1_B2_B3 曾出 hit_rate=1.0 的过拟合参数组）
- 输出 Markdown 绩效表 → `config/best_params.json`（带 walk_forward 来源标注）

### 阶段七：云端交叉验证（聚宽）
- 翻译信号逻辑为聚宽 notebook
- 2020-2025 回测，关键指标偏差 < 5%
- 输出 `reports/cross_validation_report.md`

### 阶段八：Agent 工具封装
- `scripts/daily_screener.py`：当日信号 Markdown 列表
- `scripts/evening_review.py`：胜率统计
- `scripts/risk_monitor.py`：减仓警报
- macOS 用 `launchd` / Python `schedule` 定时 14:30/15:30

### 阶段九：QMT 实盘对接
- `scripts/export_qmt_csv.py`：QMT 批量下单格式
- 3 个月半自动运行规则

### 阶段十：长期无人值守
- 每日凌晨 2:00 自动因子扫描、策略回测、案例复核
- 结果追加到 `daily_auto_report.md`

## 总里程碑

- [ ] 三种策略年化收益 > 20%，最大回撤 < 15%（2020-2025）
- [ ] 训练案例命中率 ≥ 70%，验证 ≥ 60%
- [ ] 云端偏差 < 5%
- [ ] 每日自动信号+复盘，QMT 半自动
- [ ] 无人值守稳定运行 ≥ 一周
