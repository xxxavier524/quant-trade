"""B1策略 VeighNa CtaTemplate 封装。

在 on_bar 中调用 alphapulse B1 信号生成器，
产生信号后通过 CtaTemplate 接口下单。
"""

try:
    from vnpy_ctastrategy import (
        CtaTemplate,
        StopOrder,
        TickData,
        BarData,
        TradeData,
        OrderData,
        BarGenerator,
        ArrayManager,
    )
    VNPY_AVAILABLE = True
except ImportError:
    # VeighNa 不可用时的 fallback 占位
    CtaTemplate = object
    VNPY_AVAILABLE = False

import pandas as pd
import numpy as np
from collections import deque


class B1Strategy(CtaTemplate if VNPY_AVAILABLE else object):
    """B1 多因子组合策略。

    参数:
        shrink_ratio: 缩量比例 (0.25)
        j_threshold: J值低位阈值 (13)
        abnormal_k: 放量倍量 (2.0)
        abnormal_x: 最小异动次数 (3)
        abnormal_y: 异动检查窗口 (5)
    """

    author = "AlphaPulse-A"

    # 参数
    shrink_ratio = 0.25
    j_threshold = 13.0
    abnormal_k = 2.0
    abnormal_x = 3
    abnormal_y = 5

    # 变量
    signal_count = 0
    trade_count = 0

    parameters = [
        "shrink_ratio", "j_threshold",
        "abnormal_k", "abnormal_x", "abnormal_y",
    ]
    variables = ["signal_count", "trade_count"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        if VNPY_AVAILABLE:
            super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.bars = deque(maxlen=200)  # 缓存近200根bar用于计算因子

    def on_init(self):
        """策略初始化。"""
        if VNPY_AVAILABLE:
            self.write_log("B1策略初始化")
            self.load_bar(20)

    def on_start(self):
        """策略启动。"""
        if VNPY_AVAILABLE:
            self.write_log("B1策略启动")

    def on_stop(self):
        """策略停止。"""
        if VNPY_AVAILABLE:
            self.write_log("B1策略停止")

    def on_bar(self, bar: "BarData"):
        """K线回调。"""
        if not VNPY_AVAILABLE:
            return

        # 缓存bar数据
        self.bars.append({
            "datetime": bar.datetime,
            "open": bar.open_price,
            "high": bar.high_price,
            "low": bar.low_price,
            "close": bar.close_price,
            "volume": bar.volume,
        })

        if len(self.bars) < 120:
            return

        # 构建DataFrame调用因子
        from alphapulse.strategies.b1 import generate_signals

        df = pd.DataFrame(list(self.bars))
        df = df.set_index("datetime")

        signals = generate_signals(
            df,
            symbol=self.vt_symbol,
            shrink_ratio=self.shrink_ratio,
            j_threshold=self.j_threshold,
            abnormal_k=self.abnormal_k,
            abnormal_x=self.abnormal_x,
            abnormal_y=self.abnormal_y,
        )

        if len(signals) > 0:
            last_signal = signals.iloc[-1]
            if last_signal["signal"] == 1:
                self.signal_count += 1

                # 仓位检查
                if abs(self.pos) < 0.2:
                    price = bar.close_price
                    self.buy(price, 1)  # 简化：买1手
                    self.trade_count += 1
                    self.write_log(f"B1买入信号: {bar.datetime} @ {price}")

    def on_trade(self, trade: "TradeData"):
        """成交回调。"""
        if VNPY_AVAILABLE and trade.offset.value == "开":
            self.put_event()
