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
from alphapulse.strategies import needle_washout, brick_three_types, b1_b2_b3_strategy, zg_b1_brick

from alphapulse.factors.experimental import (
    northbound_capital_flow,
    idiosyncratic_vol,
    turnover_uniformity,
    analyst_revision,
    capital_flow_big_order,
)
from alphapulse.factors import industry_rotation, beta_fundamental, knowledge_points
from alphapulse.factors import yin_volume_34, four_brick_cycle, weekly_ma_cross
from alphapulse.factors import (
    bbi,
    sell_score_v14,
    macd_enhanced,
    turnover_signals,
    weekly_long_bull,
    b1_entry_filters,
    zuchongzhi_target,
    zg_advanced_patterns,
    chip_laws,
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
            "m1": 14, "m2": 28, "m3": 57, "m4": 114,
        },
    },
    # --- 知行系列（来自知行趋势线.txt + 知行洗盘短线.txt + 知行超短选股方案.txt） ---
    "ZHIXING_TREND": {
        "module": zhixing_trend,
        "type": "indicator",  # 指标公式
        "description": "知行趋势线指标：EMA(EMA(C,10),10)短期趋势 + 4MA均值多空线 + MACD DIF",
        "source": "知行趋势线.txt",
        "default_params": {"m1": 14, "m2": 28, "m3": 57, "m4": 114},
    },
    "ZHIXING_WASHOUT": {
        "module": zhixing_washout,
        "type": "selection",  # 选股方案
        "description": "知行洗盘短线选股：四线归零/CROSS(短期,长期)/CROSS(短期,中期)/中长期>65",
        "source": "知行洗盘短线.txt",
        "default_params": {"n1": 3, "n2": 21},
    },
    # --- 体系补建因子（docs/trading_system.md §3，2026-06-11） ---
    "YIN_VOLUME_34": {
        "module": yin_volume_34,
        "type": "factor",
        "description": "3/4阴量线：放量阳后阴线缩量至前日3/4以内=卖压不足（多头确认）",
        "source": "docs/trading_system.md §3",
        "default_params": {"ratio": 0.75, "vol_ma_window": 5},
    },
    "FOUR_BRICK_CYCLE": {
        "module": four_brick_cycle,
        "type": "factor",
        "description": "砖型图四砖一周期：第1-2红砖=早段多头；compute_late第4砖起=减仓",
        "source": "docs/trading_system.md §3/§4",
        "default_params": {"early_max": 2},
    },
    "WEEKLY_MA_CROSS": {
        "module": weekly_ma_cross,
        "type": "factor",
        "description": "周线M5上穿M14 + 日线MA5>MA10>MA20多头排列（B1加强因子）",
        "source": "用户需求 2026-06-11",
        "default_params": {"fast": 5, "slow": 14, "recent_weeks": 4},
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
            "j_threshold": 13.0, "min_market_cap": 40e8,
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
    # --- 7大交易知识点因子（core） ---
    "PULL_ROPE": {
        "module": knowledge_points,
        "compute_func": "compute_pull_rope",
        "type": "core",
        "description": "牵牛绳：B1入场后未出现S1+持续在白线以上→继续持有信号，输出bool",
        "source": "7大交易知识点",
        "default_params": {"factor_name": "PULL_ROPE"},
    },
    "IN_THE_BOWL": {
        "module": knowledge_points,
        "compute_func": "compute_in_the_bowl",
        "type": "core",
        "description": "掉进碗里：股价在白线以下黄线以上区间+同时出现B1信号→增强买点，输出bool",
        "source": "7大交易知识点",
        "default_params": {"factor_name": "IN_THE_BOWL"},
    },
    "YELLOW_LINE_VALUE": {
        "module": knowledge_points,
        "compute_func": "compute_yellow_line_value",
        "type": "indicator",
        "description": "黄线交易价值：首次回踩黄线不破+无S1信号+出现B1买点→0-1连续评分",
        "source": "7大交易知识点",
        "default_params": {"factor_name": "YELLOW_LINE_VALUE"},
    },
    "PIERCE_COUNTERPART": {
        "module": knowledge_points,
        "compute_func": "compute_pierce_counterpart",
        "type": "indicator",
        "description": "击穿对手盘：缩量跌破黄线+观察次日是否站稳→0=无/1=击穿/2=击穿+恢复",
        "source": "7大交易知识点",
        "default_params": {"factor_name": "PIERCE_COUNTERPART"},
    },
    "KEY_SUPPORT": {
        "module": knowledge_points,
        "compute_func": "compute_key_support",
        "type": "indicator",
        "description": "关键支撑价位：前N型低点-3价位/横盘区间下沿/SB1下沿→DataFrame三列",
        "source": "7大交易知识点",
        "default_params": {"factor_name": "KEY_SUPPORT"},
    },
    "MAIN_CAPITAL": {
        "module": knowledge_points,
        "compute_func": "compute_main_capital",
        "type": "indicator",
        "description": "主力资金判断：近60日跌破黄线次数判断主力行为→0=弱/1=不在/2=强",
        "source": "7大交易知识点",
        "default_params": {"factor_name": "MAIN_CAPITAL"},
    },
    "DISTRIBUTION_PATTERNS": {
        "module": knowledge_points,
        "compute_func": "compute_distribution_patterns",
        "type": "indicator",
        "description": "5种出货方式：S1/加速上涨后放量长阴/新高后阶梯放量下跌/双头/顶部阴量>阳量→DataFrame五列bool",
        "source": "7大交易知识点",
        "default_params": {"factor_name": "DISTRIBUTION_PATTERNS"},
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
        "default_params": {"n1": 3, "n2": 21},
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
    # --- AlphaPulse-A 策略（module指向strategies而非factors） ---
    "NEEDLE_WASHOUT": {
        "module": needle_washout,
        "type": "selection",
        "description": "单针下三十策略(优化版v2)：长下影+J超卖+缩量+Fib20-70%+低位30%+知行趋势走平，B1前提可选关闭",
        "source": "AlphaPulse-A主力洗盘补票策略",
        "default_params": {
            "b1_lookback": 60, "require_b1_history": False,
            "j_threshold": 20.0, "volume_shrink_ratio": 0.85,
            "volume_ma_period": 20, "fib_min": 0.20, "fib_max": 0.70,
            "position_lookback": 60, "position_threshold": 0.30,
            "shadow_mult": 3.0, "trend_slope_window": 5,
        },
    },
    "BRICK_THREE_TYPES": {
        "module": brick_three_types,
        "type": "selection",
        "description": "砖型图3子类型策略：N型起跳(BRICK_N_JUMP)+上涨中继(BRICK_CONTINUATION)+横盘突破(BRICK_BREAKOUT)，基于brick_ultra.compute_brick_indicator红绿砖定义",
        "source": "AlphaPulse-A砖型图策略3子类型版本",
        "default_params": {
            "vol_mult_n_jump": 1.5, "vol_mult_breakout": 1.3,
            "bull_bear_tolerance": 0.03, "consolidation_days": (3, 5),
            "consolidation_amplitude": 0.15, "continuation_lookback": (5, 10),
            "pullback_days": (1, 2), "vol_expand_mult": 1.3,
        },
    },
    "B1_B2_B3": {
        "module": b1_b2_b3_strategy,
        "type": "selection",
        "description": "B1→B2→B3递进战法：B1底部挖掘(7条件AND)→B2确认(阳线放量突破白线)→B3锁定(缩量阳线+主力锁仓)，三阶段递进置信度0.6/0.75/0.9",
        "source": "AlphaPulse-A B1→B2→B3递进战法",
        "default_params": {},
    },
    # --- P0因子包（网上语料缺口分析 docs/research_journal/12_*，2026-07-11） ---
    "BBI_INDICATOR": {
        "module": bbi,
        "type": "indicator",
        "description": "BBI多空指标=(MA3+MA6+MA12+MA24)/4，少妇战法止盈/离场基础",
        "source": "少妇战法SOP第5/6步",
        "default_params": {},
    },
    "LUZHU_TAKE_PROFIT": {
        "module": bbi,
        "compute_func": "compute_luzhu",
        "type": "risk",
        "description": "卤煮止盈：站上BBI后连续2根中/大阳线(≥4%)→减半信号",
        "source": "少妇战法SOP第5步",
        "default_params": {"mid_yang_pct": 4.0, "n_yang": 2},
    },
    "BBI_BREAK_EXIT": {
        "module": bbi,
        "compute_func": "compute_bbi_break",
        "type": "risk",
        "description": "BBI两日破位：收盘连续2日<BBI→清仓信号",
        "source": "少妇战法SOP第6步",
        "default_params": {"n_days": 2},
    },
    "SELL_SCORE_V14": {
        "module": sell_score_v14,
        "type": "risk",
        "description": "防卖飞V1.4持仓评分(0-5)：收盘涨/BBI没破/非放量阴/趋势向上/J非死叉。4-5持有,3减半,<3离场。只用于持仓不用于开新仓",
        "source": "sell-discipline 3.10",
        "default_params": {"fangliang_mult": 1.2},
    },
    "MACD_VETO": {
        "module": macd_enhanced,
        "compute_func": "compute_veto",
        "type": "risk",
        "description": "MACD一票否决：DIF<0且近10日无周线底背离→禁止买入",
        "source": "indicators 3.12 MACD指标之王",
        "default_params": {"div_lookback": 10},
    },
    "MACD_ZERO_AXIS": {
        "module": macd_enhanced,
        "compute_func": "compute_zero_axis",
        "type": "factor",
        "description": "MACD零轴多空：DIF>0多头区间（择时/共振门用）",
        "source": "indicators 3.12",
        "default_params": {},
    },
    "MACD_TOP_DIVERGENCE": {
        "module": macd_enhanced,
        "compute_func": "compute_top_divergence",
        "type": "risk",
        "description": "MACD顶背离(日线)：价创60日新高DIF未新高→趋势衰竭警示(S2依据)",
        "source": "indicators 3.12",
        "default_params": {"window": 60},
    },
    "MACD_FAKE_GOLD_CROSS": {
        "module": macd_enhanced,
        "compute_func": "compute_fake_gold_cross",
        "type": "risk",
        "description": "金叉空：欲金叉未成DIF拐头向下=最恶毒的诱多（见金叉多等一天）",
        "source": "indicators 3.12",
        "default_params": {"approach_days": 3, "gap_eps": 0.15},
    },
    "B1_TURNOVER_PATCH": {
        "module": turnover_signals,
        "compute_func": "compute_b1_turnover_patch",
        "type": "factor",
        "description": "B1补丁2：前三根中大阳线累计换手<38%→通过（筹码未发散）",
        "source": "trading-core 3.3 B1双补丁(2026-03-15)",
        "default_params": {"max_cum_turnover": 38.0, "yang_pct": 4.0, "lookback": 60},
    },
    "HIGH_TURNOVER_EXIT": {
        "module": turnover_signals,
        "compute_func": "compute_high_turnover_exit",
        "type": "risk",
        "description": "高位换手出货：4根K线累计换手≥160%→退出信号",
        "source": "indicators 3.9 麒麟会退出信号",
        "default_params": {"window": 4, "threshold": 160.0},
    },
    "WEEKLY_LONG_BULL": {
        "module": weekly_long_bull,
        "type": "factor",
        "description": "B1补丁1：周线55/144/233多头排列且55/144向上（大级别粗筛）",
        "source": "trading-core 3.3 B1双补丁(2026-02-20)",
        "default_params": {"m1": 55, "m2": 144, "m3": 233, "require_rising": True},
    },
    "YELLOW_DISTANCE_OK": {
        "module": b1_entry_filters,
        "compute_func": "compute_yellow_distance_ok",
        "type": "factor",
        "description": "B1入场三问#1：收盘距黄线≤8%（止损可控）→True可做",
        "source": "trading-core 3.0a",
        "default_params": {"max_dist": 0.08},
    },
    "LIFT_WAVE_AVOID": {
        "module": b1_entry_filters,
        "compute_func": "compute_lift_wave_avoid",
        "type": "risk",
        "description": "拉升波回避：近10日涨幅≥15%=拉升波中，此时B1回避(高位余震)",
        "source": "三波理论/indicators高位白线首B1",
        "default_params": {"lift_min_return": 0.15, "lift_window": 10},
    },
    "ZUCHONGZHI_TARGET": {
        "module": zuchongzhi_target,
        "compute_func": "compute_target",
        "type": "indicator",
        "description": "祖冲之目标价=2a-b(a=60日高点,b=60日低点)，到价触发卤煮",
        "source": "advanced-patterns 坑里起好货",
        "default_params": {"lookback": 60},
    },
    # --- P1形态战法包（未过事件研究前不进评分链，见 scripts/p1_event_study.py） ---
    "DUAL_CANNON": {
        "module": zg_advanced_patterns, "compute_func": "compute_dual_cannon",
        "type": "factor",
        "description": "双枪/平行重炮：2根放量阳(≥1.5×MA20,涨≥3%)间隔3-10日，中间全部缩量",
        "source": "advanced-patterns 3.7",
        "default_params": {"gap_min": 3, "gap_max": 10, "cannon_vol_mult": 1.5, "cannon_pct": 3.0},
    },
    "CHANGAN": {
        "module": zg_advanced_patterns, "compute_func": "compute_changan",
        "type": "factor",
        "description": "长安战法：B1(J<-13)→放量长阳无长上影→缩半量分歧转一致(|涨跌|<2%,振幅<7%)",
        "source": "advanced-patterns（宣称75%胜率，待验证）",
        "default_params": {"j_threshold": -13.0, "yang_pct": 5.0, "half_vol": 0.6},
    },
    "NANA_PATTERN": {
        "module": zg_advanced_patterns, "compute_func": "compute_nana",
        "type": "factor",
        "description": "娜娜图：连续放量涨+顶部无巨量阴+连续缩量回调+J负值",
        "source": "advanced-patterns",
        "default_params": {"up_days": 3, "shrink_days": 3, "lookback": 15},
    },
    "RESTLESS_BREAKOUT": {
        "module": zg_advanced_patterns, "compute_func": "compute_restless",
        "type": "factor",
        "description": "跃跃欲试：横盘(20日振幅≤15%)内≥3次巨量阳+红肥绿瘦=蓄势（仅牛市前提）",
        "source": "advanced-patterns",
        "default_params": {"window": 20, "max_amplitude": 15.0, "min_surges": 3},
    },
    "REBUILD_AFTER_DISASTER": {
        "module": zg_advanced_patterns, "compute_func": "compute_rebuild",
        "type": "factor",
        "description": "灾后重建：5日内放量金叉(白穿黄)后缩量回踩黄线±2%=最后震仓",
        "source": "advanced-patterns",
        "default_params": {"cross_lookback": 5, "near_yellow": 0.02},
    },
    "SUPER_B1": {
        "module": zg_advanced_patterns, "compute_func": "compute_super_b1",
        "type": "factor",
        "description": "超级B1：N型上涨→放量下杀阴线(非跌停)→缩量企稳+J负值+反转十字星。只赌一次",
        "source": "trading-core 3.4",
        "default_params": {"uptrend_gain": 0.10, "smash_vol_mult": 1.5},
    },
    "SB1_RECLAIM": {
        "module": zg_advanced_patterns, "compute_func": "compute_sb1_reclaim",
        "type": "factor",
        "description": "SB1假摔：横盘≥3日→放量阴线破平台低点→次日收回=洗盘反包",
        "source": "trading-core 3.5",
        "default_params": {"flat_days": 3, "flat_amp": 8.0},
    },
    "CENTIPEDE_FILTER": {
        "module": zg_advanced_patterns, "compute_func": "compute_centipede",
        "type": "risk",
        "description": "蜈蚣图排除：长影/十字星≥45%+堆量不涨=呼吸紊乱，True=排除不碰",
        "source": "trading-core 3.0b/breathing-theory",
        "default_params": {"window": 20, "messy_ratio": 0.45},
    },
    # --- 筹码理论（换手率衰减引擎，日线近似） ---
    "CHIP_LOW_DENSITY": {
        "module": chip_laws, "compute_func": "compute_low_density",
        "type": "factor",
        "description": "筹码法则一·低位密集：峰值±10%集中≥70%且上方套牢≤30%=行情起点",
        "source": "indicators 3.13 筹码理论",
        "default_params": {"conc_min": 0.70, "above_max": 0.30},
    },
    "CHIP_LOCKED_LIFT": {
        "module": chip_laws, "compute_func": "compute_locked_lift",
        "type": "factor",
        "description": "筹码法则二·锁仓拉升：20日涨≥5%且低位筹码留存≥40%=慢牛基因",
        "source": "indicators 3.13",
        "default_params": {"retention_min": 0.40},
    },
    "CHIP_HIGH_DENSITY_FORBID": {
        "module": chip_laws, "compute_func": "compute_high_density_forbid",
        "type": "risk",
        "description": "筹码法则四·高位密集禁买：低位筹码留存≤20%且现价≥主力成本1.5倍=绝不买",
        "source": "indicators 3.13",
        "default_params": {"retention_max": 0.20, "cost_mult": 1.5},
    },
    # --- Z哥 B1+砖型图 融合选股（独立策略，zettaranc-perspective 体系） ---
    "ZG_B1_BRICK": {
        "module": zg_b1_brick,
        "type": "selection",
        "description": "Z哥融合选股：B1买点(b1_formula 6条件) + 砖型图周期早段确认(第1-2红砖，尾段否决) + 纪律卡(只输一根K线止损/S1离场)。独立于现有B1，效果好再合并",
        "source": "zettaranc-perspective 少妇战法SOP（女娲蒸馏）",
        "default_params": {"early_max": 2, "late_from": 4, "require_brick_early": True},
    },
    "ZG_B1_BRICK_V2": {
        "module": zg_b1_brick,
        "type": "selection",
        "description": "Z哥融合选股v2：B1 ∧ 仅第2砖 ∧ MACD多头区间(DIF>0)。依据11号回测报告(第2砖唯一正增益)+砖型图×MACD共振规则",
        "source": "docs/research_journal/11_* + indicators 3.12共振",
        "default_params": {"positions": [2], "require_dif_positive": True, "late_from": 4},
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
