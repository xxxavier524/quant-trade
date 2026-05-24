# AlphaPulse-A 完整交易体系实现计划

> 目标读者：Claude Sonnet 模型（用于后续并行执行）
> 基于：用户交易框架 vs 现有系统的Gap分析 (`reports/trading_system_gap_analysis.md`)
> 总工作量：~15个新因子 + 3个策略重写 + 风控重写 + 7个知识点编码

---

## 环境信息

- **项目路径**: `/Users/qiushixuan/cc/quantan trade`
- **Python**: `.venv/bin/python` (3.14.4)
- **数据路径**: `/Volumes/Mac-480g外接/quantan_data/day/` (5229只A股CSV)
- **测试**: `python -m pytest tests/ -v`
- **提交**: `git add -A && git commit -m "..."` (每次完成一批后提交)

## 核心约束

- 每个因子独立一个 `.py` 文件，实现 `compute(data: pd.DataFrame, **params) -> pd.Series` 接口
- 向量化优先(pandas/numpy)，禁止逐行循环
- 新增因子注册到 `alphapulse/factors/factor_registry.py`
- 每个因子至少一个单元测试（`tests/`目录）
- 完成后 `git commit`

## 系统上下文

因子注册表在 `alphapulse/factors/factor_registry.py`，通过 `FACTOR_REGISTRY` 字典注册。
策略在 `alphapulse/strategies/` 目录，每个策略实现 `generate_signals(data, symbol, **params) -> pd.DataFrame`。
数据列：date, open, high, low, close, volume, amount, turnover。
白线 = 知行趋势线 EMA(EMA(C,10),10)，实现在 `zhixing_trend.py`。
黄线 = 知行多空线 (MA20+MA60+MA120+MA250)/4，也在 `zhixing_trend.py`。

---

## 阶段一：多头因子（买入信号）— 可并行

### Agent 1-A: 关键K线 + 暴力K + 倍量柱增强

**角色提示词**:
```
你是量化因子开发专家。你的任务是在AlphaPulse-A系统中实现3个多头因子。

工作目录：/Users/qiushixuan/cc/quantan trade

1. 关键K线 (alphapulse/factors/key_kline.py):
   - 定义：近20日内涨幅最大的阳线，成交量显著放大(>2倍20日均量)
   - 输出：bool Series，标记关键K线位置
   - compute(data, lookback=20, vol_mult=2.0) -> pd.Series

2. 暴力K (alphapulse/factors/violent_kline.py):
   - 定义：当日涨幅>5%且成交量>3倍20日均量的阳线
   - 输出：bool Series
   - compute(data, pct_threshold=5.0, vol_mult=3.0) -> pd.Series

3. 倍量柱增强 (alphapulse/factors/double_volume_bar.py):
   - 定义：当日成交量>=前一日2倍，且为阳线
   - 输出：bool Series
   - compute(data, mult=2.0) -> pd.Series

约束：
- 全部向量化实现，无逐行循环
- 每个因子注册到 factor_registry.py (type="core")
- 写单元测试到 tests/test_new_factors.py
- data列: open,high,low,close,volume,amount,turnover，index=date
- 完成后 git commit -m "Add key K-line, violent K-line, double volume bar factors"
```

### Agent 1-B: 筹码集中 + 对称结构 + 填坑出坑

**角色提示词**:
```
你是量化形态识别专家。你的任务是在AlphaPulse-A系统中实现3个形态因子。

工作目录：/Users/qiushixuan/cc/quantan trade

1. 筹码集中 (alphapulse/factors/chip_concentration.py):
   - 代理实现（无真实筹码数据）：用价格振幅收窄+换手率下降来近似
   - 最近20天振幅<15%，最近10天振幅<最近20天振幅×0.6，换手率（用volume/amount估算）趋势下降
   - compute(data, window=20, amplitude_max=15.0) -> pd.Series (0-1连续值)

2. 对称结构 (alphapulse/factors/symmetric_structure.py):
   - 识别价格走势中的对称形态：左侧N型下跌 + 右侧N型上涨，形成V型或W型对称
   - 用scipy.signal.argrelextrema找局部极值点，检查左右两侧对称性
   - compute(data, tolerance=0.05, min_leg_len=5) -> pd.Series (bool)

3. 填坑出坑 (alphapulse/factors/fill_pit_exit_pit.py):
   - "坑"的定义：价格从高点回落>15%后横盘整理（3-10天振幅<8%）
   - "出坑"的定义：放量（>1.5倍均量）突破整理区间上沿
   - compute(data, drop_pct=15.0, consolidation_days=3, breakout_vol_mult=1.5) -> pd.Series (bool)

约束同Agent 1-A。
```

### Agent 1-C: 长阴短柱 + 波段识别 + 关键K ABC节点

**角色提示词**:
```
你是量化技术分析专家。你的任务是在AlphaPulse-A系统中实现3个因子。

工作目录：/Users/qiushixuan/cc/quantan trade

1. 长阴短柱 (alphapulse/factors/long_yin_short_column.py):
   - 定义：阴线（收盘<开盘）但成交量<前一日成交量×0.7，阴线实体长度>1%
   - 含义：下跌但缩量=主力未出货
   - compute(data, vol_shrink=0.7, body_min_pct=1.0) -> pd.Series (bool)

2. 波段识别 (alphapulse/factors/wave_identifier.py):
   - 识别建仓波、拉升波、冲刺波三个阶段
   - 建仓波：价格横盘或缓涨（20日涨幅<10%），成交量温和
   - 拉升波：价格加速上涨（10日涨幅>15%），成交量放大
   - 冲刺波：价格急剧上涨（5日涨幅>20%），成交量巨量
   - compute(data) -> pd.DataFrame with columns [accumulation, lift, sprint] (bool)
   
3. 关键K ABC节点 (alphapulse/factors/key_k_abc.py):
   - A点：阶段最低点（20日低点+反弹>3%确认）
   - B点：A点后首次回调低点（不低于A点）
   - C点：突破B点对应的高点
   - compute(data, lookback=20) -> pd.Series with values: 0=none, 1=A, 2=B, 3=C

约束同Agent 1-A。
```

---

## 阶段二：空头因子（卖出信号）— 可并行

### Agent 2-A: S1 + DD + 趋势线跌破

**角色提示词**:
```
你是量化风控专家。你的任务是在AlphaPulse-A系统中实现3个卖出信号因子。

工作目录：/Users/qiushixuan/cc/quantan trade

1. S1 最强卖出信号 (alphapulse/factors/s1_sell_signal.py):
   - 定义：波段最高点出现放巨量阴线
   - 条件：
     a) 当日为阴线(close < open)
     b) 当日成交量是近20日最高
     c) 当日成交量 > 近20日阳量均值的2倍
     d) 前5日至少有3日上涨（确认前期加速）
     e) 排除假阴真阳(close > prev_close)——假阴真阳时S1降级为观察
   - compute(data, vol_window=20, vol_mult=2.0) -> pd.Series (0=none, 1=S1, 2=S1疑似/假阴真阳)

2. DD 连续下跌确认 (alphapulse/factors/dd_sell_signal.py):
   - DD：当日收盘价 < 前一日最低价
   - DD增强：连续2天或以上出现DD
   - compute(data) -> pd.Series (0=none, 1=DD, 2=DD增强/连续2+天)
   - 注意：用shift(1)防未来函数

3. 趋势线跌破 (alphapulse/factors/trendline_break.py):
   - 白线：EMA(EMA(C,10),10) — 从zhixing_trend导入
   - 黄线：(MA20+MA60+MA120+MA250)/4 — 从zhixing_trend导入
   - 跌破白线：close < 白线，且前一日的close >= 白线
   - 跌破黄线：同上逻辑
   - 反弹确认：跌破后次日close重新站上趋势线 → 假跌破
   - compute(data) -> pd.DataFrame with columns [break_white, break_yellow, fake_break_white, fake_break_yellow]
   - ！！！关键：所有比较必须shift(1)防未来函数——判断"今日是否跌破"用的是今日close vs 今日白线，但交易决策在次日

约束：
- 全部向量化，无循环
- 注册到factor_registry.py (type="risk")
- 写测试到tests/test_sell_factors.py
- 完成后 git commit
```

### Agent 2-B: 止损重写 + 放飞减仓信号

**角色提示词**:
```
你是量化仓位管理专家。你的任务是在AlphaPulse-A系统中重写止损逻辑并实现放飞信号。

工作目录：/Users/qiushixuan/cc/quantan trade

1. 动态止损 (alphapulse/factors/dynamic_stop_loss.py):
   - 替代现有的固定-10%止损
   - 止损价 = min(入场日最低价 - 3×最小变动价位, 前N型结构低点 - 3×最小变动价位)
   - 对于未找到N型结构的：使用入场日最低价 - 5×最小变动价位
   - 最小变动价位：主板0.01，其他同
   - compute(data, entry_date, entry_price, n_pattern_low=None) -> float (止损价)

2. 放飞减仓信号 (alphapulse/factors/fly_away.py):
   - 连续2-3根中长阳（涨幅>3%/日）后触发减仓
   - 减仓比例：第2根中长阳减1/4，第3根减1/3
   - 砖型图第4块砖触发减仓（需引用brick_ultra的brick计数）
   - 白线以上加速（close > 白线 且 涨幅>5%）触发更大减仓
   - compute(data, brick_count=None) -> pd.DataFrame with columns [fly_signal, reduce_ratio, reason]
   
3. 更新 alphapulse/utils/backtest_utils.py 中的止盈止损常量：
   - STOP_LOSS_PCT -> 改用 dynamic_stop_loss
   - TAKE_PROFIT_PCT -> 改用 fly_away 逐步减仓

约束同Agent 2-A。
```

---

## 阶段三：策略重写 — 阶段二完成后执行

### Agent 3-A: B1/B2/B3 完整战法

**角色提示词**:
```
你是量化策略开发专家。你的任务是将AlphaPulse-A的B1策略重写为完整的B1→B2→B3递进战法。

工作目录：/Users/qiushixuan/cc/quantan trade

当前已有的B1_FORMULA在alphapulse/strategies/b1_formula_strategy.py。需要重写为alphapulse/strategies/b1_b2_b3_strategy.py。

B1入场条件（底部挖掘）:
1. 股价在底部区间（近60日跌幅>10%或近120日横盘）
2. KDJ_J_LOW: J<13（超卖）
3. 缩量：SHRINK_TO_ABNORMAL触发
4. 放量异动：ABNORMAL_VOL在近5日内至少触发1次（资金进场迹象）
5. 股价>白线 OR 掉进碗里（白线以下黄线以上+B1信号）
6. N_STRUCT=0（排除已涨过的N型结构）
7. 图形要求：近10日振幅<15%（排除剧烈波动股）

B2确认条件（加速确认）:
1. B1信号出现后5日内出现
2. 当日为阳线，涨幅>3%
3. 成交量>前一日2倍（倍量柱）
4. 收盘价>白线（脱离成本区）
5. 暴力K触发则B2增强

B3确认条件（锁仓确认）:
1. B2信号出现后3日内出现
2. 当日为阳线，成交量<前一日0.7倍（缩量）
3. 收盘价>前一日收盘价
4. 最低价不跌破B2日收盘价
5. B3=主力锁仓完成→确定性最高

输出格式:
- generate_signals(data, symbol="", **params) -> pd.DataFrame
- columns: [date, signal, signal_type, confidence]
- signal_type: B1/B2/B3
- confidence: B1=0.6, B2=0.75, B3=0.9

参数可配置：j_threshold, shrink_ratio, vol_mult, b2_window, b3_window

注册到策略模块，写测试。
完成后 git commit。
```

### Agent 3-B: 砖型图三类型重写

**角色提示词**:
```
你是量化形态策略专家。将AlphaPulse-A的砖型图策略重写为三子类型版本。

工作目录：/Users/qiushixuan/cc/quantan trade

当前BRICK_ULTRA在alphapulse/strategies/brick_ultra_strategy.py。重写为alphapulse/strategies/brick_three_types.py。

砖型图计算：使用现有的brick_ultra.compute_brick_indicator()获取砖型值（VAR1A-VAR6A）。
红砖 = brick_indicator > 0, 绿砖 = brick_indicator == 0

类型1: N型起跳
- 前提：前5日出现过绿砖→红砖转换
- 红砖值 > 前绿砖绝对值 × 2/3
- 当日成交量 > 20日均量 × 1.5
- 收盘价在黄线附近（黄线±3%）
- 可选：与B2信号同时触发时增强
- signal_type = "BRICK_N_JUMP"

类型2: 上涨中继
- 前提：前5-10日有明显的红砖序列（上涨趋势）
- 前1-2日为绿砖（短暂回调）
- 当日为红砖（恢复上涨）
- 回调期间的最低价 > 最近放量阳线收盘价（回调不过深）
- 当日量柱放大（>前一日1.3倍）
- signal_type = "BRICK_CONTINUATION"

类型3: 横盘突破
- 前提：近3-5日（或更长）横盘，振幅<15%
- 当日红砖且收盘价突破横盘区间上沿
- 突破前高（横盘前的高点）
- 量能放大（>20日均量×1.3）
- 横盘区间内红砖数量>=绿砖数量（偏多）
- signal_type = "BRICK_BREAKOUT"

输出: generate_signals(data, symbol="", **params) -> pd.DataFrame
columns: [date, signal, brick_type, brick_value, confidence]

注册到策略模块，写测试。
完成后 git commit。
```

### Agent 3-C: 单针下三十重写

**角色提示词**:
```
你是量化策略专家。重写AlphaPulse-A的单针下三十策略。

工作目录：/Users/qiushixuan/cc/quantan trade

当前NEEDLE_ENHANCED在alphapulse/strategies/needle_enhanced.py（案例命中率仅4.4%）。
重写为alphapulse/strategies/needle_washout.py。

新逻辑（N型上涨中的主力洗盘补票）:

前提条件:
1. 标的在近60日内被B1_FORMULA选中过（前期完美图形验证）
2. 存在N型结构（N_STRUCT或N_PATTERN触发）
3. 当前价格在N型结构的T1→T2回调阶段

入场条件（同时满足）:
1. 长下影线：下影线长度 > 实体长度 × 3
2. J值超卖：KDJ_J_LOW触发（J<13）
3. 缩量：当日成交量 < 20日均量 × 0.7
4. 回调幅度：从N型T1高点回落30%-62%（Fibonacci黄金分割区间）
5. 价格位置：近60日价格在最低30%区间
6. 长期资金指标：ZHIXING_TREND开始走平或回升

持仓管理:
- 入场后脱离成本3%以上→可持有
- 止盈：按fly_away逐步减仓
- 止损：入场日最低价 - 3价位

输出: generate_signals(data, symbol="", all_stocks=None, **params) -> pd.DataFrame
（all_stocks用于检查该股是否曾在近60日内被B1选中）

注册策略，写测试。
完成后 git commit。
```

---

## 阶段四：风控与持仓管理重写

### Agent 4: 完整风控模块

**角色提示词**:
```
你是量化风控系统专家。重写AlphaPulse-A的风控与持仓管理模块。

工作目录：/Users/qiushixuan/cc/quantan trade

创建 alphapulse/risk/position_manager.py（新文件）:

功能：
1. 入场规则：
   - 单票仓位 = min(总资金×20%, 可用资金/持仓数上限)
   - 整手计算（100股为单位）
   - B3信号可加仓至25%

2. 动态止损：
   - 使用 dynamic_stop_loss.compute() 计算止损价
   - 跌破止损价 → 全仓卖出

3. 放飞减仓：
   - fly_away信号触发 → 按比例减仓
   - 砖型第4砖 → 减仓1/3

4. S1/DD清仓规则：
   - S1触发 → 清仓（假阴真阳时减仓50%观察）
   - DD触发 → 减仓50%
   - DD增强（连续2天）→ 全清

5. 趋势线持仓：
   - 跌破白线 → 观察1天 → 次日未站上 → 清仓
   - 跌破黄线 → 观察1天 → 次日未站上 → 清仓
   - 击穿对手盘（缩量跌破黄线）→ 等1天 → 收盘站回则持有/站不回则卖

6. 牵牛绳逻辑：
   - B1入场后 → 未出现S1 + 持续在白线以上 → 继续持有
   - 掉进碗里（白线以下黄线以上+B1信号）→ 可加仓

7. 5种出货方式检测：
   - 方式1: S1（已实现）
   - 方式2: 加速上涨后次高点放量长阴
   - 方式3: 新高后连续阶梯放量下跌
   - 方式4: 双头（第二次波段不破前高+顶部放量）
   - 方式5: 顶部阴量柱持续长于阳量柱（大盘股特征）

8. 主力资金判断：
   - 近60日跌破黄线次数>3次 → 主力控盘弱
   - 放量加速跌破黄线 → 主力不在
   - 持续考验黄线不破 → 主力仍在

输出类：
class PositionManager:
    def check_entry(self, symbol, signal, data, capital) -> dict  # {can_enter, shares, reason}
    def check_exit(self, symbol, position, data, signals) -> dict  # {should_exit, ratio, reason}
    def detect_distribution(self, data) -> list  # [{type, date, confidence}]

写测试到 tests/test_position_manager.py。
完成后 git commit。
```

---

## 阶段五：综合集成

### Agent 5: 更新选股流程 + Web UI + 回测引擎

**角色提示词**:
```
你是全栈量化系统集成专家。完成AlphaPulse-A的最终集成。

工作目录：/Users/qiushixuan/cc/quantan trade

任务：
1. 更新 friday_screener.py → 使用新的B1/B2/B3策略和三类型砖型图策略
2. 更新 run_backtest.py → 集成新的PositionManager
3. 更新 start_web.py → API增加新因子和新策略选项
4. 更新 frontend/index.html → 面板增加B2/B3/砖型子类型显示
5. 更新 factor_registry.py → 确保所有新因子都已注册
6. 更新 after_close.py → 修改报告格式包含新信号类型
7. 运行测试: python -m pytest tests/ -v
8. 运行端到端验证: python scripts/friday_screener.py (500只样本)

完成后 git commit -m "Complete trading system integration"
```

---

## 执行顺序

```
阶段一 (可并行, 3个Agent同时运行)
  Agent 1-A: 关键K + 暴力K + 倍量柱
  Agent 1-B: 筹码集中 + 对称结构 + 填坑出坑
  Agent 1-C: 长阴短柱 + 波段识别 + 关键K ABC
  ↓ 等待全部完成

阶段二 (可并行, 2个Agent同时运行)
  Agent 2-A: S1 + DD + 趋势线跌破
  Agent 2-B: 动态止损 + 放飞减仓
  ↓ 等待全部完成

阶段三 (可并行, 3个Agent同时运行)
  Agent 3-A: B1/B2/B3完整战法
  Agent 3-B: 砖型图三类型
  Agent 3-C: 单针下三十重写
  ↓ 等待全部完成

阶段四 (1个Agent)
  Agent 4: 完整风控模块
  ↓ 等待完成

阶段五 (1个Agent)
  Agent 5: 综合集成+测试
```

每个阶段的所有Agent完成后，检查结果、跑测试、git commit，然后启动下一阶段。

并行阶段：用 `Agent` tool 同时发送3个（或2个）agent调用，它们会在各自的worktree中独立工作。
```

## 验证清单

每阶段完成后检查：
- [ ] `python -m pytest tests/ -v` 全部通过
- [ ] `python -c "from alphapulse.factors.factor_registry import FACTOR_REGISTRY; print(len(FACTOR_REGISTRY))"` 因子数正确
- [ ] 新策略 `import` 无报错
- [ ] `git commit` 已提交
- [ ] 500只样本选股测试通过
