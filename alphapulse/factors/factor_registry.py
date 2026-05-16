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
