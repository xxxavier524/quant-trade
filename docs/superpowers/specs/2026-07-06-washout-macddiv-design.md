# 洗盘段量化模板 + MACD 面积背驰因子设计（路线图#6 & #7）

> 日期：2026-07-06 | 来源：Sequoia-X 涨停洗盘（05）、chan.py MACD背驰（03）
> #6：把"缩量阴/3/4阴量线"语义参数化为通用模板，统一服务 B3 锁仓与单针下三十
> #7：把 DD 顶背离从经验判断变为可回测参数（红柱面积背驰 divergence_rate）

## 一、#6 洗盘段量化模板（`alphapulse/factors/washout_template.py`）

### 母题（Sequoia 涨停洗盘三段式 ≈ 用户 B1→B2→B3 / 单针洗盘）
主力行为确认（爆量阳）→ 洗盘段（缩量、不破锚定位）→ 再确认（阳线）。

### 接口
```python
def washout_ok(df, anchor_idx, max_vol_ratio=0.5, anchor_price_col='open',
               min_days=1, max_days=10) -> bool:
    """锚定 anchor_idx 后的洗盘段是否有效：
    区间内每日 volume < anchor日volume × max_vol_ratio（缩量，对应'缩量阴/3/4阴量线'）
    且 每日 low > df[anchor_price_col][anchor_idx]（不破锚定位）。返回该段是否成立。"""
```
- 标量版按 spec 签名，供 B3/单针以特定锚点调用。
- 向量化因子 `compute(df, max_vol_ratio, surge_vol_mult, vol_ma, max_wait, **) -> Series[bool]`：
  自动锚定"最近的爆量阳"（vol>surge_vol_mult×MA(vol,vol_ma) 且 close>open），
  其后出现**有效洗盘段**（≥1 日缩量不破锚）后的**首个再确认阳线**日 = True。
  = Sequoia 三段式的程序化，全因果（只用 ≤t 数据，锚点在过去）。

### 注册
`WASHOUT_SEGMENT`（type=factor，bool）：surge→washout→reconfirm 完成日。

### 验收（roadmap #6）
`scripts/grid_washout.py`：max_vol_ratio ∈ {0.4,0.5,0.6,0.75} 网格，
收集 WASHOUT_SEGMENT 事件 → 5/10 日前向净胜率对比，选最优缩量上限。
（B3 序列样本过小，改用洗盘再确认信号的前向胜率做网格，样本充足、口径直接。）

## 二、#7 MACD 面积背驰（`alphapulse/factors/macd_divergence.py`）

### 原理（chan.py divergence_rate）
价格创新高，但该上涨段的 MACD 红柱面积 < 前一上涨段面积 × divergence_rate → 顶背离（DD）。

### 算法（红柱分段，因果）
1. MACD：复用 `macd_bull_dead.compute_macd`（12/26/9），hist=2·(dif−dea)，红柱=hist>0。
2. 把连续 hist>0 的日切成**红柱段**（maximal run）；每段记：
   - `area` = 段内 hist 之和（红柱面积）
   - `price_peak` = 段内 high 的最大值
3. 一段在 hist 由正转非正的**段末日**（死叉日）完结——此刻该段完全已知（因果）。
   与**上一完结红柱段**比较：
   `signal = (price_peak_now > price_peak_prev) AND (area_now / area_prev < divergence_rate)`
   → 段末日触发 DD 顶背离卖点。
4. 输出 `compute(df, divergence_rate=0.9, ...) -> Series[bool]`，True 在背驰死叉日。
   附 `compute_detail` 返回 area_now/area_prev/背驰比。

### 注册
`MACD_DIVERGENCE`（type=risk，bool，与 S1/DD 卖点同类）。

### 验收（roadmap #7）
`scripts/grid_macd_div.py`：divergence_rate ∈ {0.7,0.8,0.9,1.0} 网格。
顶背离是**卖点**——信号后前向收益应**低于基线**（价格走弱才是好卖点）。
收集 MACD_DIVERGENCE 事件 → 5/10 日前向收益胜率/均值，对比全样本基线，
grid 看哪个 divergence_rate 的"信号后走弱"最显著。诚实说明：这是"卖点后走弱"代理，
非完整持仓卖出模拟（后者需换卖出引擎，留作后续）。

## 三、测试

- `washout_ok`：构造 锚+缩量不破 / 破锚 / 放量 场景；min/max_days 边界。
- `WASHOUT_SEGMENT` compute：因果（截断不改前段）、爆量阳锚定正确、性质。
- `macd_divergence`：构造"价新高+红柱缩面积"必触发、"价新高+红柱放大"不触发、
  段末日对齐、因果（截断不改前段）；红柱面积与手算一致。

## 四、不做
- 不改 dd_sell_signal（简单DD保留；MACD背驰是其升维补充，二者并存）
- 不改 yin_volume_34（3/4阴量保留；washout_template 是其通用化，不替换）
- 不做完整卖出引擎替换回测（#7 用信号后前向走弱做代理验证；持仓级留后续）
- 生成/注册的因子默认不自动进选股，验证通过后由用户显式启用
