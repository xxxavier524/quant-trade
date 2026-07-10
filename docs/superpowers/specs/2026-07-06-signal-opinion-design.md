# 统一信号协议 + 置信度加权聚合（路线图#8）

> 日期：2026-07-06 | 来源：ai-hedge-fund 统一信号协议（07）
> 目标：规则/LGBM/LLM/UMP 归一为 SignalOpinion，死区阈值抑制弱信号，聚合分数排序单一化

## 1. 现状盘点（避免重复建设）

系统**已有**大量统一：
- `ranking/composite.py`+`stock_ranker.py`：规则子分数 + LGBM `ml_score` 已用 IC 调优权重
  合成 0-100（winsorize→zscore→加权→minmax），ml_score 是加权分量之一。
- `agent_team/contract.StockOpinion`+`fusion.bayes_fuse`：LLM 仲裁与量化分的贝叶斯融合（Top-N 叠加层）。
- UMP 裁判：时间外推验证**被否决**（08_integration_log #4，止损修复已吸收其攻击面），不纳入。

因此 #8 的"规则+LGBM 归一"**已实现**；LLM 是 Top-N 叠加、UMP 已弃。重复造聚合器 =
项目"明确不做清单"警告的基础设施重复建设。**#8 的增量价值 = 显式协议 + 唯一缺失件"死区阈值"**。

## 2. 增量交付

### 2.1 `ranking/signal_opinion.py`（显式协议，薄层）
```python
@dataclass
class SignalOpinion:
    source: str           # 'rule' / 'ml' / 'llm' / 'ump'
    signed: float         # [-1,1] 方向×强度
    confidence: float     # [0,1]

def aggregate(opinions, dead_zone=0.0) -> float:
    """置信度加权聚合，|signed|<dead_zone 的观点视为噪声不计；返回 [-1,1]。
    死区：抑制近中性弱信号，只让明确观点参与排序。"""
```
`from_rule_ml(rule_z, ml_prob)`：把排序层两大来源映射为 opinions（rule 的截面 zscore、
ml 概率中心化 2·(p−0.5)）。LLM/UMP 作可选 opinion 传入（保留接口，当前不默认启用）。

### 2.2 AB 验证（roadmap #8：聚合分 vs 原0-100分 Top-N 对比）
`scripts/ab_signal_opinion.py`：复用 `ic_weight_tuning.build_panel`（截面 sub_scores+ml_score+fwd5），
逐日截面：
- 基线 = 现行线性加权 composite（`ic_weight_tuning.composite_eval` 口径）Top50 fwd5 胜率
- 对照 = SignalOpinion 聚合（死区 ∈ {0,0.25,0.5}）Top50 fwd5 胜率
诚实判定：死区聚合**是否超过**已 IC 调优的线性 composite。若不超（很可能，线性已近优），
如实报告"现行 0-100 已近最优、死区聚合无额外增益"——这本身是有价值的负结论
（佐证不必重构排序层）；若某死区超过，给出推荐值。

## 3. 测试
- `aggregate`：全一致高置信→接近 +1；方向分歧→互相抵消；死区把弱信号清零；空输入=0。
- `from_rule_ml`：ml 概率 0.5→signed 0；rule 高 zscore→signed 正。
- 边界：单一 opinion、全在死区内→聚合 0。

## 4. 不做
- 不重写 composite/stock_ranker（已 IC 调优，是生产排序主干）
- 不纳入 UMP（已否决）；LLM 仅保留接口不默认启用（Top-N 叠加已由 agent_team 承担）
- 聚合器默认不替换生产排序；仅作可选口径 + AB 研究，验证通过再由用户决定
