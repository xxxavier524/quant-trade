# 选股体系补充前后对比

> 按用户指令逐项调整 | 2026-05-24

---

## 总览：补充前后对照

| 维度 | 补充前 | 补充后 | 用户指令 |
|------|--------|--------|---------|
| **入口方式** | CLI脚本：`python scripts/xxx.py` | Web UI：`python scripts/start_web.py` → localhost:8899 | "正式使用还得用Python打开吗" |
| **数据更新** | 手动下载，数据滞后 | launchd每天15:30自动增量更新 | "每天全量更新""时间改为收盘后3点半" |
| **选股时机** | 手动执行 | 收盘后自动触发：更新→选股→输出 | "更新完后立即进行选股" |
| **股票池** | 全市场无过滤 ~5200只 | 硬过滤后 ~4800只(排除ST/退市/涨停) | "增加过滤" |
| **策略数量** | 5个策略全启用 | 3个主力(B1/Brick/B1增强)，2个废弃(Needle/SuperB1) | "梳理所有因子，分析并给出完整流程" |
| **因子数量** | 23个因子全注册 | 4核心+5废弃+其余降级观察 | 同上 |
| **信号评估** | 单策略独立输出 | 2+策略共识评分(⭐~⭐⭐⭐) | 隐含在流程设计中 |
| **案例验证** | 无 | 46只案例100%命中，确切日期可查 | "回测我的案例，是否能选出来" |
| **两阶段模型** | 无 | 行业轮动+β预测，20次参数优化 | "加入到量化系统中，完成后通过20次回测" |
| **论文研究** | 无 | 4个Skills(搜索/提取/复现/翻译) | "复刻这4个skill搭建工作流" |
| **外部对标** | 无 | HelloGitHub(25项目)+Vibe-Trading(8模块) | "阅读这个项目，逐个功能模块对比" |
| **系统文档** | 无 | README.md(12章节完整文档) | "给我一个当前系统的说明文档" |

---

## 一、入口与自动化

### 补充前
```
$ python scripts/daily_screener.py --output signals.csv
$ python scripts/run_backtest.py --strategy B1 --sample 100
$ python scripts/risk_monitor.py --positions positions.csv
```
每次操作需手动输入脚本名+参数。

### 补充后
```
$ python scripts/start_web.py
→ 浏览器打开 http://localhost:8899
→ 6个面板：仪表盘/选股扫描/回测中心/因子体系/案例检测/风控状态
```
一键启动，浏览器操作。同时launchd自动在每天15:30执行`after_close.py`。

**实现方式**: FastAPI后端(8个API端点) + 纯HTML/JS前端(无框架依赖)，复用现有策略模块。

---

## 二、数据管道

### 补充前
- 手动执行`download_a_share_data.py`或`_smart_downloader.py`
- 数据日期不一致（部分卡在数月前）

### 补充后
- `daily_update.py`：baostock增量更新，仅拉取最近10天，~0.15s/只，全量~12分钟
- `after_close.py`：更新→选股串联脚本
- launchd定时：每天15:30自动触发
- ST缓存：`data/st_cache.json`(362只ST+1116只退市)，秒级加载

**实现方式**: 
- 复用现有baostock连接，只查询最近10天而非全量历史
- 文件存在+大小≥800字节自动跳过（断点续传）
- JSON缓存替代每次baostock全量查询（从~30秒降至<0.1秒）

---

## 三、过滤系统

### 补充前
```
全市场5200只 → 直接选股 → 可能选到ST/退市/涨停股
```

### 补充后
```
全市场5200只
  → 硬过滤: ST(362只) + 退市(1116只) + 涨停(约80只/日)
  → 约4800只进入选股
  → 软过滤: N_STRUCT(IC=-0.387反向，回测阶段降低置信度)
  → 输出带过滤标记的信号
```

**实现方式**:
- `alphapulse/utils/filters.py`：ST/退市用JSON缓存O(1)查表，涨停按代码前缀计算涨跌停板(主板±10%/双创±20%/北交±30%/ST±5%)
- N_STRUCT不在每日快速选股中执行（太慢，4834只需要scipy.signal），保留在回测阶段

---

## 四、策略与因子体系

### 补充前（23因子+5策略全启用）

| 类别 | 数量 | 内容 |
|------|------|------|
| 核心技术因子 | 8 | N_STRUCT, VOL_RED_GREEN, ABNORMAL_VOL, VOL_CONT_SHRINK, KDJ_J_LOW, WEEKLY_MA_BULL, MACD_BULL_DEAD, SHRINK_TO_ABNORMAL |
| 选股方案 | 4 | B1_FORMULA, BRICK_ULTRA, ZHIXING_WASHOUT, VOLUME_B1 |
| 纯指标 | 3 | ZHIXING_TREND, BRICK_INDICATOR, ZHIXING_LINES |
| 券商实验 | 5 | NORTHBOUND_FLOW, IDIOSYNCRATIC_VOL, TURNOVER_UNIFORMITY, ANALYST_REVISION, CAPITAL_FLOW_BIG |
| AI模型 | 3 | INDUSTRY_ROTATION, BETA_PREDICTION, TWO_STAGE_SELECTION |

策略：B1_FORMULA, BRICK_ULTRA, NEEDLE_ENHANCED, B1_ENHANCED, B1_SUPER

### 补充后（按IC+案例+回测三维审计后分级）

| 等级 | 因子 | 依据 |
|------|------|------|
| ★★★★★ 核心 | KDJ_J_LOW(IC+0.019), B1_FORMULA(IC+0.012), SHRINK_TO_ABNORMAL(IC+0.007) | IC正向+案例100%+回测正收益 |
| ★★★★☆ 反向过滤 | N_STRUCT(IC-0.387) | IC最强反向，出现→降级 |
| ★★★☆☆ 辅助 | MACD_BULL_DEAD, BRICK_ULTRA, ZHIXING_TREND | IC弱但方向明确 |
| ★☆☆☆☆ 废弃 | VOLUME_B1(IC=NaN), B1_SUPER(0信号), NEEDLE_ENHANCED(案例4.4%) | 无有效信号 |
| 降级观察 | 5个券商因子(实测IC全为负/近0) | 代理精度不足，不可用于选股 |

策略：B1_FORMULA(主力)+BRICK_ULTRA(辅助)+B1_ENHANCED(确证)，Needle/B1_SUPER移除。

**实现方式**:
- 基于`reports/factor_ic_analysis.json`(17因子IC实测)
- 基于`reports/case_detection_results.json`(46案例×5策略命中率)
- 基于`backtest_results/`(3策略回测收益对比)
- 基于`reports/two_stage_opt_results.json`(20次参数优化)

---

## 五、选股输出

### 补充前
```
单策略信号列表（CSV/JSON），无评分，无过滤标记
```

### 补充后
```
共识评分体系：
  ⭐⭐⭐ 三策略共识 (B1 + Brick + B1增强)
  ⭐⭐   双策略共识
  ⭐     B1单策略

输出包含：
  - 过滤统计(ST排除数/退市排除数/涨停排除数)
  - N_STRUCT标记(软过滤)
  - 每只股的总信号数+最后信号日期
  - JSON + CSV双格式
```

**实现方式**: `scripts/friday_screener.py`和`scripts/thu_screener.py`中`consensus`字典计算多策略交集。

---

## 六、新增模块一览

| 模块 | 文件 | 功能 | 用户指令来源 |
|------|------|------|------------|
| Web服务 | `scripts/start_web.py` | FastAPI 8端点+前端 | "正式使用还得用Python打开吗" |
| 前端面板 | `frontend/index.html` | 6面板API驱动 | 同上 |
| 收盘流水线 | `scripts/after_close.py` | 更新→选股串联 | "收盘后3点半更新+选股" |
| 增量更新 | `scripts/daily_update.py` | baostock最近10天 | "每天全量更新" |
| 周五选股 | `scripts/friday_screener.py` | 指定日期全量选股 | "对周五的进行选股" |
| 周四选股 | `scripts/thu_screener.py` | 指定日期快速选股 | "按周四的收盘数据执行选股" |
| 案例日期 | `scripts/backtest_cases_dates.py` | 每只案例的确切信号日期 | "哪天被选出来的，这很重要" |
| 硬过滤 | `alphapulse/utils/filters.py` | ST/退市/涨跌停/N_STRUCT | "增加过滤" |
| 两阶段AI | `alphapulse/factors/industry_rotation.py` | 行业轮动Stage1 | "加入到量化系统中" |
| 两阶段AI | `alphapulse/factors/beta_fundamental.py` | β预测Stage2 | 同上 |
| 两阶段策略 | `alphapulse/strategies/two_stage_selection.py` | 双层垂直选股 | 同上 |
| 参数优化 | `scripts/run_two_stage_opt.py` | 20次回测寻参 | "完成后通过20次回测确立最佳参数" |
| 论文Skills | `.claude/skills/paper-*.md` | 搜索/提取/复现/翻译 | "复刻这4个skill" |
| 系统文档 | `README.md` | 12章完整文档 | "给我一个当前系统的说明文档" |
| 因子审计 | `reports/factor_audit_and_pipeline.md` | 23因子逐项审计 | "梳理所有的因子，分析并给出完整流程" |
| 外部对标 | `reports/hellogithub_quant_comparison.md` | 25项目对比 | "逐个看120份月刊报告" |
| 外部对标 | `reports/vibe_trading_comparison.md` | 8模块深度对比 | "阅读这个项目...加入我的系统" |
| 变更记录 | `reports/system_changes_before_after.md` | 本文件 | "列一个补充前后的表格" |

---

## 七、系统当前状态

```
每日流程 (全自动，launchd 15:30触发):
  
  15:30  after_close.py 启动
    │
    ├─ Step 1: daily_update.py
    │   baostock增量拉取最近10天 → 5229只股票CSV更新
    │   断点续传，已有数据自动跳过
    │   耗时: ~12分钟
    │
    ├─ Step 2: friday_screener.py  
    │   加载5229只 → 硬过滤(排除ST/退市/涨停) → ~4800只
    │   运行B1+Brick+B1增强 三策略扫描
    │   共识计算 → 输出JSON+CSV
    │   耗时: ~8分钟
    │
    └─ Step 3: 输出简报
        共识信号数 + Top picks + 过滤统计
        日志写入 logs/after_close_stdout.log

手动操作:
  python scripts/start_web.py          # Web UI
  python scripts/thu_screener.py       # 指定日期选股
  python scripts/backtest_cases.py     # 案例检测
  python scripts/run_backtest.py       # 策略回测
```
