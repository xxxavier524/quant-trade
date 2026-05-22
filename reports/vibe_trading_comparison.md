# Vibe-Trading vs AlphaPulse-A 深度对比

> 来源：HKUDS/Vibe-Trading (7,100+ Stars, MIT) | 对比日期：2026-05-22

---

## 总览

| 维度 | Vibe-Trading | AlphaPulse-A |
|------|-------------|-------------|
| 定位 | LLM原生多智能体金融工作台 | A股规则型量化选股系统 |
| 架构 | LangGraph DAG多智能体群 | 线性7-Agent Pipeline |
| 技能数 | 74个SKILL.md (8类) | 19个因子模块 |
| 回测引擎 | 7个(股/期/汇/加密/期权) | 1个(A股独立引擎) |
| 验证体系 | Monte Carlo + Bootstrap CI | **DSR + Purged CV + Walk-Forward** |
| LLM | 13+提供商 | DeepSeek为主 |
| 前端 | React 19 + Vite | Vanilla HTML + Chart.js |
| 导出 | Pine v6 + MT5 + TDX + vnpy | QMT CSV + vnpy CtaTemplate |
| 实盘 | Shadow Account | vnpy CTP + launchd |

---

## 各模块对比

### 1. 技能/因子系统
- **VT**: 74个SKILL.md，覆盖策略/分析/资产类别/加密/Flow/工具/风控8大类。自演化记忆。
- **AP-A**: 19个Python因子模块，scipy/pandas向量化。静态代码。
- **差距**: VT覆盖面广（加密/期权/宏观），AP-A算法精度高（IC分析/去重）
- **整合价值**: ★★★★☆ (SKILL.md知识库模式可借鉴)

### 2. 多智能体编排
- **VT**: LangGraph DAG，29个预设团队(投资委员会/加密桌/量化桌)，并行执行
- **AP-A**: 线性pipeline (假设→数据→代码→回测→审查→DSR→风控)
- **差距**: VT并行+动态路由，AP-A串行固定
- **整合价值**: ★★★★★ (Swarm模式是最大差异化优势)

### 3. 回测引擎
- **VT**: 7引擎(A股/港股美股/期货/外汇/加密/期权)+跨市场组合引擎
- **AP-A**: 1引擎(A股) + 8指标 + 独立验证(DSR/Purged CV)
- **差距**: 市场覆盖不如VT，但统计验证更严格
- **整合价值**: ★★★☆☆ (我们验证强，他们覆盖广)

### 4. 多平台导出
- **VT**: Pine Script v6 + MQL5(MT5) + TDX公式 + vnpy
- **AP-A**: QMT CSV + vnpy CtaTemplate
- **差距**: Pine Script/MQL5完全是空白
- **整合价值**: ★★★★★ (模板式代码生成，低成本高价值)

### 5. LLM多提供商
- **VT**: 13+ (OpenRouter/OpenAI/DeepSeek/Gemini/Groq/Ollama等)
- **AP-A**: DeepSeek主用(+litellm备选)
- **整合价值**: ★★★☆☆ (OpenRouter网关模式简洁)

---

## 整合建议

| 优先级 | 功能 | 难度 | 价值 | 工作估计 |
|--------|------|------|------|---------|
| **P0** | Pine Script/MQL5导出模板 | 低 | 高 | 2-3天 |
| **P0** | OpenRouter多提供商抽象 | 低 | 中 | 1-2天 |
| **P1** | SKILL.md知识库+自然语言查询 | 中 | 高 | 5-7天 |
| **P1** | DAG多智能体群(LangGraph) | 中 | 高 | 7-10天 |
| **P1** | MCP服务器(Claude/Cursor) | 低 | 高 | 2-3天 |
| **P2** | 加密/期货回测引擎 | 中 | 中 | 10-15天 |
| **P3** | React前端+流式仪表盘 | 高 | 低 | 15-20天 |

---

## 结论

**Vibe-Trading优势**: LLM原生多智能体协作 + 74技能广覆盖 + 跨市场引擎 + 多平台导出
**AlphaPulse-A优势**: DSR/Purged CV统计严谨性 + A股深度因子库 + 无人值守生产化

**互补性强**: 我们的验证Gate可增强VT，VT的Swarm编排和多平台导出可扩充AP-A。

关键洞察：VT用 LangGraph DAG 实现"辩论式决策"（牛/熊分析师并行分析→PM综合决策），这是单管线无法做到的。应优先整合。
