"""砖型图策略 VeighNa CtaTemplate 封装。"""

try:
    from vnpy_ctastrategy import CtaTemplate, BarData, TradeData
    VNPY_AVAILABLE = True
except ImportError:
    CtaTemplate = object
    VNPY_AVAILABLE = False

from collections import deque
import pandas as pd


class BrickStrategy(CtaTemplate if VNPY_AVAILABLE else object):
    """Renko 砖型图策略。

    参数:
        brick_pct: 砖块振幅 (0.02 = 2%)
        confirm_bricks: 确认的连续同向砖块数 (2)
    """

    author = "AlphaPulse-A"

    brick_pct = 0.02
    confirm_bricks = 2
    signal_count = 0

    parameters = ["brick_pct", "confirm_bricks"]
    variables = ["signal_count"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        if VNPY_AVAILABLE:
            super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.bars = deque(maxlen=300)
        self._brick_close = 0
        self._brick_direction = 0

    def on_init(self):
        if VNPY_AVAILABLE:
            self.write_log("砖型图策略初始化")
            self.load_bar(30)

    def on_start(self):
        if VNPY_AVAILABLE:
            self.write_log("砖型图策略启动")

    def on_stop(self):
        if VNPY_AVAILABLE:
            self.write_log("砖型图策略停止")

    def on_bar(self, bar: "BarData"):
        if not VNPY_AVAILABLE:
            return

        self.bars.append({
            "datetime": bar.datetime,
            "close": bar.close_price,
        })

        if len(self.bars) < 30:
            return

        from alphapulse.strategies.brick import generate_signals

        df = pd.DataFrame(list(self.bars)).set_index("datetime")
        signals = generate_signals(df, symbol=self.vt_symbol,
                                   brick_pct=self.brick_pct,
                                   confirm_bricks=self.confirm_bricks)

        if len(signals) > 0:
            last = signals.iloc[-1]
            if last["signal"] == 1 and abs(self.pos) < 0.2:
                self.buy(bar.close_price, 1)
                self.signal_count += 1
                self.write_log(f"砖型图买入: {bar.datetime} @ {bar.close_price}")

    def on_trade(self, trade: "TradeData"):
        if VNPY_AVAILABLE and trade.offset.value == "开":
            self.put_event()
