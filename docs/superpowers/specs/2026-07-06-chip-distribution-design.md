# 筹码分布因子设计（路线图#5）

> 日期：2026-07-06 | 来源：InStock CYQ（docs/research_journal/04_instock.md §2.4/亮点1）
> 目标：给"底部挖掘"体系补上**持仓成本维度**——B1买点 + 低位单峰密集 + 获利盘<15% = 真底确认

## 1. 现状与缺口

现有 `chip_concentration.py`（CHIP_CONCENTRATION）只是**振幅代理**（20天振幅+收敛+换手下降），
不是真实成本分布。本因子实现 InStock/通达信的 **CYQ 成本分布重建**：从日线 OHLC+成交量+换手率
逐日演化每个价位的持仓筹码，输出：
- **profit_ratio 获利盘比例**：当前价以下的筹码占比（越低=套牢盘越多=底部吸筹未完成/刚完成）
- **conc90 筹码集中度**：中央 90% 筹码的价格带宽 / 现价（越低=单峰越密集）
- **avg_cost 平均成本**：筹码加权均价

## 2. CYQ 算法

**逐日递归模型**（三角分布沉积 + 换手衰减）：
```
chips_t[price] = chips_{t-1}[price] * (1 - turnover_t) + deposit_t[price] * turnover_t
```
- `deposit_t`：当日成交量按**三角分布**摊到 [low_t, high_t]，峰在均价 avg_t=(H+L+C)/3，归一到 Σ=1
- `turnover_t`：当日换手率（turnover 列 /100），clip 到 [1e-4, 0.5] 防脏数据
- 直觉：每日 turnover 比例的筹码换手到当日成交价，其余 (1-turnover) 旧筹码保留

**价格网格**：每股取全历史 [min(low), max(high)]，B=200 个等距桶（bucket 中心）。

**因果性**：`chips_t` 只由 s≤t 的数据构成，天生无未来泄漏（与全项目一致）。

### 2.1 向量化（exp-cumsum，快路径）

递归展开：
```
chips_t[b] = exp(decaylog_t) · Σ_{s≤t} deposit_s[b] · turnover_s · exp(-decaylog_s)
其中 decaylog_t = Σ_{u≤t} log(1 - turnover_u)   （累积，≤0 递减）
```
令 `A[s,b] = deposit_s[b]·turnover_s·exp(decaylog_last - decaylog_s)`（减 decaylog_last 使
指数∈(0,1] 防溢出；全局常数在按日归一时抵消），则 `Ccum = cumsum(A, axis=0)`（T×B）。
公共因子 exp(decaylog_t) 在按日归一时抵消，故只需 Ccum：
- `profit_ratio_t = Σ_{b:grid_b<close_t} Ccum[t,b] / Σ_b Ccum[t,b]`
- `avg_cost_t = Σ_b grid_b·Ccum[t,b] / Σ_b Ccum[t,b]`
- `conc90_t = (grid[idx95_t] - grid[idx05_t]) / close_t`，idx 由行内归一 CDF 的
  `argmax(cdf≥0.05)` / `argmax(cdf≥0.95)` 得到（向量化）

复杂度 O(T·B)，纯 numpy，~1ms/股。

### 2.2 逐日参考实现（测试基准）

`_compute_chips_sequential(df)`：直接按递归逐日迭代（O(T) python），显然正确、数值稳定，
作为向量化版的**对拍金标准**（测试断言两者 allclose）。

## 3. 因子

在 `factor_registry` 注册两个（+ 指标输出）：
- **CHIP_PROFIT_LOW**（selection/bool）：`profit_ratio < profit_threshold`（默认 0.15）
- **CHIP_SINGLE_PEAK**（factor/bool）：`conc90 < conc_threshold`（默认 0.12）
- **CHIP_DISTRIBUTION**（indicator）：compute_chips 返回三列 DataFrame（供评分/研判取数）

`compute(data, **params) -> pd.Series` 统一接口；参数 profit_threshold/conc_threshold/n_buckets/max_turnover。

## 4. 验收

1. **向量化 == 逐日参考**：合成数据上 profit_ratio/avg_cost/conc90 逐点 allclose（金标准对拍）
2. **截断因果性**：截尾数据前段每点不变（无未来泄漏），固化为回归测试
3. **性质**：profit_ratio∈[0,1]；连续上涨后 profit_ratio→高；单峰横盘 conc90 低于剧烈波动段
4. **AB 验证**（真实数据，roadmap #5 口径）：`scripts/ab_test_chip.py` 收集 B1_FORMULA 事件，
   查事件日 profit_ratio/conc90，按阈值网格对比 5/10 日**净胜率**——B1 vs B1+筹码过滤，
   看"低位单峰+低获利盘"是否提纯 B1。诚实判定（沿用 #3：不夸大噪声级差异）。
   注：无法访问通达信筹码图对拍，以逐日参考对拍 + 性质检验替代该项。

## 5. 边界与不做

- 不引入 tick/逐笔数据（仅日线重建，与体系数据面一致）
- 不改现有 CHIP_CONCENTRATION（保留，二者互补：一个振幅代理、一个真实成本分布）
- 价格网格全历史固定；除权跳空由数据层前复权保证（沿用现有 data/day 前复权 CSV）
- 生成的因子默认注册即用于研究，进每日选股需 AB 通过后由用户在配置启用
