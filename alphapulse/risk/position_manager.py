"""AlphaPulse-A PositionManager -- 仓位管理与风控综合判断。

职责：
  - 入场限制（仓位上限、单票上限、整手计算）
  - 动态止损检查
  - 放飞减仓检查
  - S1 清仓 / 假阴真阳减仓
  - DD 减仓 / DD增强清仓
  - 趋势线跌破确认
  - 5种出货方式检测
  - 主力资金判断
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional


# ---- 常量 ----
LOT_SIZE = 100          # A股整手
MAX_SINGLE_PCT = 0.20   # 单票≤20%总资金
B3_BONUS_PCT = 0.25     # B3信号可加仓至25%
TICK_SIZE = 0.01
TICK_OFFSET = 3


class PositionManager:
    """AlphaPulse-A 仓位管理器。

    维护所有持仓的状态，提供入场/风控/出货检测的综合判断接口。
    """

    def __init__(self, total_capital: float = 1e6):
        """初始化。

        Args:
            total_capital: 总资金，默认100万。
        """
        self.capital = total_capital
        self.positions: Dict[str, Dict[str, Any]] = {}
        self._pending_trendline: Dict[str, Dict[str, Any]] = {}

    # ===================================================================
    # 入场控制
    # ===================================================================

    def can_enter(
        self,
        symbol: str,
        signal_data: Dict[str, Any],
        price: float,
        signal_confidence: float = 1.0,
        max_holdings: int = 5,
    ) -> Dict[str, Any]:
        """检查能否买入。

        Args:
            symbol: 股票代码
            signal_data: 信号数据，含 signal_type (B1/B2/B3 等)
            price: 当前价格
            signal_confidence: 信号置信度 (0-1)，预留扩展
            max_holdings: 最大持仓数

        Returns:
            {can_buy: bool, shares: int, reason: str}
        """
        # --- 持仓数量上限 ---
        if len(self.positions) >= max_holdings:
            return {"can_buy": False, "shares": 0,
                    "reason": f"持仓数已达上限 {max_holdings} 只"}

        # --- 单票上限 ---
        signal_type = signal_data.get("signal_type", "B1")
        max_pct = MAX_SINGLE_PCT
        if signal_type == "B3":
            max_pct = B3_BONUS_PCT

        max_amount = self.capital * max_pct

        # 如果已有该票持仓，检查加仓后是否超限
        existing = self.positions.get(symbol)
        if existing:
            current_value = existing["shares"] * price
            if current_value >= max_amount:
                return {"can_buy": False, "shares": 0,
                        "reason": f"单票已达上限 {max_pct*100:.0f}%"}
            remaining = max_amount - current_value
        else:
            remaining = max_amount

        # --- 整手计算 ---
        raw_shares = int(remaining / price)
        shares = (raw_shares // LOT_SIZE) * LOT_SIZE

        if shares <= 0:
            return {"can_buy": False, "shares": 0,
                    "reason": "资金不足以买入整手(100股)"}

        return {"can_buy": True, "shares": shares,
                "reason": f"可买入 {shares} 股 (占比 {shares*price/self.capital*100:.1f}%)"}

    # ===================================================================
    # 止损检查
    # ===================================================================

    def check_stop_loss(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """动态止损检查。

        止损价 = min(入场日最低价-3价位, N型结构低点-3价位)
        当前价 <= 止损价时触发卖出。

        Args:
            symbol: 股票代码
            data: 含 OHLCV 列的 DataFrame，index 为日期

        Returns:
            {should_sell: bool, reason: str, stop_price: float}
        """
        from alphapulse.factors.dynamic_stop_loss import compute as compute_stop

        pos = self.positions.get(symbol)
        if not pos:
            return {"should_sell": False, "reason": "无持仓", "stop_price": 0.0}

        stop_price = compute_stop(
            data=data,
            entry_date=pos["entry_date"],
            entry_price=pos["entry_price"],
            n_pattern_low=pos.get("n_pattern_low"),
        )

        current_close = float(data["close"].iloc[-1])

        if current_close <= stop_price:
            return {"should_sell": True, "stop_price": stop_price,
                    "reason": f"触发动态止损 (当前价 {current_close:.2f} <= 止损价 {stop_price:.2f})"}
        return {"should_sell": False, "stop_price": stop_price,
                "reason": ""}

    # ===================================================================
    # 放飞减仓
    # ===================================================================

    def check_fly_away(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """放飞减仓检查。

        触发条件（全部 shift(1) 防未来函数）：
          1. 连续2根涨幅>3%阳线 → 减仓 1/4
          2. 连续3根涨幅>3%阳线 → 减仓 1/3
          3. 白线上方加速(涨幅>5%) → 减仓 1/2
          4. 砖型图连续红砖第4块 → 减仓 1/3
        多条同时触发取最大比例。

        Args:
            symbol: 股票代码
            data: 含 OHLCV 列的 DataFrame

        Returns:
            {should_reduce: bool, ratio: float, reason: str}
        """
        from alphapulse.factors.fly_away import compute as fly_compute

        pos = self.positions.get(symbol)
        if not pos:
            return {"should_reduce": False, "ratio": 0.0, "reason": "无持仓"}

        result = fly_compute(data)
        last = result.iloc[-1]

        ratio = float(last["reduce_ratio"])
        if ratio > 0:
            return {"should_reduce": True, "ratio": ratio,
                    "reason": str(last["reason"])}
        return {"should_reduce": False, "ratio": 0.0, "reason": ""}

    # ===================================================================
    # S1 清仓
    # ===================================================================

    def check_s1(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """S1 清仓检查。

        S1(level=1) → 清仓
        假阴真阳S1(level=2) → 减仓50%

        Args:
            symbol: 股票代码
            data: 含 OHLCV 列的 DataFrame

        Returns:
            {should_sell: bool, reason: str, urgency: str, action: str}
        """
        from alphapulse.factors.s1_sell_signal import compute as s1_check

        pos = self.positions.get(symbol)
        if not pos:
            return {"should_sell": False, "reason": "无持仓",
                    "urgency": "", "action": ""}

        result = s1_check(data)
        last_val = int(result.iloc[-1])

        if last_val == 1:
            return {"should_sell": True, "reason": "S1卖出信号：波段高点放巨量阴线",
                    "urgency": "high", "action": "clear"}
        elif last_val == 2:
            return {"should_sell": True, "reason": "假阴真阳S1：放量阴线但收盘高于前日",
                    "urgency": "medium", "action": "reduce_50"}
        return {"should_sell": False, "reason": "",
                "urgency": "", "action": ""}

    # ===================================================================
    # DD 减仓 / 清仓
    # ===================================================================

    def check_dd(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """DD 检查。

        DD(level=1) → 减仓50%
        DD增强(level=2) → 全清

        Args:
            symbol: 股票代码
            data: 含 close/low 列的 DataFrame

        Returns:
            {should_sell: bool, ratio: float, reason: str}
        """
        from alphapulse.factors.dd_sell_signal import compute as dd_check

        pos = self.positions.get(symbol)
        if not pos:
            return {"should_sell": False, "ratio": 0.0, "reason": "无持仓"}

        result = dd_check(data)
        last_val = int(result.iloc[-1])

        if last_val == 2:
            return {"should_sell": True, "ratio": 1.0,
                    "reason": "DD增强卖出：连续2日收盘<前日最低价，全清"}
        elif last_val == 1:
            return {"should_sell": True, "ratio": 0.5,
                    "reason": "DD卖出：收盘<前日最低价，减仓50%"}
        return {"should_sell": False, "ratio": 0.0, "reason": ""}

    # ===================================================================
    # 趋势线跌破检查
    # ===================================================================

    def check_trendline(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """趋势线跌破检查。

        规则：
          - 跌破白线/黄线 → 等1天 → 不站上 → 清仓
          - 击穿对手盘(缩量跌破黄线) → 等1天 → 收不回 → 卖

        使用 self._pending_trendline 跟踪跨日状态。

        Args:
            symbol: 股票代码
            data: 含 close 列的 DataFrame，index 为日期

        Returns:
            {should_sell: bool, reason: str, pending: bool}
        """
        from alphapulse.factors.trendline_break import compute as trend_check
        from alphapulse.factors.zhixing_trend import (
            compute_short_trend,
            compute_bull_bear_line,
        )

        pos = self.positions.get(symbol)
        if not pos:
            return {"should_sell": False, "reason": "无持仓", "pending": False}

        close = data["close"].astype(float)
        volume = data["volume"].astype(float)
        white_line = compute_short_trend(close)
        yellow_line = compute_bull_bear_line(close)
        signals = trend_check(data)

        last_close = float(close.iloc[-1])
        last_white = float(white_line.iloc[-1])
        last_yellow = float(yellow_line.iloc[-1])

        # --- 处理 pending 状态：上一日触发了跌破，今日确认 ---
        pending = self._pending_trendline.pop(symbol, None)
        if pending:
            ptype = pending["type"]
            if ptype in ("white", "counterpart"):
                line_val = last_white
                line_name = "白线"
            else:
                line_val = last_yellow
                line_name = "黄线"

            if last_close >= line_val:
                return {"should_sell": False,
                        "reason": f"跌破{line_name}后1日站回，假跌破解除",
                        "pending": False}
            else:
                return {"should_sell": True,
                        "reason": f"跌破{line_name}后1日未站回 (收盘{last_close:.2f}<{line_name}{line_val:.2f})，清仓",
                        "pending": False}

        # --- 检测新的跌破信号 ---
        last_sig = signals.iloc[-1]
        prev_close = float(close.iloc[-2])
        prev_white = float(white_line.iloc[-2])
        prev_yellow = float(yellow_line.iloc[-2])

        # 白线跌破检测（当日未用shift(1)，用前日收盘对比前日白线）
        if last_sig["break_white"]:
            # 对手盘检测：跌破日缩量
            prev_vol = float(volume.iloc[-2])
            vol_ma20 = float(volume.iloc[-22:-2].mean()) if len(volume) >= 22 else prev_vol
            is_shrink = prev_vol < vol_ma20 * 0.7

            if is_shrink:
                self._pending_trendline[symbol] = {"type": "counterpart"}
                return {"should_sell": False,
                        "reason": "缩量击穿白线对手盘，等待1日确认",
                        "pending": True}
            else:
                self._pending_trendline[symbol] = {"type": "white"}
                return {"should_sell": False,
                        "reason": "跌破白线，等待1日确认",
                        "pending": True}

        # 黄线跌破检测
        if last_sig["break_yellow"]:
            self._pending_trendline[symbol] = {"type": "yellow"}
            return {"should_sell": False,
                    "reason": "跌破黄线，等待1日确认",
                    "pending": True}

        return {"should_sell": False, "reason": "", "pending": False}

    # ===================================================================
    # 5种出货方式检测
    # ===================================================================

    def detect_distribution(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """5种出货方式检测。

        方式1: S1信号（波段最高点放巨量阴线）
        方式2: 次高点放量（局部高点低于历史最高，但成交量放大）
        方式3: 新高阶梯放量（新高伴随逐级放大的成交量）
        方式4: 双头（两个相近高点，中间有低点）
        方式5: 顶部阴量 > 阳量（近期顶部区域阴线成交量超过阳线）

        Args:
            data: 含 OHLCV 的 DataFrame，index 为日期

        Returns:
            list of {type: int, date: str, confidence: float}
        """
        from alphapulse.factors.s1_sell_signal import compute as s1

        results: List[Dict[str, Any]] = []
        close = data["close"].astype(float)
        high = data["high"].astype(float)
        volume = data["volume"].astype(float)
        n = len(data)
        if n < 30:
            return results

        # ---- 方式1: S1信号 ----
        s1_result = s1(data)
        s1_dates = s1_result[s1_result >= 1].index
        for d in s1_dates:
            conf = 0.85 if s1_result.loc[d] == 1 else 0.60
            results.append({"type": 1, "date": str(d.date()),
                            "confidence": conf})

        # ---- 方式2: 次高点放量 ----
        # 找历史最高价位置，在之后找次高点（低于最高），成交量放大
        ath_pos = int(high.values.argmax())
        post_ath = data.iloc[ath_pos + 1:]
        if len(post_ath) >= 5:
            post_high = post_ath["high"].astype(float)
            post_vol = post_ath["volume"].astype(float)
            # 找次高点：局部极大值且低于ATH
            from scipy.signal import argrelextrema
            try:
                local_max_idx = argrelextrema(post_high.values, np.greater, order=3)[0]
                for lm in local_max_idx:
                    if post_high.iloc[lm] < high.iloc[ath_pos] * 0.98:
                        vol_ratio = float(post_vol.iloc[lm] / volume.iloc[ath_pos])
                        if vol_ratio > 1.2:
                            conf = min(0.5 + vol_ratio * 0.15, 0.85)
                            results.append({
                                "type": 2,
                                "date": str(post_high.index[lm].date()),
                                "confidence": round(conf, 2),
                            })
            except ImportError:
                pass

        # ---- 方式3: 新高阶梯放量 ----
        # 找连续创新高的波段，成交量逐级放大
        rolling_max = high.expanding().max()
        is_new_high = high >= rolling_max.shift(1)
        # 检测连续新高且成交量递增
        i = 20
        while i < n:
            if is_new_high.iloc[i]:
                segment_vols = []
                segment_dates = []
                j = i
                while j < n and is_new_high.iloc[j] and (j - i) < 5:
                    segment_vols.append(float(volume.iloc[j]))
                    segment_dates.append(data.index[j])
                    j += 1
                if len(segment_vols) >= 3:
                    # 检查是否逐级放大
                    increasing = all(
                        segment_vols[k] > segment_vols[k-1] * 0.95
                        for k in range(1, len(segment_vols))
                    )
                    if increasing:
                        conf = 0.55 + len(segment_vols) * 0.05
                        results.append({
                            "type": 3,
                            "date": str(segment_dates[-1].date()),
                            "confidence": round(min(conf, 0.80), 2),
                        })
                i = j
            else:
                i += 1

        # ---- 方式4: 双头 ----
        # 两个相近高点（价差 < 3%），中间有 >= 5% 的回调
        window = min(n, 60)
        recent_high = high.iloc[-window:]
        if len(recent_high) >= 10:
            try:
                from scipy.signal import argrelextrema
                peaks = argrelextrema(recent_high.values, np.greater, order=3)[0]
                for p in range(len(peaks)):
                    for q in range(p + 1, len(peaks)):
                        p_idx, q_idx = peaks[p], peaks[q]
                        p_val = float(recent_high.iloc[p_idx])
                        q_val = float(recent_high.iloc[q_idx])
                        if abs(p_val - q_val) / max(p_val, q_val) < 0.03:
                            between_low = float(high.iloc[-window:].iloc[p_idx:q_idx+1].min())
                            drawdown = (max(p_val, q_val) - between_low) / max(p_val, q_val)
                            if drawdown >= 0.05:
                                results.append({
                                    "type": 4,
                                    "date": str(recent_high.index[q_idx].date()),
                                    "confidence": round(0.55 + drawdown, 2),
                                })
            except ImportError:
                pass

        # ---- 方式5: 顶部阴量 > 阳量 ----
        # 找到近期高点附近的区域，比较阴阳成交量
        ath_pos_alltime = int(high.values.argmax())
        if ath_pos_alltime < n - 5:
            top_zone = data.iloc[ath_pos_alltime:]
        else:
            top_zone = data.iloc[-20:]
        top_close = top_zone["close"].astype(float)
        top_open = top_zone["open"].astype(float)
        top_vol = top_zone["volume"].astype(float)

        is_yang = top_close > top_open
        yang_vol = top_vol[is_yang].sum()
        yin_vol = top_vol[~is_yang].sum()

        if yang_vol > 0 and yin_vol > yang_vol:
            conf = min(0.50 + (yin_vol / yang_vol - 1) * 0.2, 0.80)
            results.append({
                "type": 5,
                "date": str(top_zone.index[-1].date()),
                "confidence": round(conf, 2),
            })

        return results

    # ===================================================================
    # 主力资金判断
    # ===================================================================

    def check_main_capital(
        self, data: pd.DataFrame, lookback: int = 60
    ) -> Dict[str, Any]:
        """主力资金判断。

        规则：
          - 跌破黄线次数 > 3（在lookback内）→ 弱，主力不在
          - 放量加速跌破黄线 → 主力不在
          - 持续考验黄线不破 → 主力在

        Args:
            data: 含 close/volume 列的 DataFrame
            lookback: 回溯窗口

        Returns:
            {controlling: bool, reason: str, break_count: int}
        """
        from alphapulse.factors.zhixing_trend import compute_bull_bear_line

        close = data["close"].astype(float)
        volume = data["volume"].astype(float)
        yellow_line = compute_bull_bear_line(close)

        n = len(data)
        if n < lookback:
            return {"controlling": False, "reason": "数据不足", "break_count": 0}

        recent_close = close.iloc[-lookback:]
        recent_yellow = yellow_line.iloc[-lookback:]
        recent_vol = volume.iloc[-lookback:]

        # 统计跌破黄线次数（收盘 < 黄线，且前一日收盘 >= 黄线）
        below = recent_close < recent_yellow
        prev_above = recent_close.shift(1) >= recent_yellow.shift(1)
        breaks = below & prev_above
        break_count = int(breaks.sum())

        # 判断逻辑
        if break_count > 3:
            return {"controlling": False, "break_count": break_count,
                    "reason": f"近{lookback}日跌破黄线{break_count}次(>3)，主力不在"}

        # 检查放量加速跌破
        if break_count >= 1:
            break_indices = breaks[breaks].index
            for bi in break_indices:
                pos_idx = recent_close.index.get_loc(bi)
                if pos_idx >= 1:
                    break_vol = float(recent_vol.iloc[pos_idx])
                    prev_vol = float(recent_vol.iloc[pos_idx - 1])
                    if break_vol > prev_vol * 1.5:
                        return {"controlling": False, "break_count": break_count,
                                "reason": f"放量加速跌破黄线(量比{break_vol/prev_vol:.1f}x)，主力不在"}

        # 持续考验但不破：在黄线附近多次触碰但不跌破
        near_yellow = abs(recent_close - recent_yellow) / recent_yellow < 0.02
        touch_count = int(near_yellow.sum())
        if touch_count >= 5 and break_count <= 2:
            return {"controlling": True, "break_count": break_count,
                    "reason": f"多次考验黄线未有效跌破(触碰{touch_count}次/跌破{break_count}次)，主力在"}

        return {"controlling": True, "break_count": break_count,
                "reason": f"跌破{break_count}次(≤3)，主力在"}

    # ===================================================================
    # 持仓管理
    # ===================================================================

    def update(
        self,
        symbol: str,
        fill_price: float,
        fill_qty: int,
        date: Any,
        n_pattern_low: Optional[float] = None,
        signal_type: str = "B1",
    ) -> None:
        """记录买入（或加仓）。

        Args:
            symbol: 股票代码
            fill_price: 成交价
            fill_qty: 成交股数
            date: 成交日期
            n_pattern_low: N型结构低点（用于动态止损）
            signal_type: 信号类型
        """
        date = pd.Timestamp(date)

        if symbol in self.positions:
            # 加仓：加权平均入场价
            old = self.positions[symbol]
            total_shares = old["shares"] + fill_qty
            avg_price = (
                old["shares"] * old["entry_price"] + fill_qty * fill_price
            ) / total_shares
            old["shares"] = total_shares
            old["entry_price"] = round(avg_price, 3)
            old["entry_date"] = old["entry_date"]  # 保持首次入场日期
            if n_pattern_low is not None:
                old["n_pattern_low"] = n_pattern_low
            old["signal_type"] = signal_type
        else:
            self.positions[symbol] = {
                "shares": fill_qty,
                "entry_price": fill_price,
                "entry_date": date,
                "n_pattern_low": n_pattern_low,
                "signal_type": signal_type,
            }

    def remove(self, symbol: str, date: Any) -> None:
        """记录卖出（清仓）。

        Args:
            symbol: 股票代码
            date: 卖出日期
        """
        self.positions.pop(symbol, None)
        self._pending_trendline.pop(symbol, None)

    # ===================================================================
    # 综合诊断
    # ===================================================================

    def diagnose(
        self, symbol: str, data: pd.DataFrame
    ) -> Dict[str, Any]:
        """综合诊断一只持仓的所有风控信号。

        Args:
            symbol: 股票代码
            data: 含 OHLCV 的 DataFrame

        Returns:
            dict 包含所有检查结果
        """
        return {
            "symbol": symbol,
            "position": self.positions.get(symbol),
            "stop_loss": self.check_stop_loss(symbol, data),
            "fly_away": self.check_fly_away(symbol, data),
            "s1": self.check_s1(symbol, data),
            "dd": self.check_dd(symbol, data),
            "trendline": self.check_trendline(symbol, data),
            "main_capital": self.check_main_capital(data),
            "distribution": self.detect_distribution(data),
        }
