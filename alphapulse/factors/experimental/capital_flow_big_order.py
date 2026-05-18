"""
大单资金流向因子 (Capital Flow - Big Order Factor).

基于东海证券资金流因子分析研究。

核心逻辑:
- A股市场大单/特大单资金流向具有显著的选股能力
- 大单资金净流入 = 主动买入大单 - 主动卖出大单
- 大单交易反映机构/游资行为，具有信息优势
- 大单持续净流入的股票未来超额收益显著

方法论:
    1. 用日内价格变化 * 成交量的加权符号识别资金流向方向
       （上涨时放量 = 主动买入 = 资金流入，下跌时放量 = 主动卖出 = 资金流出）
    2. 区分大单: 当日成交量大 + 价格变动大的交易日为大单日
    3. 计算滚动窗口内净流入比率
    4. 大单净流入 / 总成交量 = 资金流向强度

A股实证表现 (东海证券):
    - 大单资金净流入(CFLOW_BG_20D): IC 0.087 (30天), IR 0.729
    - 资金净流入(CFLOW_LB_20D): IC 0.056, IR 0.479
    - 中单资金净流入(CFLOW_MD_20D): IC 0.055, IR 0.651
    - 特大单资金净流入(CFLOW_LG_20D): IC 0.010, IR 0.112

    大单资金流向因子IC最强（0.087），是中单的1.5倍、特大单的8.7倍。

Source: 东海证券金工
"""

import numpy as np
import pandas as pd


def compute(
    data: pd.DataFrame,
    flow_window: int = 20,
    vol_ratio_threshold: float = 1.5,
    ma_window: int = 60,
    smoothing: int = 3,
) -> pd.Series:
    """计算大单资金流向因子。

    通过量价关系代理大单资金流向:
    - 当日成交量 > vol_ratio_threshold * 长期均量 → 视为大单活跃日
    - 大单活跃日 * 价格变动方向 → 资金流向
    - 滚动累计净流入 / 总成交量

    Args:
        data: 含 'close', 'volume' 列的DataFrame
        flow_window: 资金流向计算窗口（日）
        vol_ratio_threshold: 大单量能阈值倍数
        ma_window: 长期均量计算窗口
        smoothing: 平滑窗口

    Returns:
        pd.Series: 因子值，正值表示大单资金净流入，值越大越看多
    """
    volume = data["volume"]
    close = data["close"]

    # --- Step 1: 识别大单交易日 ---
    vol_ma = volume.rolling(ma_window).mean()
    vol_ratio = volume / vol_ma.replace(0, np.nan)
    is_big_order_day = (vol_ratio >= vol_ratio_threshold).astype(float)

    # --- Step 2: 每日资金流向 ---
    daily_ret = close.pct_change()

    # 资金流向方向: 量比 * 涨跌方向 * |涨跌幅|
    # 放量上涨→强流入(+), 放量下跌→强流出(-)
    flow_direction = np.sign(daily_ret) * np.abs(daily_ret)

    # 大单资金流 = 大单日标记 * 量比 * 方向
    daily_big_flow = is_big_order_day * vol_ratio * flow_direction
    # 总资金流（所有交易日）
    daily_total_flow = vol_ratio * flow_direction

    # --- Step 3: 滚动窗口累计 ---
    # 大单累计净流入
    cum_big_flow = daily_big_flow.rolling(flow_window).sum()
    # 总累计净流入
    cum_total_flow = daily_total_flow.rolling(flow_window).sum()

    # 大单占比: 大单净流入 / (总净流入绝对值 + epsilon)
    big_flow_ratio = cum_big_flow / (np.abs(cum_total_flow) + 1e-10)

    # 日均大单强度: 大单累计净流入 / 大单日数量
    big_order_days = is_big_order_day.rolling(flow_window).sum()
    daily_big_intensity = cum_big_flow / big_order_days.replace(0, np.nan)

    # --- Step 4: 平滑 ---
    if smoothing > 1:
        big_flow_ratio = big_flow_ratio.rolling(smoothing).mean()
        daily_big_intensity = daily_big_intensity.rolling(smoothing).mean()

    # --- Step 5: 综合因子 ---
    # Z-Score标准化各组件后等权合成
    zscore = lambda s: (s - s.rolling(ma_window).mean()) / s.rolling(ma_window).std().replace(0, np.nan)

    z_ratio = zscore(big_flow_ratio).fillna(0)
    z_intensity = zscore(daily_big_intensity).fillna(0)

    # 资金流向一致性：近期净流入与历史净流入的差值
    recent_flow = daily_big_flow.rolling(max(flow_window // 4, 3)).sum()
    historic_flow = daily_big_flow.rolling(flow_window).sum() / max(flow_window // 3, 1)
    flow_consistency = recent_flow - historic_flow
    z_consistency = zscore(flow_consistency).fillna(0)

    factor = 0.5 * z_ratio + 0.3 * z_intensity + 0.2 * z_consistency

    # 最终标准化
    factor_final = zscore(factor)

    return factor_final.fillna(0).astype(float)
