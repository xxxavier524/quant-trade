# AlphaPulse-A v3.0 系统设计规范

> 日期: 2026-05-26 | 基于: AlphaPulse-A v2.0 现有40因子系统
> 目标: 缩短通达信选股流程 → 自动化每日选股+诊断+排序+推送

---

## 一、背景与目标

### 核心痛点
- 每天手动在通达信看600-700只票，B1B2/单针/砖型图超短三种方式分别跑
- 选股后无系统排序，无板块过滤，无大盘判断
- 回测关注长期指标（年化/夏普），实际需要的是短期（买后N日）表现追踪

### 目标
将每日选股流程从2-3小时手动操作缩短为15分钟自动运行，15:30收盘后一键输出：
- 三策略各自Top50%精选股票列表
- 每只股票五维诊断评分(S-D)+AI一句话摘要
- 板块标注+大盘档位+飞书推送
- 夜场自动回测优化，次日结果更新

---

## 二、系统架构

### 新增模块（10个）

```
alphapulse/
├── market/                    # 大盘+板块（新增）
│   ├── macro_position.py      #   大盘多维度评分
│   └── sector_strength.py     #   板块强度+过滤
├── ranking/                   # 排序引擎（新增）
│   ├── factor_weighter.py     #   IC-IR+衰减权重计算
│   └── stock_ranker.py        #   多因子排序+Top50%
├── diagnosis/                 # 个股诊断（新增）
│   ├── stock_scorer.py        #   五维评分(S-D)
│   └── llm_diagnosis.py       #   LLM一句话摘要
├── backtest/                  # 短期回测（新增）
│   ├── short_term_bt.py       #   买后N日表现追踪
│   └── bt_storage.py          #   SQLite存储
├── ml/                        # ML引擎（新增）
│   ├── xgb_optimizer.py       #   XGBoost因子组合优化
│   └── auto_research.py       #   Auto-Research循环
├── notify/                    # 推送（新增）
│   └── feishu_bot.py          #   飞书webhook
└── ui/                        # GUI（新增）
    └── app.py                 #   Streamlit 6-Tab界面
```

### 修改模块

| 文件 | 改动 |
|------|------|
| `scripts/daily_screener.py` | 接入板块过滤+因子排序+个股诊断+飞书推送 |
| `scripts/run_backtest.py` | 新增 `--mode short` 短期回测模式 |
| `scripts/_smart_downloader.py` | 增量更新+多源降级+断点续传 |
| `scripts/daily_auto_run.py` | 接入夜场回测+auto-research优化 |
| `scripts/_monitor_runner.py` | 进程守护+卡死检测+错误自动修复 |
| `scripts/start_web.py` | 替换为Streamlit启动 |
| `config/settings.py` | 新增配置项 |

### 外部部署

| 项目 | 路径 | 方式 |
|------|------|------|
| Vibe-Trading | `/Users/qiushixuan/cc/vibe-trading/` | Docker独立部署，MCP调用 |

---

## 三、详细设计

### 3.1 数据管线

**多源降级链**:
```
日线: akshare → baostock → pytdx → 本地CSV缓存
实时: akshare.spot_em → pytdx → 上次快照(标记过期)
板块: akshare(东方财富) → akshare(同花顺备用)
指数: akshare → yfinance
```

**并发控制**:
- ThreadPoolExecutor(max_workers=3)
- random.uniform(0.5, 1.5)s 请求间隔
- 单源连续5次失败 → 暂停10分钟 → 自动恢复
- 单股票超30秒 → skip+记录
- 全局超30分钟 → 截断输出

**更新策略**:
- 工作日: 增量（最近1天数据），约5-10分钟
- 周末: 全量校验（5229只完整性检查）

**API接口文档**（实施前必查）:
- akshare: https://akshare.akfamily.xyz（5-10 req/s）
- baostock: http://baostock.com/baostock/index.php/Python_API文档（匿名60次/分）
- pytdx: https://pytdx-docs.readthedocs.io（TCP 7709，IP定期变）
- yfinance: https://github.com/ranaroussi/yfinance（60 req/min，需curl_cffi）

### 3.2 大盘+板块

**大盘多维度评分** (`macro_position.py`):
- 四维度各25分: 均线排列/量价关系/市场情绪/北向资金
- 总分0-100 → 五档: 多头/震荡偏多/震荡/震荡偏空/空头
- 阈值可配置: `config/market_params.json`
- 档位影响选股: 多头正常选、震荡提阈值、空头仅Top20%

**板块强度** (`sector_strength.py`):
- 东方财富行业分类 (akshare.stock_board_industry_hist_em)
- 评分: 板块超额收益+涨跌比+成交额趋势+龙头强度
- 只保留评分前50%的强势板块
- 选股结果标注板块+过滤弱势板块

### 3.3 选股引擎

保留现有三策略逻辑，增强输出:
```
B1B2 (B1_B2_B3策略): 7条件AND → B1底部挖掘 → B2阳线确认 → B3锁仓
砖型图 (BRICK_THREE_TYPES): N起跳/上涨中继/横盘突破 三子类型
单针 (NEEDLE_WASHOUT): 长下影+J超卖+N型洗盘确认
```

### 3.4 因子权重+排序

**权重计算** (`factor_weighter.py`):
- IC-IR + 指数衰减加权（半衰期30日）
- 每策略独立权重矩阵，不同前向窗口:
  - B1B2: 5/10/20日（波段盈亏比）
  - 砖型图: 1/2/3日（次日涨幅优先）
  - 单针: 3/5/10日（短期连续涨跌）
- 每周重算权重 → `config/factor_weights.json`

**排序输出** (`stock_ranker.py`):
- Z-score归一化 (winsorize 1%/99%)
- 加权求和 → 综合得分
- 大盘档位动态阈值
- 板块过滤 → 每策略Top50%

### 3.5 个股诊断

**五维评分** (`stock_scorer.py`):

| 维度 | 满分 | 核心指标 |
|------|------|---------|
| 技术面 | 30 | MA排列/KDJ J值/MACD/周线多头 |
| 量能 | 20 | 放量异动/缩量/红肥绿瘦/倍量柱 |
| 形态 | 20 | N型结构/砖型值/关键K线/波段识别 |
| 风控 | 15 | S1信号/DD信号/趋势线/动态止损 |
| 板块共振 | 15 | 板块强度/板块内排名/龙头关联 |

**评级映射**: S(≥85) A(70-84) B(55-69) C(40-54) D(<40)

**LLM诊断** (`llm_diagnosis.py`):
- 输入: 股票代码+评分明细+因子快照+K线摘要
- 输出: 一句话诊断摘要 (DeepSeek-v4-flash, <50 tokens)
- 格式: "J值低位超卖+缩量企稳+周线多头支撑，盈亏比优，注意前高压力"

参考项目: https://github.com/ZhuLinsen/daily_stock_analysis (38k Stars)

### 3.6 短期回测

**核心理念**: 不关注年化/夏普，关注每笔买入后短期表现

**指标矩阵**:
- B1B2: 首次上涨天数/5-20日波段涨幅/最大回调/盈亏比/清仓收益率
- 砖型图: ★次日>成本+3%概率(核心)/次日>+5%概率/当天出成本区/清仓收益
- 单针: 3-10日累计涨跌/连续上涨天数/反弹至前高天数/买后3日涨概率

**存储** (SQLite):
```sql
backtest_signals: id/symbol/strategy/signal_date/buy_price/sector/macro_level
backtest_daily_track: signal_id/day_n/close/high/low/return_pct/drawdown_pct
backtest_exit: signal_id/exit_date/exit_price/exit_reason/total_return/hold_days
```

**卖出信号**: 保留现有S1/DD/趋势线跌破/动态止损/放飞减仓体系

### 3.7 AI/ML引擎

**Phase A - 结构化ML** (`ml/xgb_optimizer.py`):
- XGBoost/LightGBM学习因子非线性组合
- 每月重新训练（6个月数据窗口）
- 对比: 线性加权 vs ML加权 → 选次日胜率高者
- 特征: 40因子值 + 板块one-hot + 大盘档位
- 目标: 前向1日/3日/5日收益方向

**Phase B - CNN形态识别**（后续迭代）:
- K线图→图片→CNN识别形态（N型/W底/头肩底等）
- 替代人工看图，降低600-700只票筛选负担
- 参考: YOLOv8 chart pattern detection (93.2% mAP)

### 3.8 Auto-Research 循环

**参考**: Karpathy autoresearch (https://github.com/karpathy/autoresearch, 72k Stars)

**夜场执行** (03:00-05:30, 2.5小时):
```
Round 1-3: 策略参数微调 (j_threshold/shrink_ratio/brick_amplitude等)
Round 4-6: 因子权重优化 (IC-IR权重±20%实验)
Round 7-8: XGBoost模型重训练
```

**保留规则**: 新参数胜率>旧×1.05→替换 / 否则保留 / 最近3天快照可回滚
**周末加量**: 全量回测(2020-今)+网格搜索×2+CNN训练(未来)

### 3.9 Streamlit GUI

**6 Tab布局**:

| Tab | 内容 |
|-----|------|
| 选股结果 | 策略切换/板块筛选/评级筛选/可排序表格/点击展开K线+诊断 |
| 回测追踪 | 买后N日表现曲线/胜率热力图/策略对比 |
| 大盘板块 | 大盘评分仪表盘/板块强度排行/北向资金趋势 |
| 因子详情 | IC变化曲线/因子权重/分布直方图 |
| AI诊断 | 选中个股五维雷达图+LLM深度诊断 |
| Vibe | 自然语言输入→Vibe-Trading因子生成 |

**顶部状态栏**: 大盘评分/强势板块数/各策略信号数
**交互**: 点击展开/双击全屏K线/筛选联动
**飞书按钮**: 一键推送当日摘要

### 3.10 飞书推送

**格式**:
```
📊 AlphaPulse 选股日报 (2026-05-26)
大盘: 65/100 震荡偏多 | 强势: 电子/医药/计算机

B1B2 Top5:
1. 000001平安银行 A(82) J低位+放量突破+周线多头
...

砖型图 Top5: ...
单针 Top5: ...

详情: http://localhost:8501
```

### 3.11 每日时间线

```
15:30  收盘选股 (10-15min)
       ├─ 数据增量更新 → 大盘评分 → 板块强度
       ├─ 三策略选股 → 因子排序 → Top50% → 个股诊断
       ├─ Markdown报告 + 飞书推送
       └─ 容错: 超时截断/失败降级/自动跳过

00:00  夜场启动
00:00-00:30  数据校验（工作日增量/周末全量）
00:30-03:00  三策略短期回测（近6个月）
03:00-05:30  Auto-Research优化循环
05:30-06:30  因子权重重算+IC更新
06:30-07:00  日报+飞书推送优化结果
```

### 3.12 容错体系

```
每步: try/except → 日志 → 继续下一步
重试: 指数退避 1s→2s→4s→8s→skip
数据降级: akshare→baostock→pytdx→本地缓存
超时杀: 单票>30s skip / 全局>30min截断
自动修复: 脚本exit≠0→读stderr→常见错误自动处理
进程守护: 5分钟心跳 / 30分钟无输出→kill+重启
```

---

## 四、模块依赖

```
数据管线 ──→ 大盘板块 ──→ 选股引擎 ──→ 排序引擎 ──→ 个股诊断 ──→ GUI/推送
                │                           │
                └───────────┬───────────────┘
                            ↓
                        短期回测 ←── ML引擎 ←── Auto-Research
                            │
                        因子权重重算 → 次日选股
```

---

## 五、配置项

```python
# config/settings.py 新增
DATA_SOURCES = ["akshare", "baostock", "pytdx", "yfinance"]  # 优先级
MAX_CONCURRENT_WORKERS = 3
REQUEST_INTERVAL = (0.5, 1.5)  # 随机延迟范围
CIRCUIT_BREAKER_FAILS = 5  # 连续失败熔断阈值
CIRCUIT_BREAKER_PAUSE = 600  # 熔断暂停秒数

MACRO_THRESHOLDS = {"bull": 80, "slightly_bull": 60, "neutral": 40, "slightly_bear": 20}
SELECTION_TOP_PCT = 0.5  # Top50%
BACKTEST_MODE = "short"  # 短期模式
AUTO_RESEARCH_HOURS = (3, 5.5)  # 优化时间窗口
DIAGNOSIS_WEIGHTS = {"technical": 30, "volume": 20, "pattern": 20, "risk": 15, "sector": 15}

FEISHU_WEBHOOK_URL = ""  # 待配置
VIBE_TRADING_URL = "http://localhost:8899"
STREAMLIT_PORT = 8501
```

---

## 六、验证清单

- [ ] 数据管线: 4源全通，降级链每级有效，并发不超限
- [ ] 大盘板块: 评分五档正常输出，板块过滤有效减少选股数
- [ ] 选股引擎: 三策略各自输出信号，B1B2/Brick/Needle独立运行
- [ ] 因子排序: IC-IR权重每周更新，Top50%输出含得分+排名
- [ ] 个股诊断: 五维评分S-D合理分布，LLM摘要无幻觉
- [ ] 短期回测: SQLite存储正常，买后N日追踪指标完整
- [ ] ML引擎: XGBoost对比线性加权，胜率提升可量化
- [ ] Auto-Research: 夜场循环正常，参数自动更新+回滚
- [ ] GUI: 6 Tab全部渲染，交互正常，K线图标注清晰
- [ ] 飞书推送: 消息格式正确，按时间线触发
- [ ] Vibe-Trading: Docker正常运行，MCP工具可调用
- [ ] 容错: 数据源降级/超时/卡死/自动修复各场景通过
- [ ] 测试: `python -m pytest tests/ -v` 全部通过
- [ ] E2E: 500只样本完整选股流程 < 30分钟
