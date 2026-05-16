"""风险监控模块。规格书5.6节。

三维度监控：市场系统性风险 / 个股风险 / 策略运行异常。
"""

import pandas as pd
import numpy as np


class RiskMonitor:
    """三维度风险监控。"""

    def __init__(self, params: dict | None = None):
        self.params = params or {}

    def check_market_risk(self, index_df: pd.DataFrame) -> list[str]:
        """市场系统性风险检查。"""
        alerts = []
        if len(index_df) < 6:
            return alerts

        close = index_df["close"]

        # 近5日跌幅 > 10%
        recent_drop = (close.iloc[-1] / close.iloc[-6]) - 1
        if recent_drop < -0.10:
            alerts.append(f"⚠️ 市场风险: 近5日大盘跌幅{recent_drop:.1%}")

        # 波动率飙升（>历史90分位）
        returns = close.pct_change().dropna()
        if len(returns) >= 20:
            vol = returns.rolling(20).std().iloc[-1]
            vol_percentile = (returns.rolling(20).std() < vol).mean()
            if vol_percentile > 0.90:
                alerts.append(f"⚠️ 波动率风险: 当前处于历史{vol_percentile:.0%}分位")

        return alerts

    def check_stock_risk(self, code: str, stock_df: pd.DataFrame) -> list[str]:
        """个股风险检查。"""
        alerts = []
        if len(stock_df) == 0:
            return alerts

        latest = stock_df.iloc[-1]

        # 涨跌停
        if "pct_change" in stock_df.columns:
            pct = latest.get("pct_change", 0)
            if abs(pct) >= 9.5:
                alerts.append(f"🔴 {code}: 涨跌幅{pct}%，接近涨跌停")

        # 停牌/无成交
        if latest.get("volume", 1) == 0:
            alerts.append(f"🔴 {code}: 成交量为0，可能停牌")

        return alerts

    def check_strategy_risk(
        self,
        signal_count: int,
        factor_report: dict,
    ) -> list[str]:
        """策略运行异常检查。"""
        alerts = []

        if signal_count == 0:
            alerts.append("⚠️ 策略异常: 今日无选股信号")
        elif signal_count > 50:
            alerts.append(f"⚠️ 策略异常: 信号数{signal_count}过多，可能参数失效")

        failed = [k for k, v in factor_report.items() if v.get("status") == "REMOVE"]
        if failed:
            alerts.append(f"🔴 因子失效: {len(failed)}个因子已失效: {failed}")

        return alerts
