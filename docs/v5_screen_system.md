# v5 纯选股成功率系统 — 第一性原理规格（2026-08-02）

## 0. 定位

本系统只回答一个问题：**"这个选股策略选出来的票，未来到底涨不涨？"**
不做仓位、不做滑点、不做止损、不做资金曲线——那些是交易层，已从代码库移除。
选股的价值 = **比"随机选一只"更高的未来上涨命中率**。

## 1. 唯一主口径：机会命中

- 信号日 T（收盘确认，信号当日不可成交）
- 观察窗口：T 之后 H 个交易日（默认 H=5）的收盘价
- **成功**：`close[T+1..T+H]` 中任一 ≥ `close[T] × (1 + P)`（默认 P=5%）
  —— "选出来之后 H 天内给过 +P% 的收盘可成交卖出机会"
- 这是纯涨跌判断：不模拟"买入→持有→卖出"，不扣费，不含止损。
  它度量的是**选股命中率**，不是已实现收益。

### 对照口径（报告用，不参与优化）

| 口径 | 定义 | 用途 |
|---|---|---|
| end_ret | T+H 收盘相对 T 收盘（%） | 持有到期末的平均/中位收益 |
| max_ret | 未来 H 日收盘最大涨幅（%） | 机会上限 |
| min_ret | 未来 H 日收盘最大跌幅（%） | 风险暴露 |
| hit_ratio_end | 期末收益 > 0 的占比（%） | 胜率参考 |

### 为什么不是"曾触及最高价"或"已实现收益"

- "最高价触及 +P%"是信息上限，实盘卖不到，禁止当主口径；
- "已实现收益（止损+扣费退出）"是交易体验口径，属于实盘追踪（signal_tracker
  的 realized），与选股命中率是两回事——前者保留在追踪报告中，后者是本系统主口径。

## 2. 基线：随机选一只

每个信号日 T，计算**全体有数据的股票**在同窗口的命中率（与主口径完全同定义），
得到当日基线。策略的**超额命中（lift）= 策略成功率 − 基线**。

第一性原理推论：
- lift ≤ 0 的策略没有选股价值（不如闭眼随机）；
- **优化系统默认拒绝写入 lift < 3pp 的参数**（`--min-lift` 可调）；
- 大盘牛市里"闭眼也涨"，基线自动吸收行情，防止把贝塔当 alpha。

## 3. 因果铁律（防止自我欺骗）

1. **信号因子禁止未来函数**：枢轴/形态按确认时点公布
   （`n_struct.compute_causal`；`compute()` 已废弃）。
2. **截断不变性门禁**：`screen_bt` 对每个策略抽样执行——把数据截断到 T，
   T 日是否出信号不得因追加未来数据而改变；抽查发现泄漏直接标 ❌。
3. **右删失处理**：窗口末尾不足 H 日的数据丢弃（防止"只有涨了才有后续数据"偏差）。
4. **幸存者偏差**：`--include-delisted` 并入退市股目录。

## 4. 样本门槛

- 策略级结论：n ≥ 100 信号（`MIN_SIGNALS`），否则"样本不足，未出结论"；
- 年度表：单年 n ≥ 20 才计入；
- 优化单窗：n ≥ 8 信号才计入该窗（避免小样本噪声）。
- 成功率一律附带 **Wilson 95% 下界**（小样本不确定性）。

## 5. 优化：walk-forward + 稳健分 + 基线约束

- 训练窗：2020 起锚定扩张；验证窗：6 个月滚动（复用 `walk_forward.make_windows`）
- 稳健分 = 0.5 × 验证窗中位成功率 + 0.5 × 最差窗成功率
  （惩罚方差，不选单窗冠军；单窗样本内选参已废弃——出过 hit_rate=1.0 的过拟合）
- 链式流程回测：第 k 窗只用前 k−1 窗选出的参数评估，得到选参流程的无偏期望
- 覆盖门槛：有效窗 < 5 的组合出局
- 写入门槛：新参数 robust 必须超过在任 + 噪声容忍（默认 1pp），
  且 lift ≥ `--min-lift`（默认 3pp）；`--force-write` 仅用于明确推翻结论
- 产出：`reports/screen_optimize_<策略>.md` + `config/best_params.json`
  （带 `_source.method="screen_walk_forward"` 与基线/超额标注）

## 6. 系统组成

| 组件 | 路径 | 职责 |
|---|---|---|
| 评估器 | `alphapulse/screening/evaluator.py` | 机会命中/基线/年度/曲线/Wilson |
| 策略注册 | `alphapulse/screening/strategies.py` | 10 个选股策略统一入口 |
| 成功率回测 CLI | `scripts/screen_bt.py` | 全策略成功率报告 + 因果门禁 |
| 参数优化 CLI | `scripts/screen_optimize.py` | walk-forward 优化写 best_params |
| ML 标签 | `alphapulse/ml/pattern_model.py` | 训练标签 = 选股机会命中（同口径） |

覆盖策略：`B1_FORMULA, B1_B2_B3, BRICK_THREE_TYPES, NEEDLE_WASHOUT,
BRICK_ULTRA, NEEDLE, B1_ENHANCED, ZG_B1_BRICK, VOLUME_B1, ZHIXING_ULTRA`。

## 7. 使用

```bash
# 全策略成功率报告（默认 300 只样本，5 日 +5% 机会命中）
python scripts/screen_bt.py --strategies ALL --sample 300

# 单策略深度报告
python scripts/screen_bt.py --strategies B1_B2_B3 --sample 800 \
    --include-delisted --out reports/screen_bt_B1_B2_B3.md

# 参数优化（写入 best_params.json 前自动检查基线超额）
python scripts/screen_optimize.py --strategy B1_B2_B3 --sample 800
python scripts/screen_optimize.py --strategy NEEDLE_WASHOUT --min-lift 5.0
```

## 8. 与实盘追踪的关系

- 本系统 = 选股命中率（信号质量的离线评估/优化）
- `signal_tracker.realized` = 实盘追踪（选出来后的真实持有体验，扣费固定退出）
- 两者互补：命中率高但 realized 低 → 信号有效但退出执行差；
  命中率低 → 信号本身无效。报告中同时呈现，但主数字互不混淆。
