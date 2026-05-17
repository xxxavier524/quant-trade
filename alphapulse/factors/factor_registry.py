"""因子注册表。

通过名称字符串调用因子，统一接口：compute(data, **params) -> pd.Series
"""

from alphapulse.factors import (
    n_struct,
    vol_red_green,
    abnormal_vol,
    vol_cont_shrink,
    kdj_j_low,
    weekly_ma_bull,
    macd_bull_dead,
    shrink_to_abnormal,
    b1_formula,
    zhixing_trend,
    brick_ultra,
    zhixing_washout,
    volume_b1,
)

FACTOR_REGISTRY = {
    "N_STRUCT": {
        "module": n_struct,
        "description": "N型结构识别：上升-回撤-再上升形态",
        "default_params": {"min_leg_len": 5, "retrace_ratio": 0.618},
    },
    "VOL_RED_GREEN": {
        "module": vol_red_green,
        "description": "红肥绿瘦：上涨放量 vs 下跌缩量",
        "default_params": {"N": 20, "ratio_threshold": 1.3},
    },
    "ABNORMAL_VOL": {
        "module": abnormal_vol,
        "description": "放量异动：成交量异常放大",
        "default_params": {"M": 60, "P": 20, "K": 2.0, "X": 3, "Y": 5},
    },
    "VOL_CONT_SHRINK": {
        "module": vol_cont_shrink,
        "description": "缩量：当日成交量极度萎缩",
        "default_params": {"shrink_ratio": 0.25, "recent_period": 5},
    },
    "KDJ_J_LOW": {
        "module": kdj_j_low,
        "description": "J值低位：KDJ超卖信号",
        "default_params": {"j_threshold": 13},
    },
    "WEEKLY_MA_BULL": {
        "module": weekly_ma_bull,
        "description": "周线多头：周线MA5>MA10>MA20",
        "default_params": {"ma_periods": [5, 10, 20]},
    },
    "MACD_BULL_DEAD": {
        "module": macd_bull_dead,
        "description": "MACD多头或零轴上死叉",
        "default_params": {"fast": 12, "slow": 26, "signal": 9},
    },
    "SHRINK_TO_ABNORMAL": {
        "module": shrink_to_abnormal,
        "description": "缩量至异动量1/4",
        "default_params": {"ratio": 0.25},
    },
    "B1_FORMULA": {
        "module": b1_formula,
        "type": "selection",  # 选股方案
        "description": "B1选股方案（6条件AND）：涨幅±3%+振幅<9%+J<13+趋势线>多空线+DIF>-0.1+市值>10亿",
        "source": "B1选股公式.txt",
        "default_params": {
            "pct_change_range": 3.0, "amplitude_max": 9.0,
            "j_threshold": 13.0, "dif_threshold": -0.1,
            "trend_fast": 12, "trend_slow": 26,
        },
    },
    # --- 知行系列（来自知行趋势线.txt + 知行洗盘短线.txt + 知行超短选股方案.txt） ---
    "ZHIXING_TREND": {
        "module": zhixing_trend,
        "type": "indicator",  # 指标公式
        "description": "知行趋势线指标：EMA(EMA(C,10),10)短期趋势 + 4MA均值多空线 + MACD DIF",
        "source": "知行趋势线.txt",
        "default_params": {"m1": 20, "m2": 60, "m3": 120, "m4": 250},
    },
    "ZHIXING_WASHOUT": {
        "module": zhixing_washout,
        "type": "selection",  # 选股方案
        "description": "知行洗盘短线选股：四线归零/CROSS(短期,长期)/CROSS(短期,中期)/中长期>65",
        "source": "知行洗盘短线.txt",
        "default_params": {"n1": 5, "n2": 30},
    },
    # --- 砖型图系列（来自砖型图.txt + 砖型图超短选股.txt） ---
    "BRICK_ULTRA": {
        "module": brick_ultra,
        "type": "selection",  # 选股方案
        "description": "砖型图超短选股：TDX砖型图指标昨绿→今红转换，红实体≥绿实体×2/3",
        "source": "砖型图超短选股.txt",
        "default_params": {"min_ratio": 2/3},
    },
    # --- 量能B1系列（来自量能B1选股.txt） ---
    "VOLUME_B1": {
        "module": volume_b1,
        "type": "selection",  # 选股方案
        "description": "量能B1选股：阳阴量比+爆量阳+缩倍量+价格位置+市值≥40亿+收盘>QL加权均线",
        "source": "量能B1选股.txt",
        "default_params": {
            "yangyin_ratio_28": 1.65, "yangyin_ratio_14": 2.25,
            "j_threshold": 13.0, "min_market_cap": 40,
            "surge_ratio": 1.85, "half_down_ratio": 0.5,
        },
    },
    # --- 指标类因子（不含选股逻辑，仅输出数值） ---
    "BRICK_INDICATOR": {
        "module": brick_ultra,
        "type": "indicator",  # 指标公式
        "description": "砖型图指标值（纯数值输出，不含选股逻辑）。等同通达信砖型图:=IF(VAR6A>4,VAR6A-4,0)",
        "source": "砖型图.txt",
        "default_params": {},
    },
    "ZHIXING_LINES": {
        "module": zhixing_washout,
        "type": "indicator",  # 指标公式
        "description": "知行四线数值（短期/中期/中长期/长期），纯指标输出",
        "source": "知行洗盘短线.txt",
        "default_params": {"n1": 5, "n2": 30},
    },
}


def compute_factor(
    name: str,
    data: "pd.DataFrame",
    **params,
) -> "pd.Series":
    """通过因子名称调用计算函数。

    Args:
        name: 因子名称（如 'N_STRUCT'）
        data: OHLCV DataFrame
        **params: 覆盖默认参数

    Returns:
        pd.Series: 因子值
    """
    if name not in FACTOR_REGISTRY:
        raise ValueError(f"未知因子: {name}。可用: {list(FACTOR_REGISTRY.keys())}")

    entry = FACTOR_REGISTRY[name]
    merged_params = {**entry["default_params"], **params}
    return entry["module"].compute(data, **merged_params)
