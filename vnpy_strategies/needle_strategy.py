"""单针下三十策略 VeighNa CtaTemplate 封装。"""

try:
    from vnpy_ctastrategy import CtaTemplate, BarData, TradeData
    VNPY_AVAILABLE = True
except ImportError:
    CtaTemplate = object
    VNPY_AVAILABLE = False

from collections import deque
import pandas as pd


class NeedleStrategy(CtaTemplate if VNPY_AVAILABLE else object):
    """单针下三十策略。

    参数:
        shadow_ratio_threshold: 下影线占比阈值 (0.6)
        j_threshold: J值超卖阈值 (13)
        position_threshold: 价格低位阈值 (0.30)
    """

    author = "AlphaPulse-A"

    shadow_ratio_threshold = 0.6
    j_threshold = 13.0
    position_threshold = 0.30
    signal_count = 0

    parameters = ["shadow_ratio_threshold", "j_threshold", "position_threshold"]
    variables = ["signal_count"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        if VNPY_AVAILABLE:
            super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.bars = deque(maxlen=300)

    def on_init(self):
        if VNPY_AVAILABLE:
            self.write_log("单针策略初始化")
            self.load_bar(30)

    def on_start(self):
        if VNPY_AVAILABLE:
            self.write_log("单针策略启动")

    def on_stop(self):
        if VNPY_AVAILABLE:
            self.write_log("单针策略停止")

    def on_bar(self, bar: "BarData"):
        if not VNPY_AVAILABLE:
            return

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

        from alphapulse.strategies.needle import generate_signals

        df = pd.DataFrame(list(self.bars)).set_index("datetime")
        signals = generate_signals(
            df, symbol=self.vt_symbol,
            shadow_ratio_threshold=self.shadow_ratio_threshold,
            j_threshold=self.j_threshold,
            position_threshold=self.position_threshold,
        )

        if len(signals) > 0:
            last = signals.iloc[-1]
            if last["signal"] == 1 and abs(self.pos) < 0.2:
                self.buy(bar.close_price, 1)
                self.signal_count += 1
                self.write_log(f"单针买入: {bar.datetime} @ {bar.close_price}")

    def on_trade(self, trade: "TradeData"):
        if VNPY_AVAILABLE and trade.offset.value == "开":
            self.put_event()
