"""信号追踪与因子沉淀 — 用户闭环：选股 → 跟踪7日 → 连涨归因 → 沉淀。

流程（用户确认需求 2026-06-11）：
1. record_signals: 每日 screen Top50 写入 tracking 库（sqlite）
2. update_performance: 用日线数据回填每个信号后 1-7 日逐日涨跌
3. find_streaks: 找出"信号后连涨≥2天"的标的
4. distill: 对连涨标的提取信号日特征共性 → DeepSeek 总结 →
   产出候选因子描述（接 factor_gen）+ 标记为 ML 强化样本（样本权重加倍）

存储：backtest_results/signal_tracking.db
  signals(id, date, symbol, name, score, strict, sector, close, sub_scores_json)
  performance(signal_id, day_n, date, close, pct_change)
"""

import json
import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "backtest_results" / "signal_tracking.db"

SUB_COLS = ["j_low", "trend_gap", "vol_shrink", "yangyin", "surge", "dif",
            "ql_pos", "pct_calm", "amplitude", "bowl", "washout_recover"]


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
    return conn


def record_signals(screen_csv: Path) -> int:
    """把一份 screen_*.csv 的信号写入追踪库（幂等）。"""
    df = pd.read_csv(screen_csv, dtype={"symbol": str})
    date = screen_csv.stem.replace("screen_", "")
    conn = _conn()
    n = 0
    for _, r in df.iterrows():
        subs = {c: float(r[c]) for c in SUB_COLS if c in df.columns and pd.notna(r.get(c))}
        try:
            conn.execute(
                "INSERT OR IGNORE INTO signals(date,symbol,name,score,strict,sector,close,sub_scores) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (date, str(r["symbol"]).zfill(6), str(r.get("name", "")),
                 float(r["score"]), int(bool(r.get("strict_signal", False))),
                 str(r.get("sector", "")), float(r.get("close", 0)), json.dumps(subs)))
            n += conn.execute("SELECT changes()").fetchone()[0]
        except Exception:
            continue
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
