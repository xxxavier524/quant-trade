#!/usr/bin/env python3
"""agent team / 四类选股 历史回测验证（用户验收标准，2026-07-02 /goal）。

四项标准（事件定义=用户给定；通过线在报告中明示）：
1. 超短类（知行超短∪量能B1）：信号次日红盘（收盘>前收）
   通过线：红盘率 ≥55% 且 高于全市场基线 ≥5个百分点
2. B1类（B1公式）：信号后3日累计涨幅 >5%
   通过线：命中率 ≥ 2×全市场基线 且 ≥12%
3. 板块判断（rank_sectors 强板块 score≥60）：未来一周内板块指数涨幅 >2%（5日内最大收盘涨幅）
   通过线：命中率 ≥ 1.5×全板块基线 且 ≥35%
4. 研判（agent team 量化核心 团队分）：
   ≥60分（增持+）：5日胜率 ≥55% 且 平均5日收益 > 全市场同期均值（超额>0）
   ≥75分（Buy）：3日胜率 ≥60%
   （辩论层为 LLM 增益，回测验证量化核心；GBDT缺失列按0填充，近似与在线一致）

用法：
    python scripts/backtest_agent_team.py --start 2025-06-01 --sample 800   # 快速抽样
    python scripts/backtest_agent_team.py --start 2025-06-01                # 全市场
输出：reports/agent_team_backtest.md
"""

import argparse
import logging
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from replay_screen import load_stock  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backtest_agent_team")
REPORTS_DIR = PROJECT_ROOT / "reports"

W_FACTOR, W_PATTERN, W_SECTOR = 0.40, 0.35, 0.25   # portfolio_agent 权重


def _load_frames(data_dir: Path, sample: int) -> dict[str, pd.DataFrame]:
    files = sorted(data_dir.glob("*.csv"))
    if sample:
        random.seed(42)
        files = random.sample(files, min(sample, len(files)))
    frames = {}
    for i, f in enumerate(files):
        if i % 1000 == 0 and i:
            logger.info(f"  加载 {i}/{len(files)}")
        df = load_stock(f, "9999-12-31", min_rows=180)
        if df is not None:
            frames[f.stem] = df
    logger.info(f"有效股票 {len(frames)}")
    return frames


def _weekly_dates(frames: dict) -> list[str]:
    """全市场交易日（众数日历）按每5日取样。"""
    dates = sorted({d for df in frames.values() for d in df["date"].tail(400)})
    return dates[::5]


def _macro_by_week(week_dates: list[str]) -> dict[str, tuple[str, float]]:
    from alphapulse.market.market_score import compute_market_score
    out = {}
    for d in week_dates:
        try:
            m = compute_market_score(end_date=d)
            out[d] = (m.get("level", "震荡"), float(m.get("score", 50.0)))
        except Exception:
            out[d] = ("震荡", 50.0)
    return out


def _sector_weekly(frames: dict, week_dates: list[str], start: str):
    """板块周度评分回放 + 标准3统计。返回 (记录df, {sector:{date:score}})。"""
    from alphapulse.market.sector_score import load_members, build_sector_index, _score_sector

    members = load_members()
    recs, score_map = [], {}
    for sector, syms in members.items():
        idx = build_sector_index(syms, frames)
        if idx is None or len(idx) < 140:
            continue
        close = idx["close"].astype(float).reset_index(drop=True)
        dts = idx["date"].astype(str).reset_index(drop=True)
        pos_of = {d: i for i, d in enumerate(dts)}
        smap = {}
        for d in week_dates:
            t = pos_of.get(d)
            if t is None or t < 120:
                continue
            sc = _score_sector(idx.iloc[:t + 1], len(syms))["score"]
            smap[d] = sc
            if d >= start and t + 5 < len(close):
                fwd_path = close.iloc[t + 1:t + 6].values / close.iloc[t] - 1.0
                recs.append({"sector": sector, "date": d, "score": sc,
                             "fwd5_max": float(fwd_path.max()),
                             "fwd5_close": float(fwd_path[-1])})
        score_map[sector] = smap
    return pd.DataFrame(recs), score_map


def _gbdt():
    from alphapulse.ml import pattern_model as pm
    if not pm.MODEL_PATH.exists():
        return None, None
    import joblib, json  # noqa: E401
    model = joblib.load(pm.MODEL_PATH)
    feats = json.loads(pm.META_PATH.read_text())["features"]
    return model, feats


def _stock_pass(sym, df, start, weights, model, feat_cols,
                sector_map, sector_scores_daily, macro_daily):
    """单股向量化：信号系列 + 团队分系列 + 前向收益 → 记录字典。"""
    from alphapulse.factors import b1_formula, volume_b1, zhixing_trend
    from alphapulse.strategies import needle
    from alphapulse.ranking.sub_scores import compute_sub_score_frame
    from alphapulse.ml.pattern_model import feature_frame

    n = len(df)
    dates = df["date"].astype(str).values
    close = df["close"].astype(float)
    fwd1 = (close.shift(-1) / close - 1).values
    fwd3 = (close.shift(-3) / close - 1).values
    fwd5 = (close.shift(-5) / close - 1).values

    def _safe(fn, *a, **k):
        try:
            return fn(*a, **k).fillna(False).values
        except Exception:
            return np.zeros(n, dtype=bool)

    b1 = _safe(b1_formula.compute, df)
    vb1 = _safe(volume_b1.compute, df)
    zx = _safe(zhixing_trend.compute_ultra, df)
    nd = _safe(needle.compute, df)
    # 生产铁律：股价站上知行黄线才进选股（rank_all 默认硬过滤）
    try:
        yellow = zhixing_trend.compute_bull_bear_line(close)
        above = (close > yellow).fillna(False).values
    except Exception:
        above = np.ones(n, dtype=bool)
    ultra = (zx | vb1) & above
    b1 = b1 & above
    nd = nd & above

    subs = compute_sub_score_frame(df)
    if subs.empty:
        return None
    wsum = sum(weights[k] for k in weights if k in subs.columns) or 1.0
    fconf = sum(subs[k].fillna(0) * w for k, w in weights.items()
                if k in subs.columns).values / wsum * 100.0
    strict = b1 | vb1 | zx | nd
    fconf_eff = np.where(strict, np.maximum(fconf, 60.0), fconf)
    f_signed = np.where(strict | (fconf_eff >= 55.0), fconf_eff,
                        np.where(fconf_eff < 35.0, -fconf_eff, 0.0))

    # pattern：近端买点态 + GBDT
    buy = b1 | vb1
    idx_arr = np.arange(n, dtype=float)
    last_buy = pd.Series(np.where(buy, idx_arr, np.nan)).ffill().values
    bars_since = idx_arr - last_buy
    nd_recent = pd.Series(nd).rolling(6, min_periods=1).max().fillna(0).values > 0
    state_bull = (bars_since <= 5) | nd_recent
    ml = None
    if model is not None:
        try:
            X = feature_frame(df).reindex(columns=feat_cols, fill_value=0.0).fillna(0.0)
            ml = model.predict_proba(X)[:, 1]
        except Exception:
            ml = None
    if ml is not None:
        pconf = ml * 100.0
        p_signed = np.where(state_bull & (pconf >= 50.0), pconf,
                            np.where((~state_bull) & (ml < 0.35), -pconf, 0.0))
    else:
        pconf = np.where(state_bull, 60.0, 40.0)
        p_signed = np.where(state_bull, pconf, 0.0)

    # sector：周度分 ffill 到日
    sec = sector_map.get(sym, "")
    ss = sector_scores_daily.get(sec)
    s_signed = np.zeros(n)
    for i, d in enumerate(dates):
        sscore = ss.get(d) if ss else None
        level, mscore = macro_daily.get(d, ("震荡", 50.0))
        bear_macro = "空" in level
        if sscore is not None and sscore >= 60.0 and not bear_macro:
            s_signed[i] = sscore
        elif sscore is not None and sscore < 35.0:
            s_signed[i] = -sscore
        elif bear_macro:
            s_signed[i] = -(sscore if sscore is not None else mscore)

    team = 50.0 + 50.0 * (W_FACTOR * f_signed + W_PATTERN * p_signed
                          + W_SECTOR * s_signed) / 100.0
    team = np.clip(team, 0.0, 100.0)

    m = (dates >= start) & ~np.isnan(fwd5)
    return {"ultra_f1": fwd1[ultra & m & ~np.isnan(fwd1)],
            "b1_f3": fwd3[b1 & m & ~np.isnan(fwd3)],
            "needle_f3": fwd3[nd & m & ~np.isnan(fwd3)],
            "team": team[m], "fwd1": fwd1[m], "fwd3": fwd3[m], "fwd5": fwd5[m],
            "daily": pd.DataFrame({"date": dates[m], "team": team[m],
                                   "fwd3": fwd3[m], "fwd5": fwd5[m]})}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-06-01")
    ap.add_argument("--sample", type=int, default=0, help="抽样股票数(0=全市场)")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        sys.exit(f"数据目录不存在: {data_dir}")

    from alphapulse.ranking.composite import load_weights
    from alphapulse.market.sector_score import symbol_sector_map
    weights = load_weights()
    frames = _load_frames(data_dir, args.sample)
    week_dates = _weekly_dates(frames)
    logger.info(f"周度锚点 {len(week_dates)} 个（{week_dates[0]}~{week_dates[-1]}）")

    macro_weekly = _macro_by_week(week_dates)
    keys = sorted(macro_weekly)

    # 周锚点前向填充：逐日查询取 <= 该日的最近锚点
    class _Daily(dict):
        def get(self, d, default=("震荡", 50.0)):
            import bisect
            j = bisect.bisect_right(keys, d) - 1
            return macro_weekly[keys[j]] if j >= 0 else default
    macro_daily = _Daily()

    logger.info("板块周度回放...")
    sec_df, sec_score_map = _sector_weekly(frames, week_dates, args.start)
    sec_daily = {}
    for sector, smap in sec_score_map.items():
        skeys = sorted(smap)
        class _SD(dict):
            def __init__(self, ks, mp):
                self._k, self._m = ks, mp
            def get(self, d, default=None):
                import bisect
                j = bisect.bisect_right(self._k, d) - 1
                return self._m[self._k[j]] if j >= 0 else default
        sec_daily[sector] = _SD(skeys, smap)
    sector_map = symbol_sector_map()

    model, feat_cols = _gbdt()
    logger.info(f"GBDT模型: {'已加载' if model is not None else '缺失(定性回退)'}")

    acc = {k: [] for k in ("ultra_f1", "b1_f3", "needle_f3", "team",
                           "fwd1", "fwd3", "fwd5", "daily")}
    for i, (sym, df) in enumerate(frames.items()):
        if i % 500 == 0 and i:
            logger.info(f"  逐股回放 {i}/{len(frames)}")
        r = _stock_pass(sym, df, args.start, weights, model, feat_cols,
                        sector_map, sec_daily, macro_daily)
        if r:
            for k, v in r.items():
                acc[k].append(v)
    daily_frames = acc.pop("daily")
    daily_df = (pd.concat(daily_frames, ignore_index=True)
                if daily_frames else pd.DataFrame())
    A = {k: (np.concatenate(v) if v else np.array([])) for k, v in acc.items()}

    # ── 统计四标准 ──
    def pct(x):
        return f"{x*100:.1f}%"

    ultra, b1f3, ndf3 = A["ultra_f1"], A["b1_f3"], A["needle_f3"]
    team, fwd1, fwd3, fwd5 = A["team"], A["fwd1"], A["fwd3"], A["fwd5"]

    c1_rate = float((ultra > 0).mean()) if len(ultra) else float("nan")
    c1_base = float((fwd1[~np.isnan(fwd1)] > 0).mean()) if len(fwd1) else float("nan")
    c2_rate = float((b1f3 > 0.05).mean()) if len(b1f3) else float("nan")
    c2_base = float((fwd3 > 0.05).mean()) if len(fwd3) else float("nan")
    cn_rate = float((ndf3 > 0).mean()) if len(ndf3) else float("nan")

    strong = sec_df[sec_df["score"] >= 60] if not sec_df.empty else pd.DataFrame()
    c3_rate = float((strong["fwd5_max"] > 0.02).mean()) if len(strong) else float("nan")
    c3_base = float((sec_df["fwd5_max"] > 0.02).mean()) if len(sec_df) else float("nan")

    m60 = team >= 60
    m75 = team >= 75
    c4_win5 = float((fwd5[m60] > 0).mean()) if m60.any() else float("nan")
    c4_mean5 = float(np.nanmean(fwd5[m60])) if m60.any() else float("nan")
    mkt_mean5 = float(np.nanmean(fwd5)) if len(fwd5) else float("nan")
    c4_win3_buy = float((fwd3[m75] > 0).mean()) if m75.any() else float("nan")

    # 4c 生产口径：每日团队分排名 Top10（且≥60分）—— 用户实际看到/交易的组合
    top10 = pd.DataFrame()
    if not daily_df.empty:
        pool = daily_df[daily_df["team"] >= 60].copy()
        if not pool.empty:
            pool["rk"] = pool.groupby("date")["team"].rank(ascending=False, method="first")
            top10 = pool[pool["rk"] <= 10]
    c4c_win5 = float((top10["fwd5"] > 0).mean()) if len(top10) else float("nan")
    c4c_mean5 = float(top10["fwd5"].mean()) if len(top10) else float("nan")
    c4c_win3 = float((top10["fwd3"] > 0).mean()) if len(top10) else float("nan")

    p1 = c1_rate >= 0.55 and (c1_rate - c1_base) >= 0.05
    p2 = c2_rate >= max(0.12, 2 * c2_base)
    p3 = c3_rate >= max(0.35, 1.5 * c3_base)
    p4 = (c4_win5 >= 0.55) and (c4_mean5 > mkt_mean5)
    p4b = c4_win3_buy >= 0.60
    p4c = (c4c_win5 >= 0.55) and (c4c_mean5 > mkt_mean5)

    mark = lambda p: "✅ 通过" if p else "❌ 未达标"  # noqa: E731
    dur = (time.monotonic() - t0) / 60
    end_date = max(df["date"].iloc[-1] for df in frames.values())

    md = [f"# Agent Team / 四类选股 回测验证",
          f"\n窗口 {args.start} ~ {end_date} · 股票 {len(frames)} 只"
          f"{'(抽样)' if args.sample else '(全市场)'} · 耗时 {dur:.1f} 分钟\n",
          "| # | 标准（事件=用户定义） | 结果 | 基线 | 通过线 | 判定 |",
          "|---|---|---|---|---|---|",
          f"| 1 | 超短信号次日红盘 | **{pct(c1_rate)}** ({len(ultra)}信号) "
          f"| 全市场日红盘≈{pct(c1_base)} | ≥55% 且 ≥基线+5pp | {mark(p1)} |",
          f"| 2 | B1后3日累计涨幅>5% | **{pct(c2_rate)}** ({len(b1f3)}信号) "
          f"| 全市场3日>5%={pct(c2_base)} | ≥2×基线 且 ≥12% | {mark(p2)} |",
          f"| 3 | 强板块(≥60分)一周内涨幅>2% | **{pct(c3_rate)}** ({len(strong)}板块周) "
          f"| 全板块={pct(c3_base)} | ≥1.5×基线 且 ≥35% | {mark(p3)} |",
          f"| 4a | 研判≥60分:5日胜率 | **{pct(c4_win5)}** ({int(m60.sum())}股日) "
          f"| 市场5日均值{pct(mkt_mean5)} vs 组合{pct(c4_mean5)} "
          f"| 胜率≥55%且超额>0 | {mark(p4)} |",
          f"| 4b | 研判≥75分(Buy):3日胜率 | **{pct(c4_win3_buy)}** ({int(m75.sum())}股日) "
          f"| — | ≥60% | {mark(p4b)} |",
          f"| 4c | 每日Top10(≥60分,生产口径):5日胜率 | **{pct(c4c_win5)}** ({len(top10)}股日,"
          f"3日胜率{pct(c4c_win3)}) | 组合均值{pct(c4c_mean5)} vs 市场{pct(mkt_mean5)} "
          f"| 胜率≥55%且超额>0 | {mark(p4c)} |",
          f"\n附:单针下三十 3日正收益率 {pct(cn_rate)}（{len(ndf3)}信号,样本参考）",
          "\n> 口径说明：信号日收盘买入；红盘=次日收盘>信号日收盘；"
          "超短/B1/单针信号均已叠加生产铁律『股价站上知行黄线』硬过滤（与选股工作台一致）；"
          "板块一周=未来5交易日最大收盘涨幅；研判分=P0量化核心(因子.40/形态.35/板块.25)，"
          "板块/大盘按周锚点前向填充；GBDT批量预测缺失值填0（与在线单点预测近似）。"]
    out = REPORTS_DIR / "agent_team_backtest.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    logger.info(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
