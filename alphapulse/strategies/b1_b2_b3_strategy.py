"""AlphaPulse-A B1->B2->B3 递进战法（基于B1选股公式）。

三阶段递进逻辑：
  B1（底部挖掘）: b1_formula (80%权重) + volume_b1 (20%增强)
                 过滤: N_STRUCT=0（因果版标签，近乎惰性）+ 近10日振幅<15%
  B2（确认信号）: B1后5日内，阳线涨幅>3% + 成交量>前日2倍 + 收盘>白线
  B3（锁仓信号）: B2后3日内，阳线缩量<前日0.7 + 收盘>前日 + 最低>=B2收盘

核心原则：
  - B1选股公式(b1_formula.py)是决定性因素，占80%权重
  - 量能B1(volume_b1.py)作为增强条件，叠加时置信度从0.6提升到0.8
  - N_STRUCT=0（因果版）：枢轴日标签按确认日公布，避免追高语义的因果近似
  - 近10日振幅<15%排除剧烈波动股

因子依赖：
  b1_formula (主信号，80%权重), volume_b1 (增强信号，+20%),
  n_struct (N型结构过滤), zhixing_trend (白线), violent_kline (B2暴力K增强)
"""

import pandas as pd
import numpy as np

from alphapulse.factors.b1_formula import compute as b1_compute
from alphapulse.factors.volume_b1 import compute as vol_b1_compute
from alphapulse.factors.zhixing_trend import compute_short_trend
from alphapulse.factors.n_struct import compute_causal
from alphapulse.factors.violent_kline import compute as violent_kline_compute


def _empty_result() -> pd.DataFrame:
    """返回空的信号DataFrame（统一schema）。"""
    return pd.DataFrame(columns=[
        "symbol", "date", "signal", "strategy",
        "signal_type", "confidence", "factor_snapshot",
        "seq_id", "parent_stage", "seq_root_date",
    ])


def assign_seq_ids(
    b1_sig: "pd.Series", b2_sig: "pd.Series", b3_sig: "pd.Series",
    symbol: str, b2_window: int = 5, b3_window: int = 3,
) -> dict:
    """把 B1/B2/B3 布尔序列串成链路（因果单次线性扫描，只用 ≤t 信息）。

    语义与 playbook_engine.simulate_b1b2b3 一致：一 B1 → 首个窗口内 B2 → 首个窗口内 B3。

    Returns:
        dict: (date_str, stage) -> {seq_id, parent_stage, seq_root_date}
              stage ∈ {"B1","B2","B3"}。按 (日期, 阶段) 键，因一日可同时是某链的 B2
              与新链的 B1（各出一行）。孤立 B1 的 seq 只含自身。
    """
    dates = [str(d) for d in b1_sig.index]
    b1v = b1_sig.fillna(False).to_numpy(dtype=bool)
    b2v = b2_sig.fillna(False).to_numpy(dtype=bool)
    b3v = b3_sig.fillna(False).to_numpy(dtype=bool)

    meta: dict[tuple, dict] = {}
    pending_b1 = None   # (seq_id, root_date, b1_i)
    pending_b2 = None   # (seq_id, root_date, b2_i)
    for i, d in enumerate(dates):
        # B3 归属：最近的、在 b3_window 内、尚未接 B3 的 B2
        if b3v[i] and pending_b2 is not None and 1 <= i - pending_b2[2] <= b3_window:
            meta[(d, "B3")] = {"seq_id": pending_b2[0], "parent_stage": "B2",
                               "seq_root_date": pending_b2[1]}
            pending_b2 = None
        # B2 归属：最近的、在 b2_window 内、尚未接 B2 的 B1
        if b2v[i] and pending_b1 is not None and 1 <= i - pending_b1[2] <= b2_window:
            meta[(d, "B2")] = {"seq_id": pending_b1[0], "parent_stage": "B1",
                               "seq_root_date": pending_b1[1]}
            pending_b2 = (pending_b1[0], pending_b1[1], i)
            pending_b1 = None
        # B1 开新序列（新 B1 覆盖旧的未确认 B1 = 取最近）
        if b1v[i]:
            seq_id = f"{symbol}:{d}"
            meta[(d, "B1")] = {"seq_id": seq_id, "parent_stage": None,
                               "seq_root_date": d}
            pending_b1 = (seq_id, d, i)
    return meta


def generate_signals(
    data: pd.DataFrame,
    symbol: str = "",
    **params,
) -> pd.DataFrame:
    """生成 B1->B2->B3 递进战法信号。

    B1 入场逻辑（b1_formula 80%权重 + volume_b1 20%权重）:
      - 主信号: b1_formula.compute() 触发（cond1~cond6全部满足，决定性因素）
      - 增强信号: volume_b1.compute() 同时触发 → 置信度 +0.2
      - 过滤条件: N_STRUCT=0（因果版：枢轴标签按确认日公布，详见代码注释）
      - 过滤条件: 近10日振幅<15%（排除剧烈波动）
      - 置信度: b1_formula单独=0.6，量能B1叠加=0.8

    B2 确认逻辑（B1后5日内）:
      - 阳线涨幅>3% + 成交量>前日2倍 + 收盘>白线
      - 暴力K触发 = 增强（置信度 0.75→0.85）
      - 参数参考b1_formula cond1(涨幅±3%)和cond2(振幅<9%)

    B3 锁定逻辑（B2后3日内）:
      - 阳线 + 缩量(<前日0.7) + 收盘>前日 + 最低≥B2收盘
      - 参考volume_b1的half_down缩量逻辑
      - B3=主力锁仓，confidence最高0.9

    Args:
        data: 日线OHLCV DataFrame，index=date，
              列需包含 open/high/low/close/volume
              可选: market_cap, pct_change, amplitude
        symbol: 股票代码
        **params: 参数覆盖，传递给b1_formula（如pct_change_range, j_threshold等）

    Returns:
        pd.DataFrame，index=date，列：
        - symbol: 股票代码
        - date: 信号日期（设为index）
        - signal: 1（买入）
        - strategy: "B1_B2_B3"
        - signal_type: "B1" | "B2" | "B3"
        - confidence: 0.6(B1) / 0.8(B1+量能) / 0.75(B2) / 0.85(B2增强) / 0.9(B3)
        - factor_snapshot: dict，各阶段关键快照值
    """
    n = len(data)
    if n < 120:
        return _empty_result()

    close = data["close"]
    open_ = data["open"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    # ---- 白线 = EMA(EMA(C,10),10) 知行短期趋势线 ----
    white_line = compute_short_trend(close)

    # ============================================================
    # B1 底部挖掘信号（b1_formula 80%权重决定，volume_b1 20%增强）
    # ============================================================

    # 主信号 (80%权重): b1_formula 6条件AND -- 决定性因素
    # 过滤仅传给 b1_compute 的参数
    _b1_keys = {"pct_change_range", "amplitude_max", "j_threshold",
                "dif_threshold", "m1", "m2", "m3", "m4"}
    _b1_params = {k: v for k, v in params.items() if k in _b1_keys}
    b1_main = b1_compute(data, **_b1_params)

    # 增强信号 (20%权重): volume_b1 量能体系 -- 增强信心但不强制
    b1_vol = vol_b1_compute(data)

    # -- 过滤条件1: N_STRUCT = 0（不能已有N型上涨结构）--
    # v5 因果化（2026-08-02）：旧版 ns_label = n_struct.compute(data) 的枢轴标签
    # 需要未来 min_leg_len 根K线确认——在信号日使用它是未来函数。compute_causal
    # 把标签放在"枢轴确认日"，此处 isna() 只反映 ≤t 已确认的枢轴。
    # 注意：该过滤是"当日非枢轴日"的因果近似，天然近乎惰性；真正语义
    # "已走完N型再上升段则禁买（避免追高）"留待 v5 策略重做时用 phase3 窗口验证。
    ns_ctx = compute_causal(data)
    no_n_struct = ns_ctx["label"].isna()

    # -- 过滤条件2: 近10日振幅 < 15%（排除剧烈波动）--
    amp_10d = (high.rolling(10).max() / low.rolling(10).min() - 1)
    amp_ok = amp_10d < 0.15

    # B1 信号 = 原始b1_formula触发 + 过滤条件
    b1_signal = b1_main & no_n_struct & amp_ok
    b1_signal = b1_signal.fillna(False).astype(bool)

    # 量能B1叠加标记（用于置信度提升）
    b1_vol_on_signal = b1_signal & b1_vol.fillna(False)

    # ============================================================
    # B2 确认信号（B1后5日内）
    # ============================================================

    # B1信号前推窗口：过去1~5个交易日内有B1
    b1_int = b1_signal.astype(int)
    in_b2_window = b1_int.shift(1).rolling(5, min_periods=1).sum().fillna(0) > 0

    # B2条件: 阳线涨幅>3% + 成交量>前日2倍 + 收盘>白线
    #  可参数化: vol_mult_b2 (放量倍数), yang_pct_b2 (涨幅阈值)
    vol_mult_b2 = params.get("vol_mult_b2", 2.0)
    yang_pct_b2 = params.get("yang_pct_b2", 0.03)
    yang_big = (close > open_) & (close.pct_change() > yang_pct_b2)
    # 成交量>前日N倍参考b1_formula的放量逻辑
    vol_double = volume > (volume.shift(1) * vol_mult_b2)
    above_white = close > white_line
    b2_conditions = yang_big & vol_double & above_white

    b2_signal = in_b2_window & b2_conditions
    b2_signal = b2_signal.fillna(False).astype(bool)

    # B2增强: 暴力K触发 → 置信度从0.75提升到0.85
    violent = violent_kline_compute(data)
    b2_enhanced = b2_signal & violent.fillna(False)

    # ============================================================
    # B3 锁定信号（B2后3日内）
    # ============================================================

    # B2信号前推窗口：过去1~3个交易日内有B2
    b2_int = b2_signal.astype(int)
    in_b3_window = b2_int.shift(1).rolling(3, min_periods=1).sum().fillna(0) > 0

    # B3条件: 阳线 + 缩量(<前日0.7) + 收盘>前日 + 最低>=B2日收盘
    # 缩量<前日0.7参考volume_b1 half_down逻辑
    yang_line = close > open_
    vol_shrink = volume < (volume.shift(1) * 0.7)
    close_up = close > close.shift(1)

    # 最低不破B2收盘：主仓锁仓特征（参考volume_b1的half_down缩量）
    last_b2_close = close.where(b2_signal).ffill()
    low_above_b2 = low >= last_b2_close

    b3_signal = in_b3_window & yang_line & vol_shrink & close_up & low_above_b2
    b3_signal = b3_signal.fillna(False).astype(bool)

    # ============================================================
    # 构建输出
    # ============================================================

    pct_change = close.pct_change()
    vol_ratio = volume / volume.shift(1)
    last_b2_close_filled = close.where(b2_signal).ffill()

    # ---- seq_id 链路贯穿（B2→B1、B3→B2；因果单次扫描，路线图#4）----
    seq_meta = assign_seq_ids(
        b1_signal, b2_signal, b3_signal, symbol,
        b2_window=5, b3_window=3)

    def _seq(dt, stage):
        m = seq_meta.get((str(dt), stage),
                         {"seq_id": None, "parent_stage": None, "seq_root_date": None})
        return m

    # 置信度阈值过滤（可通过params覆盖）
    min_conf_b1 = params.get("min_conf_b1", 0.0)
    min_conf_b2 = params.get("min_conf_b2", 0.0)
    min_conf_b3 = params.get("min_conf_b3", 0.0)

    results = []

    # B1 signals
    for dt in data.index[b1_signal]:
        with_vol = bool(b1_vol_on_signal.loc[dt]) if dt in b1_vol_on_signal.index else False
        conf = 0.8 if with_vol else 0.6
        if conf < min_conf_b1:
            continue
        s = _seq(dt, "B1")
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1_B2_B3",
            "signal_type": "B1",
            "confidence": conf,
            "factor_snapshot": {
                "close": float(close[dt]),
                "white_line": float(white_line[dt]) if pd.notna(white_line[dt]) else None,
                "b1_main": True,
                "volume_b1_enhanced": with_vol,
                "no_n_struct": bool(no_n_struct[dt]),
                "amp_10d_ok": bool(amp_ok[dt]),
            },
            "seq_id": s["seq_id"], "parent_stage": s["parent_stage"],
            "seq_root_date": s["seq_root_date"],
        })

    # B2 signals
    for dt in data.index[b2_signal]:
        conf = 0.85 if bool(b2_enhanced.loc[dt]) else 0.75
        if conf < min_conf_b2:
            continue
        s = _seq(dt, "B2")
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1_B2_B3",
            "signal_type": "B2",
            "confidence": conf,
            "factor_snapshot": {
                "close": float(close[dt]),
                "pct_change": float(pct_change[dt]) if pd.notna(pct_change[dt]) else None,
                "vol_ratio_to_prev": float(vol_ratio[dt]) if pd.notna(vol_ratio[dt]) else None,
                "white_line": float(white_line[dt]) if pd.notna(white_line[dt]) else None,
                "violent_k": bool(b2_enhanced.loc[dt]) if dt in b2_enhanced.index else False,
            },
            "seq_id": s["seq_id"], "parent_stage": s["parent_stage"],
            "seq_root_date": s["seq_root_date"],
        })

    # B3 signals
    for dt in data.index[b3_signal]:
        conf = 0.9  # B3 base confidence
        if conf < min_conf_b3:
            continue
        b2c = float(last_b2_close_filled[dt]) if pd.notna(last_b2_close_filled[dt]) else None
        s = _seq(dt, "B3")
        results.append({
            "symbol": symbol,
            "date": dt,
            "signal": 1,
            "strategy": "B1_B2_B3",
            "signal_type": "B3",
            "confidence": 0.9,
            "factor_snapshot": {
                "close": float(close[dt]),
                "prev_close": float(close.shift(1)[dt]) if pd.notna(close.shift(1)[dt]) else None,
                "vol_shrink_ratio": float(vol_ratio[dt]) if pd.notna(vol_ratio[dt]) else None,
                "low": float(low[dt]),
                "b2_close_ref": b2c,
                "locked": True,
            },
            "seq_id": s["seq_id"], "parent_stage": s["parent_stage"],
            "seq_root_date": s["seq_root_date"],
        })

    if not results:
        return _empty_result()
    return pd.DataFrame(results).set_index("date").sort_index()
