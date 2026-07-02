# Agent Team P0 MVP — 设计规格

> 来源：`docs/research_journal/09_multiagent_research_2026-06-17.md` §4。用户 2026-06-21 批准。
> 目标：把已有确定性模块串成"单股多角色投研结论"，纯量化、无 LLM、零新依赖。

## 1. 目标 / 非目标

**目标（P0）**
- 新建 `alphapulse/agent_team/`，5 个纯函数角色 + 规则聚合。
- 喂入标的列表（`daily_screener` Top-N 或显式 `--symbols`）→ 每股产出多角色裁决 + evidence + 5 档评级。
- CLI `scripts/run_agent_team.py` → 写 `reports/agent_team_YYYY-MM-DD.md` + print 摘要。
- 完整单测 `tests/test_agent_team.py`。

**非目标（留给阶段二/三）**
- DeepSeek 多空辩论、贝叶斯置信度融合（阶段二）。
- GUI「投资判断」Tab 接入（CLI 核心验证后的快速跟进，非 P0 阻塞）。
- 决策日志闭环、上下文压缩、RD-Agent 因子工厂（阶段三）。

## 2. 输出契约

新建 `alphapulse/agent_team/contract.py`（**不复用** `pipeline/agents.py:AgentResult`，那是 R&D 流水线用的）：

```python
@dataclass
class StockOpinion:
    agent: str                 # 角色名
    signal: str                # "bullish" | "bearish" | "neutral"
    confidence: float          # 0-100
    evidence: dict             # 结构化依据字段
    reasoning: str             # 一句话人话
    def signed(self) -> float  # bullish:+conf / bearish:-conf / neutral:0

@dataclass
class TeamVerdict:
    symbol: str
    name: str
    score: float               # 0-100 团队综合分
    rating: str                # Buy/增持/持有/减持/Sell
    opinions: list[StockOpinion]
    reasoning: str             # 汇总人话
    ok: bool = True            # 数据健康则 True
    def to_row(self) -> dict   # 供 Markdown/CSV 落盘
```

## 3. 五个角色（`alphapulse/agent_team/agents.py`，全部纯函数）

统一签名 `*_agent(...) -> StockOpinion`。核实过的真实 API：

| 角色 | 调用（已核实） | signal 判据 | confidence |
|---|---|---|---|
| `data_agent(df)` | 输入已由 `replay_screen.load_stock` 载入的 df | 行数≥120 且无 NaN 崩坏 → neutral(ok)；否则 bearish(不健康) | 100 健康 / 0 不健康 |
| `factor_agent(df)` | `sub_scores.compute_sub_scores`(11子分) + `b1_formula/volume_b1/zhixing_trend/needle.compute`(严格信号) | 底部因子强(j_low/vol_shrink/yangyin 高)→bullish | 子分加权 0-100（复用 composite 权重哲学） |
| `pattern_agent(df)` | `playbook_engine.simulate_b1b2b3`(取最后一笔/最近信号→当前 B1/B2/B3 态) + `pattern_model.predict_ml_score`(GBDT 0-1) | 处于 B1/B2 买点态 & GBDT>0.5 →bullish | GBDT 概率×100（无模型时退回因子态定性 60/40） |
| `sector_agent(symbol, ctx)` | `ctx.sector_map`/`ctx.concept_map`/`ctx.sector_scores` + `ctx.macro_level` | 强板块(score≥60)+热概念 & 大盘非空头→bullish；弱板块→bearish | 板块分与大盘档映射 0-100 |
| `portfolio_agent(opinions)` | 规则加权聚合 | 由 team_score 定 | team_score |

**共享上下文** `TeamContext`（`context.py`）批量只建一次：
`macro_level`(compute_market_score)、`sector_scores`(rank_sectors)、`sector_map`(symbol_sector_map)、`concept_map`(symbol_concept_map)。

## 4. 聚合规则（P0 确定性）

`portfolio_agent` 计算 `team_score`：
- 权重：factor 0.40、pattern 0.35、sector 0.25（data 为硬门：不健康→score=NA、rating=观望）。
- 每角色贡献 = `signed()/100 * 权重`（bullish 正、bearish 负、neutral 0）→ 加权和 ∈ [-1,1]。
- `team_score = round(50 + 50 * 加权和, 1)` 映射到 0-100。
- 评级阈值：`≥75 Buy`、`60–75 增持`、`45–60 持有`、`30–45 减持`、`<30 Sell`。
- `reasoning` = 各角色 reasoning 拼接（"因子:… | 形态:… | 板块:…"）。
- 单调性保证（可测）：任一角色 confidence 升高（方向不变）→ team_score 不降。

## 5. 编排与 CLI

- `core.py`：`analyze_stock(df, symbol, name, ctx) -> TeamVerdict`；`analyze_batch(items, ctx) -> list[TeamVerdict]`（items=(symbol,name,df)）。
- `scripts/run_agent_team.py`：
  - `--top N`（默认 10）：读最新 `reports/screen_*.csv` 取 Top-N 代码；或 `--symbols 000001 600519` 显式；`--date` 回放。
  - 载入各股 df（`replay_screen.load_stock`，DATA_DIR）；建 `TeamContext` 一次；`analyze_batch`。
  - 写 `reports/agent_team_YYYY-MM-DD.md`：每股裁决表(角色/信号/置信/依据) + 最终评级 + reasoning；print Top 摘要。
  - DATA_DIR 不存在（外接盘未挂载）时给出明确提示并退出。

## 6. 测试（TDD，`tests/test_agent_team.py`）

- 合成 df 夹具（沿用 `test_factors.py` 的 `np.random.seed(42)` 造 OHLCV）：造"强底部"与"破位"两种，断言 factor/pattern/sector agent 的 signal 方向与 confidence 区间。
- `portfolio_agent` 聚合：构造 opinion 列表断言 rating 阈值边界 + 单调性。
- `data_agent`：残缺 df → bearish/不健康。
- 集成冒烟：用本地真实 `data/day/000001.csv`、`600519.csv` 跑 `analyze_stock`，断言返回 TeamVerdict 结构完整、rating 合法、不抛异常。
- 目标：全部通过且不破坏现有 190 测试。

## 7. 文件布局

```
alphapulse/agent_team/
├── __init__.py
├── contract.py     # StockOpinion / TeamVerdict
├── context.py      # TeamContext + build_context()
├── agents.py       # data/factor/pattern/sector agents
├── portfolio.py    # portfolio_agent 聚合
└── core.py         # analyze_stock / analyze_batch
scripts/run_agent_team.py
tests/test_agent_team.py
```

## 8. 约束对齐（CLAUDE.md）
- 向量化优先、纯函数可测；P0 无 LLM 调用（模型路由留阶段二）。
- A 股硬约束（单票≤20% 最多5只、滑点、手续费）在阶段二 RiskAgent 落地；P0 聚合只出评级不出仓位。

## 9. 阶段二（2026-07-02 实现）与回测验收标准（用户 /goal）

**阶段二模块**：debate.py（v4-pro Bull/Bear/仲裁，触发线 65 分）、fusion.py（TrustTrade
贝叶斯融合，中立=恒等）、risk.py（Buy20%/增持12%、市值<10亿×0.5、偏空×0.5、限5只）、
GUI 投资判断 Tab「Agent Team 研判」区。全部失败回退 P0，永不阻塞。

**回测验收标准**（`scripts/backtest_agent_team.py` → `reports/agent_team_backtest.md`，
事件定义=用户给定，模块建成必须回测）：
1. 超短类：信号次日红盘率 ≥55% 且 ≥全市场基线+5pp
2. B1类：信号后3日累计涨幅>5% 命中率 ≥2×基线 且 ≥12%
3. 板块判断：强板块(≥60分)一周内(5交易日max)涨幅>2% 命中率 ≥1.5×基线 且 ≥35%
4. 研判（我方定义）：团队分≥60 股日 5日胜率 ≥55% 且超额>0；≥75(Buy) 3日胜率 ≥60%；
   另设生产口径 4c：每日 Top10(≥60分) 同 4a 通过线

**首轮回测发现（2025-06~2026-06 全市场，负结果如实记录）**：六项全部未达标；
B1 信号日 12.7% vs 基线 11.8% —— 与 Phase 3 结论自洽（优势在 B2 确认序列 72.4%/94.7%，
不在 B1 信号日）。据此迭代：`patterns.py` 战法序列状态机（B2确认=多头/B1候B2=中性），
agent 与回测严格共源。
