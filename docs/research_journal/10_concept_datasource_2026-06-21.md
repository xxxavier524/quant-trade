# 精读笔记 10：概念/板块数据源补全（实测决策）

> 任务 #4：概念信息不全，很多新板块/概念没显示。2026-06-21 实测定案。

## 问题
系统原用 akshare **新浪概念**（`stock_sector_spot(indicator="概念")` + `stock_sector_detail`），
只有约 126 个概念，热点严重缺失。

## 三源实测对比（本机，akshare 1.18.60）

| 源 | 接口 | 概念数 | 热点覆盖(抽样) | 状态 |
|---|---|---|---|---|
| 新浪(原) | `stock_sector_spot/detail` | 126 | 2/12（仅固态电池/机器人） | 基线 |
| 东财 EM | `stock_board_concept_name_em` | — | — | ❌ ConnectionError（本机被封，确认不可用） |
| **同花顺 THS** | `stock_board_concept_name_ths` | **373** | **10/12**（固态电池/低空经济/人形机器人/算力/液冷/CPO/减肥药/可控核聚变/脑机接口/机器人） | ✅ 采纳 |

## 采纳方案：同花顺
- 概念列表：`stock_board_concept_name_ths()` → `{name, code}`，函数稳定。
- 成员股：该 akshare 版本**已移除** `stock_board_concept_cons_ths`；改为直连 THS 概念详情页
  `q.10jqka.com.cn/gn/detail/.../code/{code}`，会话+重试+退避绕反爬（`hexin-v` 节流），
  解析 `stockpage.10jqka.com.cn/{6位代码}` 提取成员。见 `scripts/fetch_concepts_ths.py`。
- 催化事件：`stock_board_concept_summary_ths()` 的「驱动事件」落 `data/meta/concept_catalysts.json`
  （sidecar，供「投资判断」概念研判用）。

## 落地结果（2026-06-18 全量抓取）
- `data/meta/concept_members.json`：**366 概念 / 18016 成员条目**（source=ths），旧新浪版备份为 `concept_members.sina-backup.json`。
- 抽样验证：`002056` → 光伏/固态电池/低碳经济（新热点正确挂载）；映射覆盖 4540 只。

## 已知限制 / 后续
- **THS 每概念约 50 名成员上限**（详情页首页 50/页，反爬使深翻页不稳）：大概念只取前 ~50（通常按权重/规模靠前），足够做概念标注；若需全量成员，后续补稳健翻页或 cookie。
- 减肥药/稳定币/Sora 等个别题材 THS 命名不同或未单列。
- **传播待办**：`concept_members.json` 已更新，但选股结果里的 `concepts` 列需重跑
  `python scripts/daily_screener.py` 才会刷新（当前外接数据盘未挂载，挂载后一条命令即生效）。
