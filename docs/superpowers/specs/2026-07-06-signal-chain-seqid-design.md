# 信号链状态机改造：seq_id 贯穿（路线图#4）

> 日期：2026-07-06 | 来源：chan.py 信号链状态机（docs/research_journal/03_chan_py.md）
> 目标：B2 引用 B1、B3 引用 B2，seq_id 贯穿链路 → 完整 B1→B2→B3 序列胜率 vs 孤立信号胜率可量化

## 1. 缺口

- `b1_b2_b3_strategy.generate_signals` 产出 B1/B2/B3 是**独立行**：B2 只判断"过去5日内有 B1"
  （`in_b2_window`），B3 判断"过去3日内有 B2"，输出**不记录 seq_id** 把一条链串起来。
- 结果：无法按序列聚合，无法量化"B1 有多少推进到 B2、再到 B3"，也无法把 B2/B3 的收益
  归因到其源头 B1。roadmap #4 就是补这条链路。
- 已有 `playbook_engine.simulate_b1b2b3`（交易级：每 B1→首个 B2→首个 B3，signal_type
  已隐含链结果 B1_no_b2/B1_stop/B1B2/B1B2B3）。本改造让**信号级**输出与之**共源同义**。

## 2. seq_id 语义（与 simulate_b1b2b3 严格一致）

- 每个 **B1** 开启一条序列，`seq_id = f"{symbol}:{b1_date}"`（同一股同日唯一）。
- **B2**：B1 后 `[1, b2_window]` 日内**首个**满足 B2 条件的日，继承该 B1 的 seq_id；
  一条 B1 至多确认一个 B2（取首个，与模拟器一致）。B2 未现则序列止步 B1（孤立）。
- **B3**：B2 后 `[1, b3_window]` 日内**首个**满足 B3 条件的日，继承 seq_id；至多一个 B3。
- 多 B1 重叠：每个 B1 各开一条 seq；B2 归属"最近的、尚未被确认的、在窗口内的 B1"。

**关键：触发逻辑（哪些日 b1/b2/b3 为真）完全不变**，只在其上做**因果链路归属**后处理，
新增列 `seq_id / parent_stage / seq_root_date / stage_reached`。向后兼容（旧列不动）。

## 3. 实现（factors 无关，纯 strategies 后处理）

`b1_b2_b3_strategy.py` 内新增 `_assign_seq_ids(b1_sig, b2_sig, b3_sig, dates, symbol,
b2_window, b3_window) -> list[dict]`：单次线性扫描（因果，只用 ≤t 信息），
为每个信号行定位其 seq_id 与父阶段。`generate_signals` 调用它给三类信号行贴 seq 元数据。

链路扫描（O(n)）：
```
pending_b1 = None   # (seq_id, b1_idx)
pending_b2 = None   # (seq_id, b2_idx)
for i in 时间序:
    if b1_sig[i]: 开新 seq；pending_b1=(seq_i, i)   # 新B1覆盖旧的未确认B1（取最近）
    if b2_sig[i] and pending_b1 within b2_window:
        该B2.seq = pending_b1.seq; pending_b2=(seq, i); pending_b1=None
    if b3_sig[i] and pending_b2 within b3_window:
        该B3.seq = pending_b2.seq; pending_b2=None
```
孤立 B1（无 B2）：seq 只含 B1，stage_reached="B1"。

## 4. 序列聚合分析（验收核心）

`scripts/sequence_analysis.py`：全 universe 跑 generate_signals（带 seq_id），按 seq_id 聚合：
- **漏斗**：N 条 B1 序列 → 推进到 B2 的比例 → 推进到 B3 的比例
- **各阶段前向净胜率**：以每条序列的**B1 入场日**为基准，比较
  - 孤立 B1（止步 B1，无 B2）
  - 推进到 B2 的序列（在 B2 日入场）
  - 推进到 B3 的序列（在 B3 日入场）
  的 5/10 日前向净收益胜率
- **验证 roadmap 主张**：simulate_b1b2b3 交易级 B1B2B3 胜率 94.7%（reports/hold_matrix.md/
  agent_team_backtest.md）——本分析在序列维度复核该量级是否成立，并诚实报告
  （沿用 #3/#5 标准：不夸大、样本不足标注）。
→ reports/sequence_analysis.md

## 5. 测试（合成 + 构造场景）

`tests/test_signal_chain.py`：
- 构造 B1→B2→B3 明确链：断言三行同 seq_id、parent_stage 正确
- 两条独立链不串号；孤立 B1 只有自身 seq、stage_reached="B1"
- B2 超窗不继承（另起或悬空）
- 因果：截断尾部不改前段 seq 归属
- generate_signals 输出含新列且旧列/行数不变（向后兼容）

## 6. 不做

- 不改 simulate_b1b2b3（交易级已自洽；本次让信号级与之对齐，不动回测主干）
- 不把序列统计塞进 evening_review（其口径是单日 CSV；序列分析独立成脚本）
- 不引入新买卖点；S1/DD 卖点归因留作后续（本次只做买入链 B1→B2→B3）
