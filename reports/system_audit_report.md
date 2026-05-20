# AlphaPulse-A 全系统审计报告

> 审计时间：2026-05-20 | 2个项目 | 58个Python模块 | 5,229只A股

---

## 一、项目结构总览

### 1.1 双项目体系

| 项目 | 路径 | 定位 | 模块数 |
|------|------|------|--------|
| **AlphaPulse-A** | `cc/quantan trade/` | 主量化系统(研究+选股) | 48 |
| **quant-multifactor** | `~/quant-multifactor/` | 多因子独立策略(箱体+联动) | 10 |

### 1.2 数据资产

- **A股日线**: 5,229只（524MB），覆盖2020-2026
- **案例标的**: 45/46 已覆盖（920807无数据）
- **回测结果**: 5个JSON文件（50/100/200/300/5114只）
- **因子IC分析**: 1份（17个因子）

---

## 二、功能清单（按执行流程）

### 阶段 A：数据准备
| 序号 | 功能 | 模块 | 状态 |
|------|------|------|------|
| A1 | A股数据下载（baostock/akshare） | `scripts/download_a_share_data.py` | ✅ |
| A2 | 智能交替下载（双源+限流） | `scripts/_smart_downloader.py` | ✅ |
| A3 | 下载守护进程（自动重启） | `scripts/_daemon_download.sh` | ✅ |
| A4 | 失败重试+错误报告 | `scripts/download_with_retry.py` | ✅ |
| A5 | yfinance备用适配器 | `alphapulse/utils/yfinance_adapter.py` | ✅ |

### 阶段 B：因子计算
| 序号 | 因子 | 类型 | 来源 | 状态 |
|------|------|------|------|------|
| B1 | N_STRUCT - N型结构 | 形态 | 自研（旧版scipy） | ⚠️ |
| B2 | B1_FORMULA - B1选股公式 | 选股 | 通达信B1选股公式.txt | ✅ |
| B3 | VOL_RED_GREEN - 红肥绿瘦 | 量能 | 自研 | ✅ |
| B4 | ABNORMAL_VOL - 放量异动 | 量能 | 自研 | ✅ |
| B5 | VOL_CONT_SHRINK - 缩量 | 量能 | 自研 | ✅ |
| B6 | KDJ_J_LOW - J值低位 | 指标 | 自研 | ✅ |
| B7 | WEEKLY_MA_BULL - 周线多头 | 趋势 | 自研 | ✅ |
| B8 | MACD_BULL_DEAD - MACD | 指标 | 自研 | ✅ |
| B9 | SHRINK_TO_ABNORMAL - 缩至异动 | 量能 | 自研 | ✅ |
| B10 | BRICK_ULTRA - 砖型图超短 | 选股 | 砖型图超短选股.txt | ✅ |
| B11 | ZHIXING_TREND - 知行趋势 | 指标 | 知行趋势线.txt | ✅ |
| B12 | ZHIXING_WASHOUT - 知行洗盘 | 选股 | 知行洗盘短线.txt | ✅ |
| B13 | VOLUME_B1 - 量能B1 | 选股 | 量能B1选股.txt | ✅ |
| B14 | NORTHBOUND_FLOW - 北向资金 | 实验 | 广发/国金证券 | ✅ |
| B15 | IDIOSYNCRATIC_VOL - 特质波动 | 实验 | 国信证券2022 | ✅ |
| B16 | TURNOVER_UNIFORMITY - 换手均匀 | 实验 | 东吴证券2024 | ✅ |
| B17 | ANALYST_REVISION - 分析师修正 | 实验 | 华泰证券2024 | ✅ |
| B18 | CAPITAL_FLOW_BIG - 大单流向 | 实验 | 东海证券 | ✅ |
| B19 | BRICK_INDICATOR - 砖型图指标 | 指标 | 砖型图.txt | ✅ |

**去重合并建议**：
- ⚠️ `N_STRUCT` (旧版scipy) 与 `alphapulse/strategy/n_pattern.py` (新版精确N型) 重复 → 删除旧版scipy版
- ⚠️ B1_FORMULA vs B1 (strategies/b1.py) → B1_FORMULA 更准确，废弃旧版
- ⚠️ NEEDLE (strategies/needle.py) vs NEEDLE_ENHANCED (needle_enhanced.py) → 合并

### 阶段 C：策略引擎
| 序号 | 策略 | 5,114只回测 | 收益 | 状态 |
|------|------|------------|------|------|
| C1 | B1_FORMULA (多因子AND) | 251 trades | +65.87% | ✅ 最优 |
| C2 | BRICK_ULTRA (砖型超短) | 297 trades | -7.45% | ⚠️ 需修改 |
| C3 | NEEDLE_ENHANCED (单针增强) | 191 trades | +22.66% | ✅ |
| C4 | B1_ENHANCED (知行+洗盘) | — | — | 💤 未测 |
| C5 | B1_SUPER (BBI+KDJ) | 0 signals | 0% | ❌ 文章参数 |
| C6 | 多因子筛选(AND/OR) | — | — | 新项目 |
| C7 | 箱体突破+多维度 | — | — | 新项目 |
| C8 | 板块联动 | — | — | 新项目 |

### 阶段 D：回测验证
| 序号 | 功能 | 位置 |
|------|------|------|
| D1 | 独立回测引擎（8指标+预计算） | `scripts/run_backtest.py` |
| D2 | 向量化回测（防泄漏） | `quant-multifactor/engine/backtest_engine.py` |
| D3 | Walk-Forward验证 | `validation/validate.py` |
| D4 | Combinatorial Purged CV | 同上 |
| D5 | Deflated Sharpe Ratio | 同上 |
| D6 | 网格搜索 | `reports/grid_search_results.json` |
| D7 | 因子IC分析 | `reports/factor_ic_analysis.json` |

### 阶段 E：Agent/自动化
| 序号 | 功能 | 位置 |
|------|------|------|
| E1 | 每日选股（Markdown报告） | `scripts/daily_screener.py` |
| E2 | 晚间复盘（胜率统计） | `scripts/evening_review.py` |
| E3 | 风险监控（5检查项） | `scripts/risk_monitor.py` |
| E4 | QMT下单导出 | `scripts/export_qmt_csv.py` |
| E5 | 每日自动化（因子扫描+策略快照） | `scripts/daily_auto_run.py` |
| E6 | macOS launchd 定时(2:00) | `config/com.alphapulse.daily-auto.plist` |
| E7 | macOS launchd 下载(1:00) | `config/com.alphapulse.full-download.plist` |

### 阶段 F：前端/输出
| 序号 | 功能 | 位置 |
|------|------|------|
| F1 | HTML GUI（NLP转公式+回测面板） | `frontend/index.html` |
| F2 | 回测JSON结果 | `backtest_results/` (5份) |
| F3 | 系统搭建报告 | `reports/system_report.md` |
| F4 | 回测对比报告(V1.0 vs V2.0) | `reports/backtest_comparison_report.md` |

### 阶段 G：外部集成
| 序号 | 功能 | 状态 |
|------|------|------|
| G1 | Claude Code Skills (4/5) | ✅ |
| G2 | Qlib/Backtrader/FinRL研究 | ✅ |
| G3 | yfinance适配器 | ✅ |

---

## 三、重复/冗余清单

| 重复项 | 位置 | 建议 |
|--------|------|------|
| N型结构(旧) vs N型精确(新) | `factors/n_struct.py` vs `strategy/n_pattern.py` | 删除旧版 |
| B1(旧5条件) vs B1_FORMULA(6条件) | `strategies/b1.py` vs `factors/b1_formula.py` | 废弃旧版 |
| NEEDLE vs NEEDLE_ENHANCED | `strategies/needle.py` vs `needle_enhanced.py` | 合并 |
| B1_ENHANCED(知行) vs B1_SUPER(BBI+KDJ) | 2个增强型 | 合并 |
| 回测引擎(2个) | `quantan trade/run_backtest.py` vs `multifactor/backtest_engine.py` | 统一接口 |
| 数据下载(3个) | download_a_share, _smart_downloader, _batch_downloader | 保留smart版 |

## 四、待完成任务诊断

| 任务 | 状态 | 卡住原因 | 修复 |
|------|------|---------|------|
| #37 因子注册表 | in_progress | 已完成但未标记 | 标记完成 |
| #40 开源平台调研 | in_progress | Agent已返回结果 | 标记完成 |
| #41 Bug修复 | in_progress | 3 bug已全部修复 | 标记完成 |
| #42 API限速+下载 | in_progress | Agent已完成 | 标记完成 |
| #44 6-Agent流水线 | in_progress | Agent仍在运行 | 等待/检查 |
| #45 GitHub项目集成 | in_progress | Agent未返回 | 等待/检查 |

---

## 五、因子选股配置全览

### 因子类型分类

| 类型 | 数量 | 因子列表 |
|------|------|---------|
| **形态因子** | 2 | N_STRUCT(旧), N_PATTERN(新,strategy/) |
| **指标因子** | 4 | KDJ_J_LOW, MACD_BULL_DEAD, BRICK_INDICATOR, ZHIXING_LINES |
| **量能因子** | 5 | VOL_RED_GREEN, ABNORMAL_VOL, VOL_CONT_SHRINK, SHRINK_TO_ABNORMAL, VOLUME_B1 |
| **趋势因子** | 2 | WEEKLY_MA_BULL, ZHIXING_TREND |
| **选股方案** | 5 | B1_FORMULA, BRICK_ULTRA, ZHIXING_WASHOUT, NEEDLE, B1_SUPER |
| **实验因子** | 5 | NORTHBOUND, IDIOSYNCRATIC_VOL, TURNOVER_UNIFORMITY, ANALYST_REVISION, CAPITAL_FLOW_BIG |
| **多因子模块** | 4 | 趋势+回调, MA排列, 动量, 量价(新项目) |

### 因子IC表现（P0配置建议）

| 排序 | 因子 | IC | 使用建议 |
|------|------|-----|---------|
| 1 | N_STRUCT | -0.387 | 反向过滤（出现则减分） |
| 2 | KDJ_J_LOW | +0.019 | ✅ 正向选股 |
| 3 | B1_FORMULA | +0.012 | ✅ 综合选股 |
| 4 | SHRINK_TO_ABNORMAL | +0.007 | ✅ 辅助确认 |
| 5 | BRICK_ULTRA | +0.004 | ⚠️ 弱正向 |

### 选股配置建议

```
优先级1（核心）:
  B1_FORMULA: j_threshold=13, pct_change_range=3, amplitude_max=9
  + KDJ_J_LOW: j_threshold=13

优先级2（辅助）:
  SHRINK_TO_ABNORMAL: ratio=0.25
  + MACD_BULL_DEAD: fast=12, slow=26, signal=9

优先级3（过滤）:
  N_STRUCT: 反向过滤（出现→排除）
  + ZHIXING_TREND: 知行趋势确认

网格搜索最优:
  B1: j_threshold=23, pct_range=4 (信号×1.9)
  NEEDLE: shadow_ratio=0.3, j_threshold=28 (信号×4.4)
```

## 六、与原始方案对比

| 维度 | 原始方案 | 当前系统 | 差异 |
|------|---------|---------|------|
| **因子来源** | 8个（TDX公式） | 19个（TDX+券商+实验） | +11 |
| **策略** | B1/砖型/单针 | +B1增强/箱体突破/板块联动/SuperB1 | +5 |
| **数据** | 通达信.day | akshare/baostock（5,229只） | 替代 |
| **回测** | VeighNa | 独立引擎+向量化（8指标+DSR） | 增强 |
| **验证** | 无 | Walk-Forward/Purged CV/DSR Gate | 新增 |
| **前端** | 无 | HTML GUI（NLP转公式） | 新增 |
| **自动化** | 无 | launchd定时+4个Agent脚本 | 新增 |
| **风控** | 无 | 3维监控+硬约束+熔断 | 新增 |
| **外部集成** | 无 | 4个Claude Skills+GitHub项目调研 | 新增 |

## 七、系统执行流程

```
[数据准备]
  download_a_share_data.py → 外接硬盘CSV
  _smart_downloader.py → 交替双源下载
  
[因子计算]
  factor_registry.py → 调用19个因子
  IC分析 → 有效性排名
  
[策略筛选]
  B1_FORMULA(核心) + KDJ_J_LOW + SHRINK辅助
  BRICK_ULTRA/NEEDLE 备用
  多因子AND/OR选择
  
[回测验证]
  独立引擎(8指标) → 收益/回撤/夏普/Calmar/Sortino
  Walk-Forward → 降解比检查
  DSR ≥ 0.95 → 上线门槛
  
[Agent输出]
  daily_screener → Markdown选股报告
  evening_review → 胜率统计
  risk_monitor → 风控告警
  
[定时调度]
  launchd 1:00 → 全量下载
  launchd 2:00 → 因子扫描+策略快照
  盘中14:30 → 选股
  盘后15:30 → 复盘
```
