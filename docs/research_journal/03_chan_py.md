# 精读笔记 03：Vespa314/chan.py — 缠论形态学/动力学买卖点框架

> 研究日期：2026-06-11 | 研究目的：为 B1→B2→B3 战法状态机与砖型图N型识别寻找形态学引擎参考

## 一、项目卡片

| 项 | 内容 |
|---|---|
| 地址 | https://github.com/Vespa314/chan.py |
| Star | ~1.5k（缠论开源实现中代码质量最高的一个） |
| 语言 | Python，纯面向对象，增量计算架构 |
| 最近更新 | 持续维护中 |
| 定位 | 开放式缠论计算框架：K线合并→分型→笔→线段→中枢→买卖点，外加特征引擎+ML训练+交易引擎 |
| 选择理由 | 它解决的问题（"结构化形态 + 状态机买卖点 + 机器学习过滤"）与用户的 B1/B2/B3 + 单针下三十 + 砖型图体系是**同构问题**，工程范式可整体借鉴 |

## 二、核心架构与关键模块精读

### 2.1 分层结构计算管线

```
KLine/KLine_Unit.py   原始K线
  → KLine/KLine.py    包含关系合并后的"缠论K线"
  → Bi/Bi.py + BiList.py        笔（分型确认，bi_strict严格模式）
  → Seg/SegListChan.py          线段（特征序列法；另有SegListDef定义法、SegListDYH都业华1+1法，三种算法可插拔）
  → ZS/ZS.py + ZSList.py        中枢（zs_algo控制是否跨线段）
  → BuySellPoint/BS_Point.py    形态学买卖点
```

每一层都是"下层列表变化→增量更新上层"的事件驱动，`trigger_step=True` 时可 `step_load()` 逐根K线推进——这就是**回放式信号生成**，天然无未来函数。

### 2.2 买卖点系统（BuySellPoint/）

类型标识体系（`BS_Point.type`）：
- `1` / `1p`：一类买卖点（趋势背驰反转；1p=盘整背驰）
- `2` / `2s`：二类买卖点（一买后回踩不破前低；2s=类二买）
- `3a` / `3b`：三类买卖点（中枢突破后回踩不回中枢）

关键配置（`BSPointConfig` / `CChanConfig`）：
- `divergence_rate=0.9`：背驰判定 = 末段MACD面积/前段MACD面积 < 0.9
- `max_bs2_rate=0.618`：二买回撤不得超过前笔的0.618
- `min_zs_cnt=1`：一买前至少要有几个中枢

**精读结论**：买卖点不是孤立信号，而是带前置依赖的序列——三买依赖中枢，二买依赖一买。框架用"父子引用"（`bsp.bi`、`bsp.relate_bsp1`）把序列关系结构化了。

### 2.3 特征引擎 + 模型层（ChanModel/ 与 ModelStrategy/）

- `ChanModel/Features.py`：400+特征计算（买卖点处的笔斜率、中枢宽度、MACD背驰度、K线距离等），`FeaturesDesc.py` 做特征元数据注册
- `ModelStrategy/models/LGBMModelGenerator.py`：**对每个历史买卖点打标签（之后是否真涨）→训练LGBM→实盘只接受模型概率高的买卖点**
- `ModelStrategy/backtest.py` 特征生成与回测一体，`para_automl.py` 超参搜索

这套"**规则产生候选点 → ML做二次过滤**"的两段式架构，与我们"B1信号 + LightGBM胜率模型"完全同构，但它的特征是在**信号点上下文**提取的（不是全市场截面），值得抄。

### 2.4 交易闭环（Trade/Script/）

`SignalMonitor.py`（信号计算入库）→ `MakeOpenTrade.py`（开仓）→ `RealTimeTracker.py`（持仓追踪止盈止损）→ 数据库（`MysqlDB/SqliteDB`）。与我们的 daily_screener → evening_review → risk_monitor 三件套对应，但它多了**信号→订单→持仓的状态流转表**。

## 三、亮点技术拆解

### 亮点1：K线包含关系合并（形态识别的预处理基石）

原始K线先做缠论合并：若后一根K线高低点被前一根包含，按当前方向（向上取高高、向下取低低）合并成一根。**作用**：消除噪音K线，让"单针下三十"的长下影、N型结构的转折点在合并后的K线序列上更稳定。我们目前的 N_STRUCT 因子直接在原始K线上找 swing point，遇横盘毛刺容易误判——这是可直接改进的点。

### 亮点2：MACD面积背驰量化（divergence_rate）

把"背驰"从玄学变成可调参数：前后两段走势的 MACD 柱面积比 < 0.9 即背驰。用户的 DD 卖点（顶背离）可以用完全相同的方法量化：股价新高段的MACD红柱面积 / 前高段红柱面积 < 阈值 → DD信号。**参数可网格搜索**（我们已有 grid search 基建）。

### 亮点3：买卖点序列状态机 + relate_bsp 引用链

二买持有一买的引用、三买持有中枢引用。映射到用户战法：B2 应持有对 B1 的引用（B1价格、B1日期、B1时J值），B3 持有 B2 引用。这样卖点 S1 触发时能回溯整条链做归因分析——我们信号追踪闭环目前只记录孤立信号，缺这个链路。

### 亮点4：逐K回放接口（trigger_step / step_load）

所有结构增量更新，保证"任意时刻的计算结果只依赖该时刻之前的数据"。验证胜率时不会用未来分型确认污染历史信号。

## 四、与用户选股逻辑的契合点

| 用户逻辑 | chan.py对应物 | 契合度 |
|---|---|---|
| B1→B2→B3 序列战法 | 一买→二买→三买的依赖式状态机 | ★★★★★（同构） |
| 砖型图N型起跳/中继 | 笔与线段结构（N型≈三笔结构：上-回调-上） | ★★★★ |
| 单针下三十洗盘 | K线合并后的底分型+长下影识别更稳定 | ★★★★ |
| DD/死叉卖点 | MACD面积背驰 divergence_rate | ★★★★★ |
| LightGBM胜率模型 | 信号点上下文特征 + LGBM二次过滤（Features.py 400+特征） | ★★★★★ |
| 知行白黄线 | 无对应（均线体系它不管） | ☆ |

## 五、取精华建议

### 建议1：信号链路引用——B1B2B3状态机加 relate 链（最优先）

改造 `alphapulse/strategies/b1.py` 输出结构：

```python
@dataclass
class SignalNode:
    symbol: str; date: str; stype: str          # 'B1'|'B2'|'B3'|'S1'...
    factor_snapshot: dict                        # 触发时各因子值
    relate: "SignalNode|None" = None             # B2->B1, B3->B2, S1->持仓B链
    seq_id: str = ""                             # 同一轮战法序列共享id

# evening_review 按 seq_id 聚合统计：B1后接出B2的比率、完整B1B2B3序列胜率 vs 孤立B1胜率
```

工作量：**1~2天**（含信号追踪表加 seq_id/relate 字段与复盘报表改造）。

### 建议2：实现 `alphapulse/factors/macd_divergence.py`（DD卖点量化）

```python
def compute(df) -> pd.Series:
    # 1. 找最近两个price swing high（可用合并K线，见建议3）
    # 2. area_now = 两高点间最后一段MACD红柱面积; area_prev = 前一段
    # 3. signal = (high_now > high_prev) & (area_now / area_prev < divergence_rate)
```

`divergence_rate` 进网格搜索（0.7/0.8/0.9/1.0）。工作量：**1天**，用现有胜率验证器直接回测。

### 建议3：K线包含关系合并预处理 `alphapulse/utils/kline_merge.py`

`merge_klines(df) -> df_merged`（向量化：方向用 cummax/cummin 辅助，合并段用 groupby 聚合）。N_STRUCT、单针下三十、砖型图三个模块统一改在合并后K线上跑，回测对比误报率。工作量：**1~2天**（向量化实现有一定难度，注意 golden test）。

### 建议4：信号点上下文特征抽取器（喂LGBM）

仿 `Features.py`：在每个 B1 信号点提取"信号上下文特征"——距前低天数、本轮缩量比、J值、白黄线距离百分比、近5日红绿量比、振幅压缩度等 30~50 维，替代当前全截面特征训练胜率模型。**这是提升LGBM区分度最直接的一招**。工作量：**2天**。

## 六、不取的部分及原因

- **完整缠论笔/线段/中枢递归体系**：概念负担重，与用户已验证的战法体系并行会引入两套形态学话语，维护成本高；只取其工程范式
- **富途交易引擎（FutuTradeEngine）**：我们目标是QMT，接口不通用
- **区间套多级别联立**：用户体系基于日线+周线确认，足够；分钟级数据我们没有稳定源
- **腾讯COS/minio绘图上传**：与Streamlit展示重复
