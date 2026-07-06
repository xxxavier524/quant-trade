# 杂项增强包：CSRankNorm标签 + Hurst战法分流 + 增量/推送评估（路线图#12）

> 日期：2026-07-06 | 来源：qlib CSRankNorm / ai-hedge-fund Hurst / Sequoia 增量
> 三个独立小件；按可测性与增量价值排序交付。

## 一、Hurst 战法分流（主交付，`alphapulse/factors/hurst.py`）

**命题**（07笔记）：Hurst 指数判个股"趋势性 vs 均值回归性"——B1（回归逻辑）适合**低 Hurst**、
砖型突破（趋势逻辑）适合**高 Hurst**。按 Hurst 给战法分流。

**估计**（结构函数法，滚动因果）：窗口 W=63 内，对滞后 τ∈{1..k} 求 log 收益 τ 步差的
标准差 σ(τ)，Hurst H = log σ(τ) 对 log τ 的回归斜率。H>0.5=趋势持续，H<0.5=均值回归。
`compute(df, window=63, max_lag=20) -> Series[float]`（每日滚动 H，因果）。

**分流 AB**（roadmap #12：分流前后各战法胜率）：`scripts/ab_hurst_routing.py`
- B1_FORMULA 事件 × 事件日 Hurst → 低 Hurst（<0.5）vs 高 Hurst 子集 5/10 日净胜率
- BRICK_ULTRA/趋势事件 × Hurst → 高 vs 低
- 验证"B1 在低 Hurst 更优、趋势在高 Hurst 更优"，给分流阈值建议。诚实报告。

## 二、CSRankNorm 标签（`alphapulse/ml/label_transform.py`）

**动机**（qlib）：LGBM 二分类标签 label=(fwd>0) 受**市场 beta 污染**——大盘下跌日多数股 fwd<0，
标签与个股 alpha 无关。CSRankNorm = 按日截面对 fwd 排名归一，去 beta（只留相对强弱）。

**接口**：`csrank_norm(df, value_col, date_col, method='binary') -> Series`
- 'binary'：截面 rank > 中位 → 1（去 beta 的二分类标签，正样本率恒≈50%）
- 'zscore'：截面 rank 归一到 z（回归/排序模型用）

**验收**：去 beta 性质**可测**——下跌市日：raw 标签正样本率随大盘塌陷（beta 污染），
CSRankNorm 正样本率稳定≈50%。用真实面板（ic_weight_tuning.build_panel 的 fwd5）演示。
完整 LGBM 排序模型重训 AUC 对比需改训练目标为 rank objective，属较大改动，本期交付
标签工具 + 去 beta 性质证明，推荐下轮 ranking 模型迭代采用。

## 三、增量数据 / 飞书推送（评估，不重建）

盘点：`daily_update.py`/`recover_stale.py`/`_smart_downloader.py`/`fetch_*.py` 已实现增量抓取
与断点修复；`notify/feishu_bot.py` 已实现推送，settings 从 .env 读 FEISHU_WEBHOOK_URL。
**结论**：增量数据基建已就绪；飞书推送**代码就绪但阻塞于用户未配置 webhook**（记忆已记）。
本项不重建，记录现状；用户配置 webhook 后推送即生效。

## 四、测试
- `hurst.compute`：合成趋势序列 H>0.5、均值回归(OU/随机反转)序列 H<0.5、随机游走 H≈0.5；因果。
- `csrank_norm`：构造下跌市日 → raw 正样本率低而 CSRankNorm≈50%；截面 rank 正确；单调。

## 五、不做
- 不改 pattern_model 生产标签（label_transform 作可选工具，验证后由用户决定是否重训）
- 不做 ADX 完整置信度接入（07 提及，留后续；Hurst 分流已覆盖趋势/回归判定核心）
- 不动飞书/数据抓取代码（已就绪，push 阻塞于用户配置）
