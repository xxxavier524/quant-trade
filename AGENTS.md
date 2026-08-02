# AlphaPulse-A 量化选股系统（v5 纯选股版）

> Codex 自动读取。完整计划与核心约束。

## 核心约束（全局）

- Python 3.10+，向量化优先（pandas/numpy），禁止逐行循环
- **本系统只做选股**：输出"哪些票值得关注 + 各策略成功率证据"。
  交易侧（仓位/滑点/止损/资金曲线/下单）已于 2026-08-02 整体移除
  （git 历史可回溯），禁止重新引入
- 数据源：通达信 `.day` → CSV，主存储于外接盘 `/Volumes/Mac-480g外接/quantan_data/day`
  （经 `settings.DATA_DIR` 读取，勿硬编码；内置盘 `data/day/` 为迁移期旧副本勿用）
- 命名空间：`alphapulse.factors`、`alphapulse.strategies`、`alphapulse.screening`
- 信号因子一律禁止未来函数：枢轴/形态/阶段必须按确认时点公布
  （N 型结构用 `n_struct.compute_causal`，`compute()` 已废弃）
- 选股成功率唯一主口径 = **机会命中**：信号日收盘后 H（默认5）个交易日内
  任一收盘 ≥ +5%（见 `docs/v5_screen_system.md`）；必须与随机基线对比，
  超额命中 ≤ 0 的策略无选股价值
- 每次修改代码前 `git commit`
- 每阶段结束追加 `progress_log.md`

## v5 分支（2026-08-02 起）

- 当前分支：`codex/v5`（基线 v4-fusion；tag `v3-stable` 可回退）
- 已移除交易侧：run_backtest 引擎、portfolio/position 管理、playbook 模拟、
  risk_monitor、QMT 下单导出、auto_retune（周检调参）、相关回测脚本与测试
- 已建立纯选股评估：`alphapulse/screening/` + `scripts/screen_bt.py` +
  `scripts/screen_optimize.py`（第一性原理规格见 `docs/v5_screen_system.md`）
- P0/P1 已完成：N型因果化、realized 口径、闸门留痕、假规则修复、QMT/IC 死代码下线
- 已知待办：B1B2B3 策略重做（负期望，调参已放弃）；数据停更后追平验证

## 模型路由

- **重推理任务** → `deepseek-v4-pro`：因子设计、策略逻辑修改、bug 调试、案例特征分析
- **批量任务** → `deepseek-v4-flash`：数据清洗、全市场因子扫描、成功率回测（并行）、报告生成

## 自动化任务（无人值守，全部为选股/数据链路）

### 数据自愈 + 选股流水线（收盘后 15:35 起每小时）
- 触发：launchd `config/com.alphapulse.data-catchup.plist`（15:35~22:30，RunAtLoad=true
  开机/登录即触发一次，覆盖关机漏更）
- 链路：data_catchup 续传至覆盖率达标 → `scripts/eod_pipeline.py`
  （指数更新 → 数据新鲜度铁律 → 全市场选股 → agent 研判 → 信号追踪 → 决策对账 → 卡死股恢复）
- 全市场选股：`scripts/daily_screener.py [--date YYYY-MM-DD] [--top N] [--no-gate]`
  → `reports/screen_YYYY-MM-DD.csv` + `daily_report_*.md`
- 硬闸门关闭（上证MACD零轴/大盘S1）→ 写 `reports/gate_closed_<date>.json`、
  流水线记录 `gated:true`、夜场报告提示"不开新仓"（禁止静默空转）

### 每日凌晨 2:00 — 夜场报告
- launchd `config/com.alphapulse.daily-auto.plist` → `scripts/daily_auto_run.py`
- 内容：追踪库实盘口径（realized）复盘 + 硬闸门状态，推飞书；
  `daily_auto_report.md` 由决策对账与周日 screen_optimize 追加

### 晚间复盘（手动/按需）
- `scripts/evening_review.py [--push] [--window 30] [--output 文件]`
- 口径：追踪库 realized 为主，"曾触及+5%"仅对照

### 纯选股成功率回测/优化（手动/按需）
- `scripts/screen_bt.py --strategies ALL --sample 300` → 全策略成功率报告
- `scripts/screen_optimize.py --strategy B1_B2_B3 --sample 800` →
  walk-forward 稳健参数（须跑赢基线才写入 best_params.json）

## 项目结构

```
├── AGENTS.md / CLAUDE.md / progress_log.md
├── alphapulse/
│   ├── factors/            # 因子模块（compute(df)->Series，注册于 factor_registry）
│   ├── strategies/         # 选股信号生成器（B1_B2_B3/砖型图/单针/ZG 等）
│   ├── screening/          # 纯选股评估层（evaluator + 策略注册）★v5
│   ├── ranking/            # 子分数 + 加权排序（每日选股评分链）
│   ├── tracking/           # 信号追踪闭环（实盘口径成功率）
│   ├── market/             # 大盘诊断 + 硬闸门（选股择时门）
│   ├── agent_team/         # 多角色选股研判（无仓位/风控层）
│   ├── ml/                 # 形态模型（标签=选股机会命中）
│   ├── pipeline/           # 研究管线（策略开发用）
│   └── config/             # settings.py, best_params.json, factor_weights.json
├── scripts/                # daily_screener / eod_pipeline / data_catchup /
│   │                       # screen_bt / screen_optimize / track_signals 等
├── tests/                  # 全量单测（含截断不变性防泄漏测试）
├── docs/                   # v5_screen_system.md（第一性原理规格）
└── reports/                # 选股日报 / 成功率报告 / walk-forward 报告
```

## 执行阶段（v5 纯选股体系）

### 阶段一：数据准备 ✅
- `scripts/fetch_index_data.py`（指数）、`scripts/daily_update.py`（个股断点续传）、
  `scripts/data_catchup.py`（每小时自愈）、`scripts/fetch_delisted.py`（退市股）
- 数据新鲜度铁律：`alphapulse/utils/data_freshness.py`（基准=上证指数最新bar，
  个股覆盖 ≥75% 才算最新；选股/复盘前强制确认）

### 阶段二：因子/策略库 ✅
- 8 核心因子 + 40+ 扩展因子注册于 `factor_registry.py`；10 个选股策略注册于
  `screening/strategies.py`；全部因子必须因果（未来函数=红线）

### 阶段三：纯选股成功率回测 ✅（v5 新增，替代旧交易回测）
- `screen_bt.py`：机会命中（H日收盘≥+P%）+ 随机基线 + 年度表 + 逐H曲线 +
  Wilson 下界 + 截断不变性门禁 + 退市股并入

### 阶段四：参数优化 ✅（v5 重做）
- `screen_optimize.py`：walk-forward 稳健分（0.5中位+0.5最差）+ 链式流程回测 +
  基线超额门槛（默认 ≥3pp 才写参）+ 覆盖门槛 → `config/best_params.json`（带 provenance）

### 阶段五：每日选股 + 追踪闭环 ✅
- 评分链（ranking）+ 硬闸门 + 新鲜度铁律 → Top50 → 信号追踪 →
  实盘口径成功率（realized）→ 夜间/周复盘

### 阶段六：长期无人值守
- launchd：data-catchup（自愈+选股）/ daily-auto（夜报）/ morning-brief（晨报）
- 选股成功率里程碑见下

## 总里程碑（v5 选股口径）

- [ ] 至少一个策略相对随机基线超额命中 ≥ +5pp（H=5, P=5%），且每年均为正
- [ ] 全部生产策略通过截断不变性门禁（无未来函数）
- [ ] walk-forward 链式样本外成功率 ≥ 基线 + 3pp
- [ ] 每日自动选股+追踪稳定运行 ≥ 一周，闸门关闭有留痕与告警
