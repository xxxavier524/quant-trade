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
    key_kline,
    violent_kline,
    double_volume_bar,
    chip_concentration,
    symmetric_structure,
    fill_pit_exit_pit,
    long_yin_short_column,
    wave_identifier,
    key_k_abc,
    dynamic_stop_loss,
    fly_away,
    s1_sell_signal,
    dd_sell_signal,
    trendline_break,
)

from alphapulse.factors.experimental import (
    northbound_capital_flow,
    idiosyncratic_vol,
    turnover_uniformity,
    analyst_revision,
    capital_flow_big_order,
)
from alphapulse.factors import industry_rotation, beta_fundamental

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
    # --- 多头K线因子（core） ---
    "KEY_KLINE": {
        "module": key_kline,
        "type": "core",
        "description": "关键K线：近20日涨幅最大阳线 + 成交量>2倍20日均量",
        "default_params": {"lookback": 20, "vol_mult": 2.0},
    },
    "VIOLENT_KLINE": {
        "module": violent_kline,
        "type": "core",
        "description": "暴力K：涨幅>5% + 成交量>3倍20日均量",
        "default_params": {"pct_threshold": 5.0, "vol_mult": 3.0},
    },
    "DOUBLE_VOLUME_BAR": {
        "module": double_volume_bar,
        "type": "core",
        "description": "倍量柱：成交量>=前日2倍 + 阳线",
        "default_params": {"mult": 2.0},
    },
    # --- 形态识别因子（core） ---
    "CHIP_CONCENTRATION": {
        "module": chip_concentration,
        "type": "core",
        "description": "筹码集中度：20天振幅<15% + 10天振幅<20天×0.6 + 换手率下降，输出0-1连续值",
        "default_params": {"window": 20, "amplitude_max": 15.0},
    },
    "SYMMETRIC_STRUCTURE": {
        "module": symmetric_structure,
        "type": "core",
        "description": "对称结构：V型/W型对称形态识别，使用argrelextrema找极值点",
        "default_params": {"tolerance": 0.05, "min_leg_len": 5},
    },
    "FILL_PIT_EXIT_PIT": {
        "module": fill_pit_exit_pit,
        "type": "core",
        "description": "填坑出坑：回落>15%→横盘整理3-10天→放量>1.5倍突破上沿",
        "default_params": {"drop_pct": 15.0, "consolidation_days": 3, "breakout_vol_mult": 1.5},
    },
    "LONG_YIN_SHORT_COLUMN": {
        "module": long_yin_short_column,
        "type": "core",
        "description": "长阴短柱：阴线+成交量<前日0.7倍+实体>1%",
        "default_params": {"vol_shrink": 0.7, "body_min_pct": 1.0},
    },
    "WAVE_IDENTIFIER": {
        "module": wave_identifier,
        "type": "core",
        "description": "波段识别：建仓波(20日涨幅<10%+量温和)/拉升波(10日涨幅>15%+量放大>1.5倍)/冲刺波(5日涨幅>20%+量巨量>3倍)",
        "default_params": {
            "accumulation_max_return": 0.10, "vol_mild_ratio": 1.0,
            "lift_min_return": 0.15, "vol_expand_ratio": 1.5,
            "sprint_min_return": 0.20, "vol_huge_ratio": 3.0,
        },
    },
    "KEY_K_ABC": {
        "module": key_k_abc,
        "type": "core",
        "description": "关键K线ABC节点：A(20日最低+反弹>3%)/B(首次回调低点)/C(突破前高)，输出0-3",
        "default_params": {"lookback": 20, "rebound_pct": 3.0, "min_leg_len": 3},
    },
    # --- 指标类因子（不含选股逻辑，仅输出数值） ---
    "BRICK_INDICATOR": {
        "module": brick_ultra,
        "compute_func": "compute_brick_indicator",
        "type": "indicator",  # 指标公式
        "description": "砖型图指标值（纯数值输出，不含选股逻辑）。等同通达信砖型图:=IF(VAR6A>4,VAR6A-4,0)",
        "source": "砖型图.txt",
        "default_params": {},
    },
    "ZHIXING_LINES": {
        "module": zhixing_washout,
        "compute_func": "compute_indicator",
        "type": "indicator",  # 指标公式
        "description": "知行四线数值（短期/中期/中长期/长期），纯指标输出",
        "source": "知行洗盘短线.txt",
        "default_params": {"n1": 5, "n2": 30},
    },
    # --- 实验性因子（券商金工研究来源） ---
    "NORTHBOUND_FLOW": {
        "module": northbound_capital_flow,
        "type": "experimental",
        "description": "北向资金代理因子：量价估计资金流向加速度。广发证券北向2.0 / 国金证券(2024)。A股IC 5.1%, ICIR 2.7, 胜率89.3%",
        "source": "广发证券《北向选股2.0》/ 国金证券《量化行业配置》",
        "default_params": {"short_window": 5, "long_window": 20, "zscore_window": 60},
    },
    "IDIOSYNCRATIC_VOL": {
        "module": idiosyncratic_vol,
        "type": "experimental",
        "description": "特质波动率(IVOL)因子：去Beta后残差波动率。国信证券(2022)。A股RankIC -9.29%, ICIR -3.44, 胜率86%。负向因子(低IVOL=看多)",
        "source": "国信证券金工(2022) / 东吴证券纯真波动率(2020) / Ang et al.(2006)",
        "default_params": {"window": 20, "method": "simple", "use_composite": False},
    },
    "TURNOVER_UNIFORMITY": {
        "module": turnover_uniformity,
        "type": "experimental",
        "description": "换手率分布均匀度(UTD)因子：换手率CV/范围比。东吴证券(2024)。A股RankIC -6.7%, ICIR -3.99, 胜率77.3%。负向因子(均匀=看多)",
        "source": "东吴证券金工(2024) / 中信建投筹码分布因子(2025)",
        "default_params": {"window": 20, "method": "cv", "use_decay": True},
    },
    "ANALYST_REVISION": {
        "module": analyst_revision,
        "type": "experimental",
        "description": "分析师盈利修正代理因子：量价动量代理盈利上调。华泰证券(2024)。A股综合RankIC 4.27%, TOP组合年化超额10.55%",
        "source": "华泰证券金工《分析师预期类因子初探》(2024.12)",
        "default_params": {"short_window": 5, "long_window": 20, "volume_window": 10, "momentum_window": 60},
    },
    "CAPITAL_FLOW_BIG": {
        "module": capital_flow_big_order,
        "type": "experimental",
        "description": "大单资金流向因子：量价识别大单净流入强度。东海证券。A股IC 0.087(30天), IR 0.729(大单最强)",
        "source": "东海证券金工",
        "default_params": {"flow_window": 20, "vol_ratio_threshold": 1.5, "ma_window": 60},
    },
    # --- 两阶段AI选股模型（Stage 1+2） ---
    "INDUSTRY_ROTATION": {
        "module": industry_rotation,
        "type": "experimental",
        "description": "行业主线轮动模型(Stage 1)：构建行业指数+趋势评分(MA/MACD/动量/一致性)+排序。Top5行业实测半年",
        "source": "AI量化选股第一阶段——行业主线轮动模型",
        "default_params": {"ma_periods": [5, 10, 20, 60], "mom_periods": [20, 60, 120], "top_n": 5},
    },
    "BETA_PREDICTION": {
        "module": beta_fundamental,
        "type": "experimental",
        "description": "个股β预测模型(Stage 2)：7个基本面因子代理(规模/盈利稳定性/成长性/经营杠杆/财务杠杆/资产质量/量能趋势)预测β系数",
        "source": "AI量化选股第二阶段——基于个股基本面特征因子的β系数预测",
        "default_params": {"hist_beta_weight": 0.60, "fundamental_weight": 0.40},
    },
    "TWO_STAGE_SELECTION": {
        "module": industry_rotation,
        "type": "selection",
        "description": "两阶段AI选股：行业轮动(Top5主线行业) + 个股β排序(每行业Top10)。双层垂直AI体系(宏观→微观)",
        "source": "AI量化选股模型——行业配置+个股精选双层垂直体系",
        "default_params": {"top_industries": 5, "stocks_per_industry": 10, "min_trend_score": 0.45},
    },
    # --- 风控因子（type="risk"） ---
    "DYNAMIC_STOP_LOSS": {
        "module": dynamic_stop_loss,
        "type": "risk",
        "description": "动态止损：止损价 = min(入场日最低价-3价位, 前N型结构低点-3价位)，最小变动价位0.01",
        "default_params": {},
    },
    "FLY_AWAY": {
        "module": fly_away,
        "type": "risk",
        "description": "放飞减仓：连续阳线加速/白线上方加速/砖型图连续红砖→阶梯减仓(1/4→1/3→1/2)，全部shift(1)防未来函数",
        "default_params": {},
    },
    "S1_SELL_SIGNAL": {
        "module": s1_sell_signal,
        "type": "risk",
        "description": "S1最强卖出信号：波段最高点放巨量阴线（阴线+量近20日最高+量>20日阳量均值2x+前5日≥3日涨），假阴真阳降级",
        "default_params": {"vol_window": 20, "vol_mult": 2.0},
    },
    "DD_SELL_SIGNAL": {
        "module": dd_sell_signal,
        "type": "risk",
        "description": "DD卖出信号：收盘价<前日最低价，连续2天DD增强，全部shift(1)防未来函数",
        "default_params": {},
    },
    "TRENDLINE_BREAK": {
        "module": trendline_break,
        "type": "risk",
        "description": "趋势线跌破：白线(EMA(EMA(C,10),10))与黄线(4MA均值)跌破检测，含假跌破确认，全部shift(1)防未来函数",
        "default_params": {},
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
    # 支持 registry 中指定 compute_func 键来调用非 compute 函数
    func_name = entry.get("compute_func", "compute")
    func = getattr(entry["module"], func_name)
    return func(data, **merged_params)
