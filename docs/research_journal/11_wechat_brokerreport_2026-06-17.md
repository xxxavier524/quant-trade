# 微信公众号券商早报自动阅读方案调研

> 调研日期：2026-06-17  
> 调研目标：评估自动获取券商微信公众号早报/晨报并接入 AlphaPulse-A 的可行方案  
> 数据截止：2026-06 实际检索（不确定处标注「需进一步验证」）

---

## 一、背景与需求

AlphaPulse-A 已具备因子选股 + 每日盘中信号推送能力，下一步需要引入券商观点层，实现：

1. 每日 07:00–08:30 自动拉取主流券商晨报/早报正文
2. DeepSeek 摘要提炼：大盘观点 + 行业推荐 + 个股推荐
3. 结构化输出 → 飞书/飞书机器人推送 + 追加 `daily_auto_report.md`

---

## 二、方案逐一评估

### 2.1 搜狗微信搜索抓取（weixin.sogou.com）

| 维度 | 评估 |
|------|------|
| 原理 | 搜索 `weixin.sogou.com/weixin?type=2&query=<公众号名>` 返回近期文章列表及 mp.weixin.qq.com 真实链接 |
| 可用性 | 截至 2026-06 仍可访问；已有 MCP 工具封装（weixin_search_mcp） |
| 稳定性 | 中等。搜狗会做 IP 频率限制 + 验证码弹出；高并发下需轮换代理 |
| 反爬程度 | 中等。滑块验证码、User-Agent 检查；低频（<50次/天）可绕过 |
| 合规风险 | 搜狗服务条款禁止商业爬取；腾讯/搜狗随时可更改接口或关闭入口（需进一步验证法律边界） |
| 成本 | 代理 IP 费用（如使用商业代理 ¥50–200/月） |
| 适用场景 | 快速验证、低频按需查询；不适合稳定全自动流水线 |
| 参考项目 | [chyroc/WechatSogou](https://github.com/chyroc/WechatSogou)（较老，需自测可用性）、[weixin_search_mcp](https://github.com/fancyboi999/weixin_search_mcp)（2025 活跃，支持 MCP） |

**小结**：低成本快速验证首选，但作为生产级数据源风险较高，建议仅用于补充/兜底。

---

### 2.2 RSS 化方案

#### 2.2.1 WeWe RSS（cooderl/wewe-rss）

| 维度 | 评估 |
|------|------|
| 原理 | 接入微信读书账号，利用微信读书内部 API 轮询关注公众号的新文章列表，生成标准 RSS |
| 维护状态 | **已于 2026-05-11 归档（archive），不再主动维护**；9.6k stars；仍可 fork 自用 |
| 稳定性 | 微信读书 session 2–3 天过期需重新扫码；单账号跟踪 ≤10 个号较稳，超过易触发"封控"（24h 临时封禁） |
| 封号风险 | 中等。频繁添加/刷新触发验证机制；建议单账号 ≤10 公众号、刷新间隔 ≥6h |
| 部署方式 | Docker 一键部署：`docker run -d --name wewe-rss -p 4000:4000 cooderl/wewe-rss-web` |
| 成本 | 自建服务器（¥20–50/月 VPS） + 微信账号 |
| 合规风险 | 调用微信读书私有 API，违反微信服务条款；腾讯不定期更新封堵策略 |

**小结**：项目已停止维护，长期稳定性存疑。适合个人尝鲜，不适合 7×24 生产。

#### 2.2.2 We-MP-RSS（rachelos/we-mp-rss）

| 维度 | 评估 |
|------|------|
| 原理 | Python/FastAPI + Vue3 前后端分离；需要提供微信公众号 Cookie/Token 进行认证抓取；支持 Webhook 推送、转 Markdown/PDF、AI Agent 接入 |
| 维护状态 | **活跃维护**，最新版本 v1.5.2（2026-04），3.6k stars，604 forks |
| 稳定性 | 依赖 Cookie 有效期；支持 Redis/Memcached 缓存；父子节点级联架构可横向扩展 |
| 封号风险 | 中等。需用已登录微信账号的 Cookie；异常访问频率可能触发封号 |
| 接入友好度 | 提供 Webhook + REST API，可直接被 AlphaPulse-A 脚本调用 |
| 部署方式 | `docker run -d --name we-mp-rss -p 8001:8001 -v ./data:/app/data ghcr.io/rachelos/we-mp-rss:latest` |
| 成本 | VPS（¥20–50/月） |
| 合规风险 | 同上，调用微信私有接口 |

**小结**：目前最推荐的 RSS 化方案。Webhook 接口可直接对接脚本，Markdown 输出方便 DeepSeek 摘要。

#### 2.2.3 RSSHub 微信路由

| 维度 | 评估 |
|------|------|
| 原理 | RSSHub 有 `/wechat/` 路由，但需要配合 WeChatFerry 或第三方网关；公共实例大多失效 |
| 维护状态 | RSSHub 项目本身活跃，但微信路由**需进一步验证**是否可用（2026 年多用户反馈失效） |
| 稳定性 | 依赖网关可用性，公共实例不稳定；自建网关成本高 |
| 合规风险 | 同微信私有 API 问题 |

**小结**：不推荐作为主链路，可作备选了解。

#### 2.2.4 feeddd

已于 2026-01-19 归档停止维护，**不再推荐**。

---

### 2.3 微信公众号官方导出能力

官方仅提供「账号迁移」（将粉丝/文章迁移到另一个账号），**不提供订阅号文章批量导出 API**。读者无法通过官方渠道批量拉取他人公众号内容。唯一半官方路径是公众号运营者后台可导出自己账号的文章列表（仅运营者可用）。

**结论**：对于读者侧的自动阅读需求，官方没有可用接口。

---

### 2.4 替代且更稳的券商观点源

这是**合规风险最低、最稳定**的一组方案，强烈推荐作为主数据源。

#### 2.4.1 AKShare 财联社电报 `stock_info_global_cls`

| 维度 | 评估 |
|------|------|
| 接口 | `ak.stock_info_global_cls(symbol="全部")` → 返回近 300 条财联社电报 |
| 稳定性 | 2025-02 曾出现接口断裂（GitHub Issue #5732）；AKShare 团队通常 1–2 周内修复 |
| 数据质量 | 财联社电报覆盖盘前重要资讯、政策、板块消息，质量较高 |
| 成本 | 完全免费，pip install akshare |
| 合规风险 | **低**。AKShare 抓取公开可访问数据，无需账号；财联社数据已通过 AKShare 合法封装 |
| 局限 | 非完整早报正文，属电报体（50–200字/条），不含详细分析 |

#### 2.4.2 AKShare 东财研报 `stock_research_report_em`

| 维度 | 评估 |
|------|------|
| 接口 | `ak.stock_research_report_em(symbol="600519")` → 个股研报列表（机构/日期/目标价/评级） |
| 稳定性 | 中等；东财高并发时会临时封 IP，建议请求间隔 1–3s |
| 数据质量 | 覆盖主流券商研报摘要；部分含 PDF 链接可进一步下载 |
| 成本 | 免费 |
| 合规风险 | 低（公开页面数据） |
| 局限 | 研报摘要为主，无法获取完整 PDF 正文（需进一步验证 PDF 直链是否稳定） |

#### 2.4.3 慧博研报（hibor.com.cn）

| 维度 | 评估 |
|------|------|
| 可用性 | 网站提供研报下载，但无公开 API；需要登录 + 会员 |
| 自动化可行性 | 需 Playwright 模拟已登录浏览器操作（见 2.5 节） |
| 成本 | 会员费用（需进一步验证具体价格） |
| 合规风险 | 中等（需要遵守用户协议） |

#### 2.4.4 雪球 `pysnowball`

| 维度 | 评估 |
|------|------|
| 原理 | 雪球非官方 Python 接口（uname-yang/pysnowball） |
| 数据内容 | 个股新闻、机构持仓、观点等；无标准晨报接口 |
| 稳定性 | 依赖 Cookie；雪球反爬中等 |
| 合规风险 | 中等 |
| 适用性 | 补充个股舆情，非晨报替代 |

#### 方案对比表（替代源）

| 数据源 | 接口类型 | 稳定性 | 合规风险 | 成本 | 晨报覆盖度 |
|--------|---------|--------|---------|------|-----------|
| AKShare 财联社电报 | Python 库 | 中（偶发断裂） | 低 | 免费 | 电报体，高频 |
| AKShare 东财研报 | Python 库 | 中 | 低 | 免费 | 研报摘要 |
| 慧博研报 | 浏览器自动化 | 中 | 中 | 会员费 | 全文研报 |
| 雪球 pysnowball | Python 库 | 中 | 中 | 免费 | 个股舆情 |
| 财新/21财经 RSS | 标准 RSS | 高 | 低 | 免费/付费 | 宏观/财经新闻 |

---

### 2.5 浏览器自动化方案（已登录账号）

#### 原理

使用 Playwright（推荐）或 Selenium 驱动已登录微信网页版（wx.qq.com）或公众号文章页面，自动打开特定公众号历史消息页，截取当日最新文章正文。

#### 可行性分析

| 维度 | 评估 |
|------|------|
| 技术可行性 | 可行。Playwright 支持持久化 Browser Context（保存 Cookie/session），可复用已登录状态 |
| 稳定性 | 中等。微信网页版登录态 7–30 天需重新扫码；页面结构变更时需维护选择器 |
| 反爬程度 | 微信文章页（mp.weixin.qq.com）无明显反爬；但自动化特征（无头浏览器）可能触发人机验证 |
| 封号风险 | 微信号有被限制风险；建议使用专用小号操作 |
| 合规风险 | 中高。模拟用户操作抓取仍违反微信服务条款；但仅个人使用时实际执法风险低 |
| 成本 | 代码维护成本；需要本地机器常驻或 VPS 部署 Chrome |
| 适用场景 | 无其他方案时的兜底；或补充抓取特定高价值公众号 |

**推荐实现**：Playwright Python + `browser_context.storage_state()` 持久化登录态，定时任务抓取指定公众号首页最新文章 URL，再调用 `page.goto(url)` 获取正文。

---

## 三、推荐方案

### 方案 A：理想稳态（生产级）

```
主数据流（合规 + 稳定）：
  AKShare 财联社电报（每日 07:00 拉取）
  + AKShare 东财研报摘要（按持仓股每日拉取）
  + We-MP-RSS 自建（10 个核心券商公众号，Webhook 推送）

清洗层：
  Python 脚本解析/去重/结构化

摘要层：
  DeepSeek-v4-pro（重要性判断 + 个股关联）
  DeepSeek-v4-flash（批量摘要）

输出层：
  追加 daily_auto_report.md
  飞书机器人 Webhook 推送卡片
```

**核心券商公众号建议订阅**（需进一步验证最新公众号 ID）：
- 中信证券研究（citics_research）
- 国泰君安证券研究
- 华泰证券研究
- 中金研究
- 广发证券研究
- 天风证券研究
- 国盛证券研究所

**成本估算**：VPS ¥30/月 + DeepSeek API（每日约 5万 token ≈ ¥0.5–1/天）

---

### 方案 B：低成本快速验证（1–3 天内跑通）

```
第一步：安装 akshare，跑通财联社电报拉取
  ak.stock_info_global_cls(symbol="全部")

第二步：搜狗微信 MCP（weixin_search_mcp）手动查询 2–3 个公众号
  验证是否能获取全文

第三步：接 DeepSeek API 做一次摘要测试

第四步：飞书机器人 Webhook 推送一条测试消息
```

估时：4–6 小时完成可行性验证，无需部署服务器。

---

## 四、接入 AlphaPulse-A 数据流

### 新增脚本

```
scripts/
├── fetch_broker_morning.py     # 主脚本：拉取早报数据
├── wechat_rss_client.py        # We-MP-RSS Webhook 客户端
├── akshare_news_fetcher.py     # AKShare 财联社/研报拉取
└── morning_report_summary.py   # DeepSeek 摘要生成 + 飞书推送
```

### 数据流示意

```
06:50  launchd 触发 fetch_broker_morning.py
  ├── akshare_news_fetcher.py
  │     ├── ak.stock_info_global_cls()  → 财联社电报 JSON
  │     └── ak.stock_research_report_em(持仓股列表)  → 研报列表
  ├── wechat_rss_client.py
  │     └── GET http://localhost:8001/api/feed/<公众号>  → 文章 Markdown
  └── 合并去重 → morning_raw_{date}.json

07:10  morning_report_summary.py
  ├── DeepSeek-v4-flash 批量摘要（每篇 500字 → 100字）
  ├── DeepSeek-v4-pro 综合判断（大盘观点 + 持仓关联）
  ├── 追加 daily_auto_report.md
  └── 飞书 Webhook → 卡片消息（标题/摘要/关联股票）
```

### 飞书消息卡片示例结构

```json
{
  "msg_type": "interactive",
  "card": {
    "header": {"title": "2026-06-17 券商早报摘要"},
    "elements": [
      {"tag": "div", "text": "大盘观点：..."},
      {"tag": "div", "text": "行业关注：..."},
      {"tag": "div", "text": "持仓相关：600519 茅台 - 中信维持买入..."}
    ]
  }
}
```

---

## 五、各方案路径对比表

| 方案 | 可行性 | 稳定性 | 合规风险 | 成本 | 接入难度 | 推荐 |
|------|--------|--------|---------|------|---------|------|
| 搜狗微信搜索抓取 | 中 | 低 | 高 | 低 | 中 | 兜底补充 |
| WeWe RSS（已归档） | 中 | 低 | 高 | 低 | 低 | 不推荐 |
| We-MP-RSS（活跃） | 高 | 中 | 高 | 中 | 低 | 推荐（主公众号流） |
| RSSHub 微信路由 | 低 | 低 | 高 | 低 | 高 | 不推荐 |
| 官方导出 | 不可用 | — | — | — | — | 不适用 |
| AKShare 财联社电报 | 高 | 中 | 低 | 免费 | 低 | 强烈推荐（主流） |
| AKShare 东财研报 | 高 | 中 | 低 | 免费 | 低 | 强烈推荐（研报） |
| 慧博研报 | 中 | 中 | 中 | 会员费 | 高 | 可选 |
| 雪球 pysnowball | 中 | 中 | 中 | 免费 | 低 | 舆情补充 |
| Playwright 浏览器自动化 | 高 | 中 | 中高 | 低 | 高 | 高价值号兜底 |

---

## 六、合规提示

1. **AKShare 系列接口**：抓取东财/财联社公开页面数据，AKShare 作为中间层已广泛被学术和个人使用，但仍建议控制请求频率（间隔 ≥1s），**不用于商业分发**。

2. **We-MP-RSS / WeWe RSS**：使用微信账号 Cookie 调用私有 API，明确违反《微信公众平台服务协议》第 7 条。建议：
   - 使用专用小号，不绑定真实身份
   - 仅用于个人研究，不分发数据
   - 知晓账号可能被封的风险

3. **搜狗微信搜索**：搜狗服务条款禁止自动化抓取；2024 年腾讯收购搜狗后接口政策可能进一步收紧（需进一步验证）。

4. **券商早报版权**：券商研报/晨报享有著作权，自动获取后**仅供内部使用**，不得对外分发或用于商业目的。

5. **个人使用 vs 商业使用**：上述方案均建议限定在个人量化研究场景，如需商业化需对接正规数据商（如 Wind、Bloomberg）。

---

## 七、参考链接

- [WeWe RSS GitHub（已归档）](https://github.com/cooderl/wewe-rss)
- [We-MP-RSS GitHub（活跃维护）](https://github.com/rachelos/we-mp-rss)
- [weixin_search_mcp MCP工具](https://github.com/fancyboi999/weixin_search_mcp)
- [AKShare 官方文档](https://akshare.akfamily.xyz/)
- [AKShare stock_info_global_cls Issue #5732](https://github.com/akfamily/akshare/issues/5732)
- [WeRss 微信公众号RSS订阅（已关停）](https://werss.app/)
- [微信公众号RSS方案汇总 - 知乎](https://zhuanlan.zhihu.com/p/2012810675609699554)
- [飞书 Webhook 接入教程](https://www.feishu.cn/content/7271149634339422210)
- [AKShare 财联社电报接口说明](https://zhuanlan.zhihu.com/p/707002961)
- [We-MP-RSS 少数派评测](https://sspai.com/post/93845)

---

*调研者：AlphaPulse-A Claude Agent | 2026-06-17*
