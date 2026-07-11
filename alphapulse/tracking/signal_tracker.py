"""信号追踪与因子沉淀 — 用户闭环：选股 → 跟踪 → 成功判定 → 归因沉淀。

流程（用户确认需求 2026-06-11；成功率跟踪需求 2026-07-10）：
1. record_signals: 每日 screen Top50 写入 tracking 库（sqlite），含战法归属
2. update_performance: 用日线数据回填每个信号后 1-7 日逐日涨跌
3. evaluate_outcomes: 5日内涨超+5%（脱离成本区）=成功；累计跌超-5%=大跌停跟踪
4. distill_success: 对成功标的自动复盘（选股过程/特征/上涨原因，DeepSeek）
5. success_stats/nightly_review_text: 按两大战法分开统计成功率，推飞书夜间复盘
6. find_streaks/distill: 连涨归因 → 候选因子 + ML 强化样本（既有闭环，保留）

存储：backtest_results/signal_tracking.db
  signals(id, date, symbol, name, score, strict, sector, close, sub_scores,
          strategies, family, reason, top_factors, concepts, pattern_state,
          status[tracking/success/stopped_drop/expired], outcome_day, outcome_pct, reviewed)
  performance(signal_id, day_n, date, close, pct_change)
  pick_reviews(signal_id, date, symbol, review)
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "backtest_results" / "signal_tracking.db"
REVIEWS_MD = PROJECT_ROOT / "reports" / "pick_reviews.md"

SUB_COLS = ["j_low", "trend_gap", "vol_shrink", "yangyin", "surge", "dif",
            "ql_pos", "pct_calm", "amplitude", "bowl", "washout_recover"]

# 成功/止踪口径（用户 2026-07-10 定义）
SUCCESS_PCT = 5.0      # 5日内相对信号日收盘涨超 +5% = 脱离成本区（成功）
STOP_DROP_PCT = -5.0   # 累计跌超 -5% = 大幅下跌，停止跟踪
HORIZON_DAYS = 5       # 跟踪窗口（交易日）
STALE_CALENDAR_DAYS = 21  # 数据长期缺失的信号按过期处理，防止永久悬挂

_FAMILY_PATH = PROJECT_ROOT / "config" / "strategy_families.json"
_DEFAULT_FAMILIES = {"基本面法": ["B1", "量能B1", "单针下三十"], "砖型图法": ["知行超短"]}


def load_families() -> dict:
    """战法家族映射：家族名 -> strategies 标签列表（config 可编辑，缺失用默认）。"""
    try:
        raw = json.loads(_FAMILY_PATH.read_text(encoding="utf-8"))
        fams = {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, list)}
        return fams or dict(_DEFAULT_FAMILIES)
    except Exception:
        return dict(_DEFAULT_FAMILIES)


def family_of(strategies: str) -> str:
    """由 strategies 标签串（如 'B1+量能B1'）归出战法家族。

    命中一个家族返回家族名；同时命中两个返回 '基本面法+砖型图法'（双法共振，
    用户明确要求交叉重叠须标注互相强化）；都不命中返回 ''（综合评分/周线金叉）。
    """
    tags = set((strategies or "").split("+"))
    fams = load_families()
    hit = [name for name, members in fams.items() if tags & set(members)]
    return "+".join(sorted(hit, key=list(fams).index)) if hit else ""


_SIGNAL_EXTRA_COLS = [
    ("strategies", "TEXT DEFAULT ''"), ("family", "TEXT DEFAULT ''"),
    ("reason", "TEXT DEFAULT ''"), ("top_factors", "TEXT DEFAULT ''"),
    ("concepts", "TEXT DEFAULT ''"), ("pattern_state", "TEXT DEFAULT ''"),
    ("status", "TEXT DEFAULT 'tracking'"), ("outcome_day", "INTEGER"),
    ("outcome_pct", "REAL"), ("reviewed", "INTEGER DEFAULT 0"),
]


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, symbol TEXT, name TEXT, score REAL, strict INTEGER,
        sector TEXT, close REAL, sub_scores TEXT,
        UNIQUE(date, symbol))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS performance (
        signal_id INTEGER, day_n INTEGER, date TEXT, close REAL, pct_change REAL,
        UNIQUE(signal_id, day_n))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pick_reviews (
        signal_id INTEGER PRIMARY KEY, date TEXT, symbol TEXT, review TEXT)""")
    existing = {r[1] for r in conn.execute("PRAGMA table_info(signals)")}
    for col, decl in _SIGNAL_EXTRA_COLS:
        if col not in existing:
            conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {decl}")
    return conn


def _clean(v) -> str:
    """pandas 空值/NaN 一律转空串，避免 'nan' 字符串进库污染展示。"""
    s = "" if v is None or (isinstance(v, float) and v != v) else str(v)
    return "" if s in ("nan", "None") else s


def _snapshot_fields(r) -> tuple:
    """从 screen 行提取选股快照（战法/理由/贡献/概念/形态），供成功复盘还原选股过程。"""
    strategies = _clean(r.get("strategies"))
    return (strategies, family_of(strategies),
            _clean(r.get("reason")), _clean(r.get("top_factors")),
            _clean(r.get("concepts")), _clean(r.get("pattern_state")))


def record_signals(screen_csv: Path) -> int:
    """把一份 screen_*.csv 的信号写入追踪库（幂等），含战法归属与选股快照。"""
    df = pd.read_csv(screen_csv, dtype={"symbol": str})
    date = screen_csv.stem.replace("screen_", "")
    conn = _conn()
    n = 0
    for _, r in df.iterrows():
        subs = {c: float(r[c]) for c in SUB_COLS if c in df.columns and pd.notna(r.get(c))}
        try:
            conn.execute(
                "INSERT OR IGNORE INTO signals(date,symbol,name,score,strict,sector,close,sub_scores,"
                "strategies,family,reason,top_factors,concepts,pattern_state) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (date, str(r["symbol"]).zfill(6), _clean(r.get("name")),
                 float(r["score"]), int(bool(r.get("strict_signal", False))),
                 _clean(r.get("sector")), float(r.get("close", 0)), json.dumps(subs),
                 *_snapshot_fields(r)))
            n += conn.execute("SELECT changes()").fetchone()[0]
        except Exception:
            continue
    conn.commit()
    conn.close()
    return n


def backfill_labels() -> int:
    """用历史 screen_*.csv 回填库中缺战法标注的旧信号（幂等，一次性成本）。"""
    conn = _conn()
    missing = pd.read_sql(
        "SELECT id, date, symbol FROM signals WHERE strategies='' OR strategies IS NULL", conn)
    if missing.empty:
        conn.close()
        return 0
    n = 0
    for date, grp in missing.groupby("date"):
        csv = PROJECT_ROOT / "reports" / f"screen_{date}.csv"
        if not csv.exists():
            continue
        df = pd.read_csv(csv, dtype={"symbol": str})
        if "strategies" not in df.columns:
            continue
        rows = {str(r["symbol"]).zfill(6): r for _, r in df.iterrows()}
        for _, sig in grp.iterrows():
            r = rows.get(sig["symbol"])
            if r is None:
                continue
            conn.execute(
                "UPDATE signals SET strategies=?,family=?,reason=?,top_factors=?,"
                "concepts=?,pattern_state=? WHERE id=?",
                (*_snapshot_fields(r), int(sig["id"])))
            n += 1
    conn.commit()
    conn.close()
    return n


def update_performance(data_dir: Path, horizon: int = 7) -> int:
    """回填所有未完成信号的逐日表现（信号日后1~horizon个交易日）。"""
    conn = _conn()
    sigs = pd.read_sql("SELECT id, date, symbol FROM signals", conn)
    if sigs.empty:
        conn.close()
        return 0
    done = pd.read_sql("SELECT signal_id, COUNT(*) c FROM performance GROUP BY signal_id", conn)
    done_map = dict(zip(done["signal_id"], done["c"])) if not done.empty else {}

    updated = 0
    for sym, group in sigs.groupby("symbol"):
        pending = [(r["id"], r["date"]) for _, r in group.iterrows()
                   if done_map.get(r["id"], 0) < horizon]
        if not pending:
            continue
        p = data_dir / f"{sym}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, usecols=["date", "close"])
        dates = df["date"].tolist()
        closes = df["close"].tolist()
        idx_map = {d: i for i, d in enumerate(dates)}
        for sig_id, sig_date in pending:
            i0 = idx_map.get(sig_date)
            if i0 is None:
                continue
            base = closes[i0]
            for n in range(1, horizon + 1):
                if i0 + n >= len(dates):
                    break
                prev = closes[i0 + n - 1]
                conn.execute(
                    "INSERT OR IGNORE INTO performance VALUES(?,?,?,?,?)",
                    (sig_id, n, dates[i0 + n], closes[i0 + n],
                     round((closes[i0 + n] / prev - 1) * 100, 3)))
                updated += 1
    conn.commit()
    conn.close()
    return updated


def evaluate_outcomes(success_pct: float = SUCCESS_PCT, stop_pct: float = STOP_DROP_PCT,
                      horizon: int = HORIZON_DAYS) -> dict:
    """对在跟踪信号做成功/止踪判定（幂等，只改 status='tracking' 的行）。

    逐日走：先到 +success_pct（相对信号日收盘）→ success（脱离成本区）；
    先到 stop_pct → stopped_drop（大幅下跌，不再跟踪）；
    horizon 个交易日走完两者皆未触发 → expired；
    数据长期缺失（超 STALE_CALENDAR_DAYS 自然日仍不满窗）→ expired 兜底。
    """
    conn = _conn()
    sigs = pd.read_sql(
        "SELECT id, date, close FROM signals WHERE status='tracking' AND close > 0", conn)
    if sigs.empty:
        conn.close()
        return {"success": 0, "stopped_drop": 0, "expired": 0}
    perf = pd.read_sql(
        "SELECT signal_id, day_n, close FROM performance WHERE signal_id IN (%s) "
        "ORDER BY signal_id, day_n" % ",".join(str(i) for i in sigs["id"]), conn)
    perf_map = {sid: g for sid, g in perf.groupby("signal_id")}
    today = datetime.now().date()
    counts = {"success": 0, "stopped_drop": 0, "expired": 0}
    for _, s in sigs.iterrows():
        g = perf_map.get(s["id"])
        new_status, out_day, out_pct = None, None, None
        if g is not None:
            g5 = g[g["day_n"] <= horizon]
            for _, p in g5.iterrows():
                cum = (p["close"] / s["close"] - 1) * 100
                if cum >= success_pct:
                    new_status, out_day, out_pct = "success", int(p["day_n"]), round(cum, 2)
                    break
                if cum <= stop_pct:
                    new_status, out_day, out_pct = "stopped_drop", int(p["day_n"]), round(cum, 2)
                    break
            else:
                if len(g5) >= horizon:
                    last = g5.iloc[-1]
                    new_status = "expired"
                    out_day, out_pct = horizon, round((last["close"] / s["close"] - 1) * 100, 2)
        if new_status is None:
            try:
                age = (today - datetime.strptime(s["date"], "%Y-%m-%d").date()).days
                if age > STALE_CALENDAR_DAYS:
                    new_status = "expired"
            except ValueError:
                pass
        if new_status:
            conn.execute("UPDATE signals SET status=?, outcome_day=?, outcome_pct=? WHERE id=?",
                         (new_status, out_day, out_pct, int(s["id"])))
            counts[new_status] += 1
    conn.commit()
    conn.close()
    return counts


def success_stats(window_days: int = 30) -> dict:
    """按战法家族统计成功率（近 window_days 自然日内的信号，已出结果的为分母）。"""
    conn = _conn()
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    df = pd.read_sql(
        "SELECT family, status, outcome_day FROM signals WHERE date >= ?", conn, params=(cutoff,))
    conn.close()
    fams = list(load_families()) + ["基本面法+砖型图法", ""]
    out = {}
    for fam in fams:
        sub = df[df["family"] == fam]
        resolved = sub[sub["status"].isin(["success", "expired", "stopped_drop"])]
        succ = resolved[resolved["status"] == "success"]
        out[fam or "综合评分"] = {
            "resolved": len(resolved), "success": len(succ),
            "rate": round(len(succ) / len(resolved) * 100, 1) if len(resolved) else None,
            "avg_days": round(succ["outcome_day"].mean(), 1) if len(succ) else None,
            "tracking": int((sub["status"] == "tracking").sum()),
            "stopped": int((sub["status"] == "stopped_drop").sum()),
        }
    return out


def _rule_based_review(row: dict, path_text: str) -> str:
    """无 LLM 时的复盘兜底：直接由快照字段拼装。"""
    return (f"选股过程: {row['strategies'] or '综合评分'}触发，总分{row['score']:.0f}，"
            f"主要贡献 {row['top_factors'] or '—'}。"
            f"特征: {row['sector'] or '未知板块'} | {row['concepts'] or '无概念标注'}"
            f"{(' | 形态 ' + row['pattern_state']) if row['pattern_state'] else ''}。"
            f"走势: {path_text}，第{row['outcome_day']}日脱离成本区(+{row['outcome_pct']}%)。")


def distill_success(use_llm: bool = True, limit: int = 5) -> list:
    """对新晋成功信号自动复盘（选股过程/股票特征/上涨原因），写库并追加 Markdown。"""
    conn = _conn()
    rows = pd.read_sql(
        "SELECT * FROM signals WHERE status='success' AND reviewed=0 ORDER BY date DESC LIMIT ?",
        conn, params=(limit,))
    if rows.empty:
        conn.close()
        return []
    reviews = []
    for _, r in rows.iterrows():
        perf = pd.read_sql(
            "SELECT day_n, close FROM performance WHERE signal_id=? ORDER BY day_n",
            conn, params=(int(r["id"]),))
        path_text = " → ".join(
            f"D{int(p['day_n'])} {(p['close'] / r['close'] - 1) * 100:+.1f}%"
            for _, p in perf.head(int(r["outcome_day"] or HORIZON_DAYS)).iterrows())
        row = r.to_dict()
        text = None
        if use_llm:
            try:
                from alphapulse.llm.client import chat, is_configured, MODEL_REASONING
                if is_configured():
                    subs = json.loads(r["sub_scores"] or "{}")
                    top_subs = dict(sorted(subs.items(), key=lambda kv: -kv[1])[:4])
                    prompt = (
                        f"A股复盘。{r['date']} 选出 {r['symbol']} {r['name']}"
                        f"（战法: {r['strategies']}，家族: {r['family'] or '综合评分'}，总分{r['score']:.0f}），"
                        f"选股依据: {r['top_factors'] or r['reason'] or '综合因子'}；"
                        f"信号日突出子分数: {json.dumps(top_subs, ensure_ascii=False)}；"
                        f"板块: {r['sector']}，概念: {r['concepts']}"
                        f"{('，形态: ' + r['pattern_state']) if r['pattern_state'] else ''}。"
                        f"随后走势 {path_text}，第{int(r['outcome_day'])}日涨幅达 +{r['outcome_pct']}% 脱离成本区。"
                        "请用≤120字总结: ①选股过程为何命中 ②该股关键特征 ③上涨的可能原因。只基于给定信息，勿编造消息面。")
                    text = chat(prompt, model=MODEL_REASONING, max_tokens=400)
            except Exception:
                text = None
        if not text:
            text = _rule_based_review(row, path_text)
        conn.execute("INSERT OR REPLACE INTO pick_reviews VALUES(?,?,?,?)",
                     (int(r["id"]), r["date"], r["symbol"], text))
        conn.execute("UPDATE signals SET reviewed=1 WHERE id=?", (int(r["id"]),))
        reviews.append({"date": r["date"], "symbol": r["symbol"], "name": r["name"],
                        "family": r["family"], "strategies": r["strategies"],
                        "outcome_day": int(r["outcome_day"]), "outcome_pct": float(r["outcome_pct"]),
                        "review": text})
    conn.commit()
    conn.close()
    if reviews:
        REVIEWS_MD.parent.mkdir(exist_ok=True)
        with open(REVIEWS_MD, "a", encoding="utf-8") as f:
            for rv in reviews:
                f.write(f"\n## {rv['date']} {rv['symbol']} {rv['name']} "
                        f"+{rv['outcome_pct']}%(第{rv['outcome_day']}日) "
                        f"[{rv['family'] or '综合评分'}·{rv['strategies']}]\n\n{rv['review']}\n")
    return reviews


def nightly_review_text(new_reviews: list | None = None, new_outcomes: dict | None = None) -> str:
    """夜间复盘飞书文本：按战法分列的成功率 + 今日新成功案例复盘 + 止踪通报。"""
    stats = success_stats()
    lines = [f"🌙 夜间复盘 {datetime.now():%Y-%m-%d}",
             f"【选股成功率·近30日】(成功={HORIZON_DAYS}日内涨超{SUCCESS_PCT:.0f}%脱离成本区)"]
    for fam, s in stats.items():
        if s["resolved"] == 0 and s["tracking"] == 0:
            continue
        rate = f"{s['rate']}%" if s["rate"] is not None else "—"
        avg = f"，均{s['avg_days']}日达标" if s["avg_days"] else ""
        lines.append(f"· {fam}: {s['success']}/{s['resolved']}={rate}{avg}"
                     f" | 跟踪中{s['tracking']} 止踪{s['stopped']}")
    if new_reviews:
        lines.append("⭐ 新脱离成本区:")
        for rv in new_reviews:
            lines.append(f"{rv['symbol']} {rv['name']} +{rv['outcome_pct']}%"
                         f"(第{rv['outcome_day']}日) [{rv['family'] or '综合评分'}]")
            lines.append(f"  复盘: {rv['review'][:120]}")
    if new_outcomes and new_outcomes.get("stopped_drop"):
        lines.append(f"🛑 今日大跌止踪 {new_outcomes['stopped_drop']} 只（不再跟踪）")
    return "\n".join(lines)


def weekly_report(days: int = 7) -> pd.DataFrame:
    """近 N 个信号日的表现矩阵：每信号一行 + day1..day7 涨跌 + 累计。"""
    conn = _conn()
    q = """SELECT s.id, s.date, s.symbol, s.name, s.score, s.strict, s.sector,
                  p.day_n, p.pct_change
           FROM signals s JOIN performance p ON p.signal_id = s.id
           WHERE s.date >= (SELECT MIN(d) FROM (
               SELECT DISTINCT date d FROM signals ORDER BY date DESC LIMIT ?))"""
    df = pd.read_sql(q, conn, params=(days,))
    conn.close()
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot_table(index=["id", "date", "symbol", "name", "score", "strict", "sector"],
                          columns="day_n", values="pct_change").reset_index()
    wide.columns = [f"d{c}" if isinstance(c, (int, float)) else c for c in wide.columns]
    day_cols = [c for c in wide.columns if c.startswith("d") and c[1:].isdigit()]
    wide["cum_pct"] = ((wide[day_cols] / 100 + 1).prod(axis=1, skipna=True) - 1) * 100
    # 连涨天数（从day1起连续>0）
    def streak(row):
        n = 0
        for c in sorted(day_cols, key=lambda x: int(x[1:])):
            v = row[c]
            if pd.notna(v) and v > 0:
                n += 1
            else:
                break
        return n
    wide["streak"] = wide.apply(streak, axis=1)
    return wide.sort_values(["streak", "cum_pct"], ascending=False)


def find_streaks(min_streak: int = 2) -> pd.DataFrame:
    """信号后从第1天起连涨 ≥ min_streak 天的标的（待归因）。"""
    rep = weekly_report()
    if rep.empty:
        return rep
    return rep[rep["streak"] >= min_streak]


def distill_streaks(min_streak: int = 2, use_llm: bool = True) -> dict:
    """对连涨标的做特征归因：
    1. 取其信号日子分数，与全体信号均值对比 → 显著偏高的维度
    2. （可选）DeepSeek 总结共性 → 候选因子中文描述（供 factor_gen 生成）
    3. 标记 ML 强化样本（ml_weight=2.0）写回库
    """
    streaks = find_streaks(min_streak)
    if streaks.empty:
        return {"n": 0, "message": "近一周无连涨≥%d天的信号" % min_streak}

    conn = _conn()
    conn.execute("CREATE TABLE IF NOT EXISTS ml_boost (signal_id INTEGER PRIMARY KEY, weight REAL)")
    all_subs, streak_subs = [], []
    ids = set(streaks["id"].tolist())
    for sid, subs_json in conn.execute("SELECT id, sub_scores FROM signals"):
        subs = json.loads(subs_json or "{}")
        if not subs:
            continue
        all_subs.append(subs)
        if sid in ids:
            streak_subs.append(subs)
            conn.execute("INSERT OR REPLACE INTO ml_boost VALUES(?, 2.0)", (sid,))
    conn.commit()
    conn.close()

    base = pd.DataFrame(all_subs).mean()
    win = pd.DataFrame(streak_subs).mean()
    diff = (win - base).sort_values(ascending=False)
    top_traits = {k: round(float(v), 3) for k, v in diff.head(4).items()}

    result = {"n": len(streaks),
              "symbols": streaks[["symbol", "name", "date", "streak", "cum_pct"]].to_dict("records"),
              "trait_lift": top_traits,
              "ml_boosted": len(streak_subs)}

    if use_llm:
        try:
            from alphapulse.llm.client import chat, is_configured, MODEL_REASONING
            if is_configured():
                prompt = (f"以下A股信号股在选股后连涨≥{min_streak}天。其信号日特征相对全体信号的"
                          f"均值偏移（子分数0-1）：{json.dumps(top_traits, ensure_ascii=False)}。\n"
                          f"个股: {json.dumps(result['symbols'][:10], ensure_ascii=False)}\n"
                          "请总结这批强势股的共性（≤100字），并给出一条可量化的中文选股条件描述"
                          "（将用于自动生成因子，格式如'X大于Y且Z小于W'，只用量价指标）。")
                result["llm_summary"] = chat(prompt, model=MODEL_REASONING, max_tokens=500)
        except Exception as e:
            result["llm_summary"] = f"(LLM归因失败: {e})"
    return result
