# K线包含关系合并预处理（路线图#10）

> 日期：2026-07-06 | 来源：chan.py K线合并（03，形态识别的预处理基石）
> 目标：缠论包含合并去毛刺，让长下影/N型转折点在合并后序列上更稳定；AB 对比误报率/胜率

## 1. 算法（缠论包含合并，逐根顺序，因果）

原始K线先做合并：若相邻两根有**包含关系**（一根的 [high,low] 完全含另一根），
按**当前方向**合并成一根：
- 向上（direction=up）：new_high=max(两high)，new_low=max(两low)（取"高高"）
- 向下（direction=down）：new_high=min(两high)，new_low=min(两low)（取"低低"）

方向更新：无包含时，若 cur.high>prev.high → up，否则 down。首方向由前两根非包含K线定。
合并后每根"缠论K线"记 [orig_start, orig_end]（跨越的原始下标）与 date=orig_end 日期。

**因果**：单次前向扫描，第 t 根只依赖 ≤t 的原始K线；合并结果随新数据只增不改历史
（历史合并段一旦被非包含K线终结即固定）。这是形态因子无未来泄漏的前提。

## 2. 接口（`alphapulse/utils/kline_merge.py`）

```python
def merge_klines(df) -> (merged_df, orig_to_merged):
    """df(OHLCV+date) → 合并后K线DataFrame + 原始行→合并行的映射数组(len=len(df))。
    merged_df 列: open/high/low/close/volume/date/orig_start/orig_end。"""

def map_merged_signal_to_original(merged_sig, orig_to_merged, n_orig) -> np.ndarray:
    """合并K线上的bool信号 → 原始日历(信号落在合并段的 orig_end 日=可交易日，因果)。"""
```

不改 N_STRUCT/单针/砖型默认路径（避免动 golden test）；提供 opt-in 让形态在合并K线上跑。

## 3. AB 验证（roadmap #10：合并前后误报率/胜率）

`scripts/ab_kline_merge.py`：用自包含的**长下影探底信号**（单针下三十的核心：
下影 > shadow_mult × 实体 且 处于近 N 日低位）——分别在**原始K线**与**合并K线**上计算，
映射回原始日历，对比：
- 信号数（合并后应更少 = 去毛刺）
- 5/10 日前向净胜率（合并后误报减少 → 胜率应持平或提升）

诚实判定（沿用本轮标准）：若合并后信号数降但胜率未升，说明去毛刺代价是漏真信号，如实报告。

## 4. 测试（`tests/test_kline_merge.py`）

- 无包含序列：merge 应原样（行数不变、逐根对齐）
- 构造包含：向上取高高、向下取低低（手算对拍）
- 合并后行数 ≤ 原始；orig_to_merged 单调非降、覆盖全部原始行
- 因果性：截断尾部不改前段合并结果与映射
- map 回原始：信号落在 orig_end 日，长度 = 原始

## 5. 不做
- 不做完整分型/笔/线段/中枢（缠论全体系，明确不做清单已排除）——只做合并这一层
- 不改三个形态因子的默认实现（opt-in；避免 golden test 回归）
- 生成的合并K线不进入选股主干，仅供形态因子可选调用与 AB 研究
